"""initial schema — Prisma port + Trinity schema-at-scale irreversibles

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-14

This migration hand-writes the physical schema via raw DDL (``op.execute``)
because SQLAlchemy/Alembic autogenerate cannot express:

  * declarative partitioning (LIST / RANGE / HASH),
  * STORED generated columns inside the CREATE TABLE,
  * TimescaleDB hypertables,
  * partial / GIN(jsonb_path_ops) indexes propagated to partitions,
  * per-table autovacuum + fillfactor storage params.

The five Trinity *irreversibles* (cannot be applied online post-data) are baked
in here and must never be retrofitted:

  1. matches            PARTITION BY LIST(season_id) sub RANGE(played_at) monthly
  2. match_participants PARTITION BY HASH(player_id) 16 + denorm played_at +
                        INDEX(player_id, played_at DESC)
  3. integrity_events   PARTITION BY RANGE(created_at) monthly + partial open-queue idx
  4. cr_snapshots       Timescale hypertable on snapshot_at (PK leads with snapshot_at)
  5. players            shadowbanned/banned/restricted real bool cols + partial idx

Reversible-but-pre-traffic items also applied: GIN(jsonb_path_ops) on
integrity_flags/metadata/modifiers, generated winrate column, autovacuum
tuning + fillfactor 85 on player_seasons, timescaledb extension guard.

LEADERBOARD NOTE (do NOT use a 30s REFRESH MATERIALIZED VIEW): per Trinity #6
the leaderboard is served via a **Redis read-through cache** (ZSET, Postgres
authoritative) optionally backed by **pg_ivm** incremental MV. The naive
trigger-maintained full-rank table is a trap (dense-median displacement storm)
and the 30s MV refresh starves autovacuum on player_seasons. No MV is created
here by design.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Extensions
    # ------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")  # gen_random_uuid()
    # TimescaleDB is optional in some envs (CI/local). Guard so the rest of
    # the migration still applies; the hypertable call is guarded too.
    op.execute(
        """
        DO $$
        BEGIN
          CREATE EXTENSION IF NOT EXISTS timescaledb;
        EXCEPTION WHEN OTHERS THEN
          RAISE NOTICE 'timescaledb extension unavailable; cr_snapshots stays a plain table';
        END$$;
        """
    )

    # ------------------------------------------------------------------
    # Enum types
    # ------------------------------------------------------------------
    op.execute("CREATE TYPE season_status AS ENUM ('ACTIVE','SOFT_LOCK','ENDED','OFF_SEASON');")
    op.execute("CREATE TYPE rating_mode AS ENUM ('DUOS','TRIOS');")
    op.execute("CREATE TYPE severity AS ENUM ('INFO','WARN','CRITICAL');")
    op.execute("CREATE TYPE registration_source AS ENUM ('auto','manual');")
    op.execute("CREATE TYPE tournament_status AS ENUM ('upcoming','live','ended');")
    op.execute("CREATE TYPE tournament_match_status AS ENUM ('upcoming','live','ended');")

    # ------------------------------------------------------------------
    # players  (Trinity #5: moderation flags as real bool columns)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE players (
            id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            puuid                varchar(78) NOT NULL,
            summoner_name        varchar(64),
            tag_line             varchar(8),
            region               varchar(8),
            registered_at        timestamptz NOT NULL DEFAULT now(),
            registration_source  registration_source NOT NULL DEFAULT 'auto',
            shadowbanned         boolean NOT NULL DEFAULT false,
            banned               boolean NOT NULL DEFAULT false,
            restricted           boolean NOT NULL DEFAULT false,
            moderation_flags     jsonb NOT NULL DEFAULT '[]'::jsonb,
            anonymized_at        timestamptz,
            CONSTRAINT uq_players_puuid UNIQUE (puuid)
        );
        """
    )
    # Partial indexes — only the (rare) true rows, auth hot-path.
    op.execute(
        "CREATE INDEX ix_players_shadowbanned_true ON players (shadowbanned) "
        "WHERE shadowbanned = true;"
    )
    op.execute("CREATE INDEX ix_players_banned_true ON players (banned) WHERE banned = true;")
    op.execute(
        "CREATE INDEX ix_players_restricted_true ON players (restricted) WHERE restricted = true;"
    )
    # GIN on residual moderation_flags long-tail.
    op.execute(
        "CREATE INDEX ix_players_moderation_flags_gin ON players "
        "USING gin (moderation_flags jsonb_path_ops);"
    )

    # ------------------------------------------------------------------
    # seasons
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE seasons (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name       varchar(64) NOT NULL,
            queue_id   integer NOT NULL,
            starts_at  timestamptz NOT NULL,
            ends_at    timestamptz NOT NULL,
            status     season_status NOT NULL,
            config     jsonb NOT NULL
        );
        """
    )
    op.execute("CREATE INDEX ix_seasons_status ON seasons (status);")

    # ------------------------------------------------------------------
    # player_seasons  (Trinity #6/#8: fillfactor 85 + aggressive autovacuum;
    # leaderboard (season_id, cr DESC) index — NO INCLUDE columns by design)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE player_seasons (
            id                            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            player_id                     uuid NOT NULL REFERENCES players(id),
            season_id                     uuid NOT NULL REFERENCES seasons(id),
            cr                            double precision NOT NULL DEFAULT 1000,
            mu                            double precision NOT NULL DEFAULT 1000,
            sigma                         double precision NOT NULL DEFAULT 350,
            matches_played                integer NOT NULL DEFAULT 0,
            placement_matches_remaining   integer NOT NULL DEFAULT 10,
            is_provisional                boolean NOT NULL DEFAULT true,
            peak_cr                       double precision NOT NULL DEFAULT 1000,
            current_streak                integer NOT NULL DEFAULT 0,
            updated_at                    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_player_seasons_player_season UNIQUE (player_id, season_id)
        ) WITH (
            fillfactor = 85,
            autovacuum_vacuum_scale_factor = 0.02,
            autovacuum_vacuum_cost_limit = 2000,
            autovacuum_vacuum_cost_delay = 2
        );
        """
    )
    op.execute("CREATE INDEX ix_player_seasons_season_cr ON player_seasons (season_id, cr DESC);")

    # ------------------------------------------------------------------
    # matches  (Trinity #1: PARTITION BY LIST(season_id) sub RANGE(played_at))
    # Partition keys (season_id, played_at) are part of every PK/UNIQUE.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE matches (
            id                uuid NOT NULL DEFAULT gen_random_uuid(),
            riot_match_id     varchar(32) NOT NULL,
            queue_id          integer NOT NULL,
            mode              rating_mode NOT NULL,
            season_id         uuid NOT NULL REFERENCES seasons(id),
            played_at         timestamptz NOT NULL,
            processed_at      timestamptz,
            processed         boolean NOT NULL DEFAULT false,
            integrity_flags   jsonb NOT NULL DEFAULT '[]'::jsonb,
            duration_seconds  integer,
            CONSTRAINT pk_matches PRIMARY KEY (id, season_id, played_at),
            CONSTRAINT uq_matches_riot_match_id
                UNIQUE (riot_match_id, season_id, played_at)
        ) PARTITION BY LIST (season_id);
        """
    )
    # Template indexes on the parent — propagated to every partition.
    op.execute("CREATE INDEX ix_matches_played_at ON matches (played_at DESC);")
    op.execute(
        "CREATE INDEX ix_matches_unprocessed ON matches (processed) WHERE processed = false;"
    )
    op.execute(
        "CREATE INDEX ix_matches_integrity_flags_gin ON matches "
        "USING gin (integrity_flags jsonb_path_ops);"
    )
    # DEFAULT season partition (range-subpartitioned) so writes never fail
    # before a season-specific partition is provisioned by the scheduler.
    op.execute(
        "CREATE TABLE matches_default PARTITION OF matches DEFAULT PARTITION BY RANGE (played_at);"
    )
    # One concrete monthly sub-partition so the default is writable out of the
    # box; the scheduler provisions future months + per-season partitions.
    op.execute(
        """
        CREATE TABLE matches_default_2026_06 PARTITION OF matches_default
            FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
        """
    )

    # ------------------------------------------------------------------
    # match_participants  (Trinity #2/#10: HASH(player_id) 16 + denorm
    # played_at + INDEX(player_id, played_at DESC))
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE match_participants (
            id           uuid NOT NULL DEFAULT gen_random_uuid(),
            match_id     uuid NOT NULL,
            player_id    uuid NOT NULL REFERENCES players(id),
            played_at    timestamptz NOT NULL,
            champion_id  integer NOT NULL,
            team_id      integer NOT NULL,
            placement    integer NOT NULL,
            eligible     boolean NOT NULL,
            cr_before    double precision NOT NULL,
            cr_after     double precision NOT NULL,
            cr_delta     double precision NOT NULL,
            is_premade   boolean NOT NULL DEFAULT false,
            party_id     varchar(36),
            modifiers    jsonb NOT NULL,
            CONSTRAINT pk_match_participants PRIMARY KEY (id, player_id),
            CONSTRAINT uq_match_participants_match_player
                UNIQUE (match_id, player_id)
        ) PARTITION BY HASH (player_id);
        """
    )
    # 16 hash partitions.
    for i in range(16):
        op.execute(
            f"CREATE TABLE match_participants_p{i:02d} PARTITION OF match_participants "
            f"FOR VALUES WITH (MODULUS 16, REMAINDER {i});"
        )
    # Profile history pagination (chronological) — propagated to partitions.
    op.execute(
        "CREATE INDEX ix_match_participants_player_played_at "
        "ON match_participants (player_id, played_at DESC);"
    )
    # Head-to-head bitmap-AND support.
    op.execute(
        "CREATE INDEX ix_match_participants_player_match "
        "ON match_participants (player_id, match_id);"
    )
    # GIN on the AppliedModifiers snapshot.
    op.execute(
        "CREATE INDEX ix_match_participants_modifiers_gin ON match_participants "
        "USING gin (modifiers jsonb_path_ops);"
    )

    # ------------------------------------------------------------------
    # champion_stats  (Trinity #10: GENERATED winrate column + index)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE champion_stats (
            id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            player_id            uuid NOT NULL REFERENCES players(id),
            season_id            uuid NOT NULL REFERENCES seasons(id),
            champion_id          integer NOT NULL,
            matches_played       integer NOT NULL DEFAULT 0,
            wins                 integer NOT NULL DEFAULT 0,
            top_half             integer NOT NULL DEFAULT 0,
            total_placement_sum  integer NOT NULL DEFAULT 0,
            cr_delta_sum         double precision NOT NULL DEFAULT 0,
            last10_placements    integer[] NOT NULL DEFAULT '{}'::integer[],
            winrate              numeric GENERATED ALWAYS AS
                                 (wins::numeric / NULLIF(matches_played, 0)) STORED,
            CONSTRAINT uq_champion_stats_player_season_champion
                UNIQUE (player_id, season_id, champion_id)
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_champion_stats_player_season ON champion_stats (player_id, season_id);"
    )
    op.execute(
        "CREATE INDEX ix_champion_stats_player_season_winrate "
        "ON champion_stats (player_id, season_id, winrate DESC);"
    )

    # ------------------------------------------------------------------
    # integrity_events  (Trinity #3: PARTITION BY RANGE(created_at) monthly +
    # partial open-queue index). created_at is part of the PK.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE integrity_events (
            id           uuid NOT NULL DEFAULT gen_random_uuid(),
            match_id     uuid NOT NULL,
            player_id    uuid,
            flag_type    varchar(32) NOT NULL,
            severity     severity NOT NULL,
            metadata     jsonb,
            created_at   timestamptz NOT NULL DEFAULT now(),
            reviewed     boolean NOT NULL DEFAULT false,
            reviewer_id  uuid,
            CONSTRAINT pk_integrity_events PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at);
        """
    )
    op.execute(
        "CREATE INDEX ix_integrity_events_player_created_at "
        "ON integrity_events (player_id, created_at DESC);"
    )
    # Partial open-queue index — PG16 propagates to per-partition indexes.
    op.execute(
        "CREATE INDEX ix_integrity_events_open_queue "
        "ON integrity_events (flag_type, created_at DESC) WHERE reviewed = false;"
    )
    op.execute(
        "CREATE INDEX ix_integrity_events_metadata_gin ON integrity_events "
        "USING gin (metadata jsonb_path_ops);"
    )
    # Seed monthly partition so writes succeed immediately.
    op.execute(
        """
        CREATE TABLE integrity_events_2026_06 PARTITION OF integrity_events
            FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
        """
    )

    # ------------------------------------------------------------------
    # player_achievements
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE player_achievements (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            player_id         uuid NOT NULL REFERENCES players(id),
            season_id         uuid NOT NULL REFERENCES seasons(id),
            achievement_type  varchar(32) NOT NULL,
            tier              varchar(16) NOT NULL,
            rank_value        integer NOT NULL,
            awarded_at        timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_player_achievements_player_season_type
                UNIQUE (player_id, season_id, achievement_type)
        );
        """
    )
    op.execute("CREATE INDEX ix_player_achievements_player ON player_achievements (player_id);")

    # ------------------------------------------------------------------
    # cr_snapshots  (Trinity #4: PK leads with snapshot_at; Timescale hypertable)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE cr_snapshots (
            snapshot_at     timestamptz NOT NULL,
            player_id       uuid NOT NULL,
            season_id       uuid NOT NULL,
            cr              double precision NOT NULL,
            mu              double precision NOT NULL,
            sigma           double precision NOT NULL,
            matches_played  integer NOT NULL,
            CONSTRAINT pk_cr_snapshots PRIMARY KEY (snapshot_at, player_id, season_id)
        );
        """
    )
    # Hypertable (guarded — only if timescaledb is installed). Chunk interval
    # 3 days per Trinity #7 (post event-driven cut). Tunable later via
    # set_chunk_time_interval; only the PK column order is irreversible.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
            PERFORM create_hypertable(
                'cr_snapshots', 'snapshot_at',
                chunk_time_interval => INTERVAL '3 days',
                if_not_exists => TRUE
            );
          END IF;
        END$$;
        """
    )

    # ------------------------------------------------------------------
    # tournaments / tournament_teams / tournament_matches (contract §5)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE tournaments (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            title         varchar(80) NOT NULL,
            format        varchar(8) NOT NULL DEFAULT '3v3',
            status        tournament_status NOT NULL DEFAULT 'upcoming',
            num_teams     integer NOT NULL DEFAULT 6,
            num_matches   integer NOT NULL DEFAULT 3,
            current_match integer NOT NULL DEFAULT 1,
            prize_rp      integer NOT NULL DEFAULT 5000,
            banner_tone   varchar(2) NOT NULL DEFAULT 'b1',
            tag           varchar(32),
            starts_at     timestamptz,
            scoring       jsonb NOT NULL DEFAULT '[]'::jsonb,
            access_key    varchar(32) NOT NULL,
            created_at    timestamptz NOT NULL DEFAULT now(),
            updated_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_tournaments_access_key UNIQUE (access_key)
        );
        """
    )
    op.execute("CREATE INDEX ix_tournaments_status ON tournaments (status);")
    op.execute("CREATE INDEX ix_tournaments_starts_at ON tournaments (starts_at DESC);")

    op.execute(
        """
        CREATE TABLE tournament_teams (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tournament_id  uuid NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
            seed           integer NOT NULL,
            team_name      varchar(80) NOT NULL,
            captain        varchar(80),
            players        jsonb NOT NULL DEFAULT '[]'::jsonb,
            per_match      integer[] NOT NULL DEFAULT '{}'::integer[],
            penalties      integer NOT NULL DEFAULT 0,
            bonus          integer NOT NULL DEFAULT 0,
            total          integer NOT NULL DEFAULT 0,
            CONSTRAINT uq_tournament_teams_tournament_seed UNIQUE (tournament_id, seed)
        );
        """
    )
    op.execute("CREATE INDEX ix_tournament_teams_tournament ON tournament_teams (tournament_id);")

    op.execute(
        """
        CREATE TABLE tournament_matches (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tournament_id  uuid NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
            n              integer NOT NULL,
            status         tournament_match_status NOT NULL DEFAULT 'upcoming',
            winner_team_id uuid,
            starts_at      timestamptz,
            lobby_max      integer NOT NULL DEFAULT 18,
            lobby_count    integer NOT NULL DEFAULT 0,
            magnetic_link  varchar(512),
            result         jsonb,
            CONSTRAINT uq_tournament_matches_tournament_n UNIQUE (tournament_id, n)
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_tournament_matches_tournament ON tournament_matches (tournament_id);"
    )


def downgrade() -> None:
    # Drop in FK-safe order. Partitions drop with their parent (CASCADE).
    op.execute("DROP TABLE IF EXISTS tournament_matches CASCADE;")
    op.execute("DROP TABLE IF EXISTS tournament_teams CASCADE;")
    op.execute("DROP TABLE IF EXISTS tournaments CASCADE;")
    op.execute("DROP TABLE IF EXISTS cr_snapshots CASCADE;")
    op.execute("DROP TABLE IF EXISTS player_achievements CASCADE;")
    op.execute("DROP TABLE IF EXISTS integrity_events CASCADE;")
    op.execute("DROP TABLE IF EXISTS champion_stats CASCADE;")
    op.execute("DROP TABLE IF EXISTS match_participants CASCADE;")
    op.execute("DROP TABLE IF EXISTS matches CASCADE;")
    op.execute("DROP TABLE IF EXISTS player_seasons CASCADE;")
    op.execute("DROP TABLE IF EXISTS seasons CASCADE;")
    op.execute("DROP TABLE IF EXISTS players CASCADE;")

    op.execute("DROP TYPE IF EXISTS tournament_match_status;")
    op.execute("DROP TYPE IF EXISTS tournament_status;")
    op.execute("DROP TYPE IF EXISTS registration_source;")
    op.execute("DROP TYPE IF EXISTS severity;")
    op.execute("DROP TYPE IF EXISTS rating_mode;")
    op.execute("DROP TYPE IF EXISTS season_status;")
