"""SQLAlchemy 2.0 ORM models — port of the Prisma schema + Trinity findings.

Source of truth for the *logical* schema. The physical schema (declarative
partitioning, generated columns, hypertable, partial/GIN indexes, autovacuum
tuning) is materialized by the initial Alembic migration via raw DDL, because
SQLAlchemy has no native partition DDL. Where the physical reality affects the
ORM contract (composite PKs that must lead with the partition key, the
generated ``winrate`` column, the denormalized ``played_at`` on participants,
the moderation bool columns) it is reflected here so the ORM matches Postgres.

Conventions:
* Table names match the Prisma ``@@map`` names (``players``, ``matches`` ...).
* Column names are snake_case; camelCase is applied only in the API/Pydantic
  serialization layer (contract requirement).
* ``mu``/``sigma`` and augment/item winrate are persisted but MUST NOT be
  surfaced by the API-for-UI (use CR/Pontos). That is an API-layer concern.

Partitioning / Trinity map (enforced in migration raw DDL):
* matches              -> PARTITION BY LIST(season_id) / sub RANGE(played_at) monthly
* match_participants   -> PARTITION BY HASH(player_id) 16 + denorm played_at
* integrity_events     -> PARTITION BY RANGE(created_at) monthly + partial open-queue idx
* cr_snapshots         -> Timescale hypertable on snapshot_at, PK leads with snapshot_at
* players              -> shadowbanned/banned/restricted real bool cols + partial idx
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Date,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from arena.db.base import Base, uuid_pk

# ---------------------------------------------------------------------------
# Enums (native PG enums; mirror the Prisma enums verbatim)
# ---------------------------------------------------------------------------


class SeasonStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    SOFT_LOCK = "SOFT_LOCK"
    ENDED = "ENDED"
    OFF_SEASON = "OFF_SEASON"


class RatingMode(enum.Enum):
    DUOS = "DUOS"
    TRIOS = "TRIOS"


class Severity(enum.Enum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


class RegistrationSource(enum.Enum):
    auto = "auto"
    manual = "manual"


class IngestMode(enum.Enum):
    """Como uma temporada trata partidas recém-descobertas.

    ``catching_up`` — não avalia nada: as partidas vão para ``match_backlog`` e
    depois são drenadas em ordem cronológica estrita. É o modo de um refill (DB
    vazio, janela de temporada retroativa), em que a descoberta chega em ordem
    essencialmente arbitrária e avaliar na chegada produziria um ladder que
    reflete ordem de chegada, não ordem de jogo.

    ``live`` — regime normal: avalia na chegada. Partidas atrasadas ainda
    acontecem (um jogador descoberto hoje pode ter jogado há 15 dias) e são
    tratadas pelo ``replay_floor`` + replay incremental, não por este modo.
    """

    catching_up = "catching_up"
    live = "live"


class TournamentStatus(enum.Enum):
    upcoming = "upcoming"
    live = "live"
    ended = "ended"


class TournamentMatchStatus(enum.Enum):
    upcoming = "upcoming"
    live = "live"
    ended = "ended"


class OperatorRole(enum.Enum):
    owner = "owner"
    admin = "admin"
    moderator = "moderator"
    analyst = "analyst"
    support = "support"


def _pg_enum(py_enum: type[enum.Enum], name: str) -> Enum:
    """Native PG enum that stores the *value* (lower/upper preserved)."""
    return Enum(
        py_enum,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        create_type=True,
    )


# ---------------------------------------------------------------------------
# players  (Trinity #5: moderation flags promoted to real bool columns)
# ---------------------------------------------------------------------------


class Player(Base):
    __tablename__ = "players"

    id: Mapped[uuid.UUID] = uuid_pk()
    puuid: Mapped[str] = mapped_column(String(78), unique=True)
    summoner_name: Mapped[str | None] = mapped_column(String(64))
    tag_line: Mapped[str | None] = mapped_column(String(8))
    region: Mapped[str | None] = mapped_column(String(8))
    # Data Dragon (ddragon) summoner profile icon id from match-v5 ``profileIcon``.
    # Nullable: backfilled lazily on next match ingest for pre-existing rows.
    profile_icon_id: Mapped[int | None] = mapped_column(Integer)
    registered_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
    registration_source: Mapped[RegistrationSource] = mapped_column(
        _pg_enum(RegistrationSource, "registration_source"),
        server_default=text("'auto'"),
    )

    # Trinity #5 — auth/profile hot-path flags as real columns + partial idx.
    shadowbanned: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    banned: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    restricted: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)

    # Admin-selected priority ingestion flag (priority sweep worker).
    is_selected: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )

    # Long-tail unstructured moderation metadata stays JSONB.
    moderation_flags: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )

    # D2.8 GDPR right-to-erasure marker.
    anonymized_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    player_seasons: Mapped[list[PlayerSeason]] = relationship(back_populates="player")
    participants: Mapped[list[MatchParticipant]] = relationship(back_populates="player")
    champion_stats: Mapped[list[ChampionStat]] = relationship(back_populates="player")
    achievements: Mapped[list[PlayerAchievement]] = relationship(back_populates="player")

    __table_args__ = (
        # Partial indexes on each flag (tiny — only true rows). Mirrored in
        # raw DDL too; declaring here lets autogenerate stay consistent.
        Index(
            "ix_players_shadowbanned_true",
            "shadowbanned",
            postgresql_where=text("shadowbanned = true"),
        ),
        Index(
            "ix_players_banned_true",
            "banned",
            postgresql_where=text("banned = true"),
        ),
        Index(
            "ix_players_restricted_true",
            "restricted",
            postgresql_where=text("restricted = true"),
        ),
        Index(
            "ix_players_is_selected_true",
            "is_selected",
            postgresql_where=text("is_selected = true"),
        ),
        # GIN on residual moderation_flags long-tail (Trinity #11).
        Index(
            "ix_players_moderation_flags_gin",
            "moderation_flags",
            postgresql_using="gin",
            postgresql_ops={"moderation_flags": "jsonb_path_ops"},
        ),
    )


# ---------------------------------------------------------------------------
# seasons
# ---------------------------------------------------------------------------


class Season(Base):
    __tablename__ = "seasons"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(64))
    queue_id: Mapped[int] = mapped_column(Integer)
    starts_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[SeasonStatus] = mapped_column(_pg_enum(SeasonStatus, "season_status"))
    # placementCount, resetFactor, cap params (mirrors RatingParams).
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    player_seasons: Mapped[list[PlayerSeason]] = relationship(back_populates="season")
    matches: Mapped[list[Match]] = relationship(back_populates="season")
    champion_stats: Mapped[list[ChampionStat]] = relationship(back_populates="season")
    achievements: Mapped[list[PlayerAchievement]] = relationship(back_populates="season")

    __table_args__ = (Index("ix_seasons_status", "status"),)


# ---------------------------------------------------------------------------
# player_seasons  (Trinity #6/#8: leaderboard hot table — fillfactor 85 +
# aggressive autovacuum applied in migration; (season_id, cr DESC) index)
# ---------------------------------------------------------------------------


class PlayerSeason(Base):
    __tablename__ = "player_seasons"
    # Don't RETURNING server-side defaults (e.g. updated_at) on insert — fetching
    # them per row disables insertmanyvalues batching. They're read back lazily
    # if ever needed (we don't on the write path). See uuid_pk() rationale.
    __mapper_args__ = {"eager_defaults": False}

    id: Mapped[uuid.UUID] = uuid_pk()
    player_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("players.id"))
    season_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("seasons.id"))
    cr: Mapped[float] = mapped_column(Float, server_default=text("1000"))
    mu: Mapped[float] = mapped_column(Float, server_default=text("1000"))
    sigma: Mapped[float] = mapped_column(Float, server_default=text("350"))
    matches_played: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    placement_matches_remaining: Mapped[int] = mapped_column(Integer, server_default=text("10"))
    is_provisional: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    peak_cr: Mapped[float] = mapped_column(Float, server_default=text("1000"))
    current_streak: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
    )

    player: Mapped[Player] = relationship(back_populates="player_seasons")
    season: Mapped[Season] = relationship(back_populates="player_seasons")

    __table_args__ = (
        UniqueConstraint("player_id", "season_id", name="uq_player_seasons_player_season"),
        # Leaderboard scan (§8.2). cr DESC because we rank high-to-low.
        Index(
            "ix_player_seasons_season_cr",
            "season_id",
            text("cr DESC"),
        ),
    )


# ---------------------------------------------------------------------------
# matches  (Trinity #1: PARTITION BY LIST(season_id) sub RANGE(played_at))
# Partition keys (season_id, played_at) MUST be part of the PK.
# ---------------------------------------------------------------------------


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    riot_match_id: Mapped[str] = mapped_column(String(32))
    queue_id: Mapped[int] = mapped_column(Integer)
    mode: Mapped[RatingMode] = mapped_column(_pg_enum(RatingMode, "rating_mode"))
    season_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("seasons.id"))
    played_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    processed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    integrity_flags: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    duration_seconds: Mapped[int | None] = mapped_column(Integer)

    season: Mapped[Season] = relationship(back_populates="matches")
    # `matches` is partitioned (composite PK), so Postgres has no FK from the
    # child tables back to it. Declare explicit id-only primaryjoins so the ORM
    # can resolve the relationship without a DB-level ForeignKey.
    participants: Mapped[list[MatchParticipant]] = relationship(
        back_populates="match",
        primaryjoin="Match.id == foreign(MatchParticipant.match_id)",
    )
    integrity_events: Mapped[list[IntegrityEvent]] = relationship(
        back_populates="match",
        primaryjoin="Match.id == foreign(IntegrityEvent.match_id)",
    )

    __table_args__ = (
        # Partition key columns must be in the PK on a partitioned table.
        PrimaryKeyConstraint("id", "season_id", "played_at", name="pk_matches"),
        # riot_match_id unique must also include partition keys on a
        # partitioned table; the global dedup is enforced additionally by the
        # ingestion layer + a btree the migration creates per Postgres rules.
        UniqueConstraint(
            "riot_match_id",
            "season_id",
            "played_at",
            name="uq_matches_riot_match_id",
        ),
        Index("ix_matches_played_at", text("played_at DESC")),
        # Partial unprocessed index — ingestion scan (created WHERE
        # processed=false in raw DDL; declared here for parity).
        Index(
            "ix_matches_unprocessed",
            "processed",
            postgresql_where=text("processed = false"),
        ),
        # GIN on integrity_flags (Trinity #11).
        Index(
            "ix_matches_integrity_flags_gin",
            "integrity_flags",
            postgresql_using="gin",
            postgresql_ops={"integrity_flags": "jsonb_path_ops"},
        ),
    )


# ---------------------------------------------------------------------------
# match_participants  (Trinity #2/#10: PARTITION BY HASH(player_id) 16 +
# DENORMALIZED played_at + INDEX(player_id, played_at DESC))
# Partition key (player_id) MUST be in the PK.
# ---------------------------------------------------------------------------


class MatchParticipant(Base):
    __tablename__ = "match_participants"
    # See id below + uuid_pk(): keep inserts batchable (no per-row RETURNING).
    __mapper_args__ = {"eager_defaults": False}

    # Client-side default (not just server_default) so a 16-row participant
    # flush batches into ONE INSERT instead of 16 INSERT...RETURNING round-trips
    # (the ORM needs the PK up front to skip per-row RETURNING). See uuid_pk().
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    match_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    player_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("players.id"))
    # Trinity #10 — denormalized from matches.played_at; enables chronological
    # profile pagination (cuid/uuid PKs are not time-ordered) and matches-side
    # partition pruning. Kept in sync via trigger on rare played_at correction.
    played_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    champion_id: Mapped[int] = mapped_column(Integer)
    team_id: Mapped[int] = mapped_column(Integer)
    placement: Mapped[int] = mapped_column(Integer)
    eligible: Mapped[bool] = mapped_column(Boolean)
    cr_before: Mapped[float] = mapped_column(Float)
    cr_after: Mapped[float] = mapped_column(Float)
    cr_delta: Mapped[float] = mapped_column(Float)
    is_premade: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    party_id: Mapped[str | None] = mapped_column(String(36))
    # AppliedModifiers snapshot from the rating-engine.
    modifiers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # RESTORE POINT: o PlayerState deste jogador IMEDIATAMENTE ANTES desta
    # partida (ver services/rating_service.py::state_before_to_json). É o que
    # torna possível o replay incremental "a partir de T": para reprocessar em
    # ordem cronológica a partir de um instante, é preciso restaurar mu/sigma de
    # cada jogador naquele ponto, e isso NÃO era recuperável — ``cr_snapshots``
    # é carimbado com o relógio de PROCESSAMENTO (não com played_at, logo
    # inútil como índice temporal quando o processamento saiu de ordem), e
    # ``cr_before`` sozinho não inverte cr = (mu - 3*sigma)*scale + offset (uma
    # equação, duas incógnitas). Com played_at já denormalizado aqui, cada linha
    # vira um ponto de restauração completo.
    #
    # NULL nas linhas anteriores à migração 0014: o replay incremental se recusa
    # a atravessar um NULL e exige um rerate de temporada inteira primeiro.
    state_before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    match: Mapped[Match] = relationship(
        back_populates="participants",
        primaryjoin="Match.id == foreign(MatchParticipant.match_id)",
    )
    player: Mapped[Player] = relationship(back_populates="participants")

    __table_args__ = (
        # HASH(player_id) partition key must be in the PK.
        PrimaryKeyConstraint("id", "player_id", name="pk_match_participants"),
        UniqueConstraint("match_id", "player_id", name="uq_match_participants_match_player"),
        # Profile history pagination (Trinity #10) — chronological.
        Index(
            "ix_match_participants_player_played_at",
            "player_id",
            text("played_at DESC"),
        ),
        # Head-to-head A∩B bitmap-AND support (§8.2).
        Index("ix_match_participants_player_match", "player_id", "match_id"),
        # GIN on the AppliedModifiers snapshot (Trinity #11).
        Index(
            "ix_match_participants_modifiers_gin",
            "modifiers",
            postgresql_using="gin",
            postgresql_ops={"modifiers": "jsonb_path_ops"},
        ),
    )


# ---------------------------------------------------------------------------
# champion_stats  (Trinity #10: GENERATED winrate column + index)
# ---------------------------------------------------------------------------


class ChampionStat(Base):
    __tablename__ = "champion_stats"
    # Skip eager RETURNING of the GENERATED winrate column on insert so a
    # multi-row flush batches; winrate is read lazily (and only via the API).
    __mapper_args__ = {"eager_defaults": False}

    id: Mapped[uuid.UUID] = uuid_pk()
    player_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("players.id"))
    season_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("seasons.id"))
    champion_id: Mapped[int] = mapped_column(Integer)
    matches_played: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    wins: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    top_half: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    total_placement_sum: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cr_delta_sum: Mapped[float] = mapped_column(Float, server_default=text("0"))
    last10_placements: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), server_default=text("'{}'::integer[]"), nullable=False
    )

    # Trinity #10 — STORED generated column. NOTE: champion (not augment/item)
    # winrate; still must NOT be exposed by API-for-UI (internal analytics).
    winrate: Mapped[float | None] = mapped_column(
        Numeric,
        Computed("wins::numeric / NULLIF(matches_played, 0)", persisted=True),
    )

    player: Mapped[Player] = relationship(back_populates="champion_stats")
    season: Mapped[Season] = relationship(back_populates="champion_stats")

    __table_args__ = (
        UniqueConstraint(
            "player_id",
            "season_id",
            "champion_id",
            name="uq_champion_stats_player_season_champion",
        ),
        Index("ix_champion_stats_player_season", "player_id", "season_id"),
        Index(
            "ix_champion_stats_player_season_winrate",
            "player_id",
            "season_id",
            text("winrate DESC"),
        ),
        # Champion-first index for the per-champion "best players" leaderboard:
        # rank players within a (champion_id, season_id) by matches_played DESC
        # (index-ordered scan). champion_stats' other indexes are player-first.
        Index(
            "ix_champion_stats_champion_season_games",
            "champion_id",
            "season_id",
            text("matches_played DESC"),
        ),
    )


# ---------------------------------------------------------------------------
# integrity_events  (Trinity #3: PARTITION BY RANGE(created_at) monthly +
# partial open-queue index). Partition key (created_at) MUST be in the PK.
# ---------------------------------------------------------------------------


class IntegrityEvent(Base):
    __tablename__ = "integrity_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    match_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    player_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    flag_type: Mapped[str] = mapped_column(String(32))
    severity: Mapped[Severity] = mapped_column(_pg_enum(Severity, "severity"))
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
    reviewed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    match: Mapped[Match] = relationship(
        back_populates="integrity_events",
        primaryjoin="Match.id == foreign(IntegrityEvent.match_id)",
    )

    __table_args__ = (
        # RANGE(created_at) partition key must be in the PK.
        PrimaryKeyConstraint("id", "created_at", name="pk_integrity_events"),
        Index(
            "ix_integrity_events_player_created_at",
            "player_id",
            text("created_at DESC"),
        ),
        # Open moderation queue — partial. PG16 propagates to partitions.
        Index(
            "ix_integrity_events_open_queue",
            "flag_type",
            text("created_at DESC"),
            postgresql_where=text("reviewed = false"),
        ),
        # GIN on metadata (Trinity #11). DB column name is ``metadata``.
        Index(
            "ix_integrity_events_metadata_gin",
            "metadata",
            postgresql_using="gin",
            postgresql_ops={"metadata": "jsonb_path_ops"},
        ),
    )


# ---------------------------------------------------------------------------
# player_achievements  (no pathology per audit — UNIQUE is correct)
# ---------------------------------------------------------------------------


class PlayerAchievement(Base):
    __tablename__ = "player_achievements"

    id: Mapped[uuid.UUID] = uuid_pk()
    player_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("players.id"))
    season_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("seasons.id"))
    achievement_type: Mapped[str] = mapped_column(String(32))
    tier: Mapped[str] = mapped_column(String(16))
    rank_value: Mapped[int] = mapped_column(Integer)
    awarded_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )

    player: Mapped[Player] = relationship(back_populates="achievements")
    season: Mapped[Season] = relationship(back_populates="achievements")

    __table_args__ = (
        UniqueConstraint(
            "player_id",
            "season_id",
            "achievement_type",
            name="uq_player_achievements_player_season_type",
        ),
        Index("ix_player_achievements_player", "player_id"),
    )


# ---------------------------------------------------------------------------
# cr_snapshots  (Trinity #4: Timescale hypertable; PK leads with snapshot_at)
# ---------------------------------------------------------------------------


class CrSnapshot(Base):
    __tablename__ = "cr_snapshots"

    snapshot_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    player_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    season_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    cr: Mapped[float] = mapped_column(Float)
    mu: Mapped[float] = mapped_column(Float)
    sigma: Mapped[float] = mapped_column(Float)
    matches_played: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        # Trinity #4 — time/partitioning column leads for chunk-aligned
        # uniqueness (TimescaleDB requirement).
        PrimaryKeyConstraint("snapshot_at", "player_id", "season_id", name="pk_cr_snapshots"),
    )


# ---------------------------------------------------------------------------
# cr_snapshots_recent  (T2.3, workaround_readpath) — carve-out PLANO da janela
# da temporada corrente. Hypertables Timescale não replicam logicamente para um
# Postgres vanilla; esta tabela plana entra na publicação `arena_read` e serve
# o delta7d do read path na réplica. Dual-write no RatingService (junto do
# CrSnapshot) + purge de temporadas antigas no cron do SchedulerWorker.
# ---------------------------------------------------------------------------


class CrSnapshotRecent(Base):
    __tablename__ = "cr_snapshots_recent"

    player_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    season_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    snapshot_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    cr: Mapped[float] = mapped_column(Float)
    mu: Mapped[float] = mapped_column(Float)
    sigma: Mapped[float] = mapped_column(Float)
    matches_played: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        # Player leads: o delta7d agrupa por player dentro da temporada.
        PrimaryKeyConstraint(
            "player_id", "season_id", "snapshot_at", name="pk_cr_snapshots_recent"
        ),
    )


# ---------------------------------------------------------------------------
# champion_daily_stats  (B1/B2 — per-champion daily rollup). Placement-derived,
# season-scoped. Tabela PLANA replicável (entra na publicação ``arena_read``):
# o read path na réplica lê o rollup em vez de reagregar ``match_participants``
# a cada request na t3.micro — é a fonte da tierlist ``/champions``, do delta 7d
# e das séries de trend. Escrita: cron ``champion_daily_maintenance`` (recompute
# dos dias recentes) + backfill one-shot na migração. Deriva de
# ``match_participants`` (played_at denormalizado) — NÃO precisa de ingestão
# nova. ToS: placement-derived, nunca winrate de augment/item.
# ---------------------------------------------------------------------------


class ChampionDailyStat(Base):
    __tablename__ = "champion_daily_stats"
    # Multi-row upsert do cron: sem RETURNING per-row (mantém o flush batchado).
    __mapper_args__ = {"eager_defaults": False}

    snapshot_date: Mapped[date] = mapped_column(Date)
    season_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    champion_id: Mapped[int] = mapped_column(Integer)
    games: Mapped[int] = mapped_column(Integer)  # participações elegíveis no dia
    top4: Mapped[int] = mapped_column(Integer)  # placement <= 4 (top-half do contrato)
    first_place: Mapped[int] = mapped_column(Integer)  # placement == 1
    placement_sum: Mapped[int] = mapped_column(Integer)  # p/ colocação média do dia

    __table_args__ = (
        # (season, champion) lidera: a query de trend filtra por campeão dentro
        # da temporada e faz range no dia.
        PrimaryKeyConstraint(
            "season_id", "champion_id", "snapshot_date", name="pk_champion_daily_stats"
        ),
        # Totais diários (pick-rate), a janela do delta 7d e o SUM da tierlist
        # agrupam por dia sobre todos os campeões da temporada.
        Index("ix_champion_daily_stats_season_date", "season_id", "snapshot_date"),
    )


# ---------------------------------------------------------------------------
# match_backlog — área de espera das partidas descobertas durante um refill.
#
# Guarda a partida JÁ PARSEADA (``ParsedArenaMatch``), não o payload cru da
# match-v5: ~2,5 kB contra ~75 kB por partida (≈180 MB em vez de ≈5 GB numa
# temporada de 71k), e evita re-buscar na Riot ao drenar — o cache de payload
# vive só 24 h (riot/cache.py), curto demais para uma janela de 20 dias.
#
# ``played_at`` é extraído de ``gameStartTimestamp`` no momento do parse, então a
# ordenação cronológica é possível SEM tocar no payload de novo.
# ---------------------------------------------------------------------------


class MatchBacklog(Base):
    __tablename__ = "match_backlog"
    __mapper_args__ = {"eager_defaults": False}

    riot_match_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    season_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    # De ParsedArenaMatch.started_at_ms — hora de JOGO, nunca a de processamento.
    played_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    parsed: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        # A drenagem lê exatamente nesta ordem: (temporada, played_at asc).
        Index("ix_match_backlog_season_played", "season_id", "played_at"),
    )


# ---------------------------------------------------------------------------
# season_ingest_state — o modo de ingestão de uma temporada + o que o console
# mostra durante um refill. Uma linha por temporada.
# ---------------------------------------------------------------------------


class SeasonIngestState(Base):
    __tablename__ = "season_ingest_state"
    __mapper_args__ = {"eager_defaults": False}

    season_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    mode: Mapped[IngestMode] = mapped_column(
        _pg_enum(IngestMode, "ingest_mode"), server_default=text("'live'")
    )
    # Piso do replay incremental: o played_at MAIS ANTIGO avaliado fora de ordem
    # desde o último replay. NULL = nada pendente. Não dispara por partida (um
    # jogador novo traz partidas velhas o tempo todo e isso seria thrashing);
    # um cron consome quando as filas esvaziam.
    replay_floor: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    # Progresso do bootstrap (só telemetria de console).
    frontier_pending: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    frontier_done: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    saturated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    # Estimativa de cobertura da última amostragem do audit (0..100), e quando.
    coverage_pct: Mapped[float | None] = mapped_column(Float)
    coverage_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )


# ---------------------------------------------------------------------------
# champion_combo_stats — sinergias (duplas/trios) materializadas.
#
# As rotas /champions/synergy* faziam self-join de 2 ou 3 vias sobre
# match_participants a cada request: medido na temporada com 1,2M participações,
# 8,0 s / 63,5M buffers / ~285 MB em temp para duplas e 19,1 s / ~530 MB para
# trios — PIOR que o scan que fazia o OOM killer derrubar a api na t3.micro, e
# fora do circuit breaker do Caddy. Este rollup é cumulativo por TEMPORADA (não
# por dia como champion_daily_stats: 308k trios distintos × N dias explodiria a
# tabela; agregado por temporada são ~21k linhas com o piso de escrita).
#
# ``c2 = 0`` marca "ausente" numa dupla — champion ids são positivos, e um
# sentinela mantém a PK simples e NOT NULL (uma coluna anulável não entra em PK).
# ToS: placement-derived, nunca winrate de augment/item.
# ---------------------------------------------------------------------------


class ChampionComboStat(Base):
    __tablename__ = "champion_combo_stats"
    __mapper_args__ = {"eager_defaults": False}

    season_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    size: Mapped[int] = mapped_column(SmallInteger)  # 2 = dupla, 3 = trio
    c0: Mapped[int] = mapped_column(Integer)  # combo ordenado por championId asc
    c1: Mapped[int] = mapped_column(Integer)
    c2: Mapped[int] = mapped_column(Integer, server_default=text("0"))  # 0 = ausente
    games: Mapped[int] = mapped_column(Integer)
    top4: Mapped[int] = mapped_column(Integer)  # placement <= 4 (top-half do contrato)
    first_place: Mapped[int] = mapped_column(Integer)  # placement == 1
    placement_sum: Mapped[int] = mapped_column(Integer)  # p/ colocação média

    __table_args__ = (
        PrimaryKeyConstraint("season_id", "size", "c0", "c1", "c2", name="pk_champion_combo_stats"),
        # A leitura pega o topo por jogos dentro de (temporada, tamanho) antes do
        # re-rank de Wilson em Python.
        Index("ix_champion_combo_stats_season_size_games", "season_id", "size", "games"),
    )


# ---------------------------------------------------------------------------
# season_record_cache — resultado materializado de ``/meta/records``.
#
# Os cinco records da temporada custavam um GROUP BY player_id sobre TODOS os
# participants elegíveis (~127k jogadores materializados) + um sort sem índice
# em cr_delta — a segunda rota que o OOM killer derrubava na t3.micro. Em vez de
# um rollup por jogador (grande demais), cacheamos o RESULTADO: no máximo 5
# linhas por temporada, uma por ``key``. Escrita: cron
# ``season_records_maintenance``; leitura: um SELECT indexado. Tabela plana e
# minúscula — entra na publicação ``arena_read``.
# ---------------------------------------------------------------------------


class SeasonRecordCache(Base):
    __tablename__ = "season_record_cache"
    __mapper_args__ = {"eager_defaults": False}

    season_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    # streak | biggest_gain | most_today | first_rate | top4_rate (RawRecord.key)
    key: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(64))  # rótulo PT-BR já formatado
    value: Mapped[str] = mapped_column(String(32))  # valor já formatado ("14", "+72", "42%")
    # Detentor do record; o router hidrata nome/handle/avatar a partir daqui.
    player_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    accent: Mapped[str] = mapped_column(String(32))  # dica de cor para a UI
    computed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        PrimaryKeyConstraint("season_id", "key", name="pk_season_record_cache"),
    )


# ---------------------------------------------------------------------------
# Tournaments (api_contract_v1 §5) — first-class persisted subsystem.
# ---------------------------------------------------------------------------


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(String(80))
    format: Mapped[str] = mapped_column(String(8), server_default=text("'3v3'"))
    status: Mapped[TournamentStatus] = mapped_column(
        _pg_enum(TournamentStatus, "tournament_status"),
        server_default=text("'upcoming'"),
    )
    num_teams: Mapped[int] = mapped_column(Integer, server_default=text("6"))
    num_matches: Mapped[int] = mapped_column(Integer, server_default=text("3"))
    current_match: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    prize_rp: Mapped[int] = mapped_column(Integer, server_default=text("5000"))
    banner_tone: Mapped[str] = mapped_column(String(2), server_default=text("'b1'"))
    tag: Mapped[str | None] = mapped_column(String(32))
    starts_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    # scoring table [{place, points}], tiebreak rules, prize rows, etc.
    scoring: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    # Admin-only access key (ARENA-XXXXXX). Never exposed to non-admin reads.
    access_key: Mapped[str] = mapped_column(String(32), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
    )

    teams: Mapped[list[TournamentTeam]] = relationship(
        back_populates="tournament", cascade="all, delete-orphan"
    )
    tournament_matches: Mapped[list[TournamentMatch]] = relationship(
        back_populates="tournament", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_tournaments_status", "status"),
        Index("ix_tournaments_starts_at", text("starts_at DESC")),
    )


class TournamentTeam(Base):
    __tablename__ = "tournament_teams"

    id: Mapped[uuid.UUID] = uuid_pk()
    tournament_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tournaments.id", ondelete="CASCADE")
    )
    seed: Mapped[int] = mapped_column(Integer)
    team_name: Mapped[str] = mapped_column(String(80))
    captain: Mapped[str | None] = mapped_column(String(80))
    # Player slots: [{name,handle,riotId,avatar}] or [{empty:true}].
    players: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    # Scoring running totals.
    per_match: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), server_default=text("'{}'::integer[]"), nullable=False
    )
    penalties: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    bonus: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    total: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    tournament: Mapped[Tournament] = relationship(back_populates="teams")

    __table_args__ = (
        UniqueConstraint("tournament_id", "seed", name="uq_tournament_teams_tournament_seed"),
        Index("ix_tournament_teams_tournament", "tournament_id"),
    )


class TournamentMatch(Base):
    __tablename__ = "tournament_matches"

    id: Mapped[uuid.UUID] = uuid_pk()
    tournament_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tournaments.id", ondelete="CASCADE")
    )
    n: Mapped[int] = mapped_column(Integer)  # 1..numMatches
    status: Mapped[TournamentMatchStatus] = mapped_column(
        _pg_enum(TournamentMatchStatus, "tournament_match_status"),
        server_default=text("'upcoming'"),
    )
    winner_team_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    starts_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    lobby_max: Mapped[int] = mapped_column(Integer, server_default=text("18"))
    lobby_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    magnetic_link: Mapped[str | None] = mapped_column(String(512))
    # result: [{teamId, placement, bravura}]
    result: Mapped[list[Any] | None] = mapped_column(JSONB)

    tournament: Mapped[Tournament] = relationship(back_populates="tournament_matches")

    __table_args__ = (
        UniqueConstraint("tournament_id", "n", name="uq_tournament_matches_tournament_n"),
        Index("ix_tournament_matches_tournament", "tournament_id"),
    )


# ---------------------------------------------------------------------------
# champion_build_ref  (PROVISIONAL — reference build data, remove when native
# augment ingestion lands)
#
# Caches a per-champion Arena aggregate — augment / item / teammate placement
# stats — as one JSONB snapshot per (champion_id, patch), backing a stop-gap
# "build recomendada" surface until our own ingestion captures augment/item
# data. Self-contained + clearly named so the whole feature drops in one pass
# (this class, migration 0006, scripts/fetch_build_ref.py).
# ---------------------------------------------------------------------------


class ChampionBuildRef(Base):
    __tablename__ = "champion_build_ref"

    champion_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patch: Mapped[str] = mapped_column(String, primary_key=True)
    dt: Mapped[str | None] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
    )


# ---------------------------------------------------------------------------
# admin_operators — per-operator RBAC identities (arena/api/rbac.py).
#
# The env ADMIN_API_KEY (arena/core/config.py) stays a separate, permanent
# "Owner" bootstrap credential and is never stored here — this table is only
# for additional named operators. Keys are high-entropy random tokens (never
# user-chosen), so a fast deterministic hash + unique-index lookup is the
# right tradeoff (no bcrypt/scrypt needed, unlike a user password).
# ---------------------------------------------------------------------------


class AdminOperator(Base):
    __tablename__ = "admin_operators"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(254), unique=True)
    role: Mapped[OperatorRole] = mapped_column(_pg_enum(OperatorRole, "operator_role"))
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # Last chars of the plaintext key, for display only ("…a1b2c3") — never
    # enough to reconstruct or brute-force the real key from this column.
    key_prefix: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    __table_args__ = (
        Index(
            "ix_admin_operators_active",
            "revoked_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )


# ---------------------------------------------------------------------------
# admin_audit_events — immutable trail of privileged actions
# (arena/api/rbac.py::record_audit, called from every admin mutation route).
# Written best-effort in its own short transaction, independent of whatever
# DB/Redis transaction the mutation itself used — several admin actions
# (DLQ/worker/queue ops) only ever touch Redis and have no DB session to
# piggyback on, and a logging failure must never break the real action.
# ---------------------------------------------------------------------------


class AdminAuditEvent(Base):
    __tablename__ = "admin_audit_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    occurred_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
    )
    # Operator email, or "env:ADMIN_API_KEY" for the bootstrap Owner key —
    # whatever require_scope resolved onto request.state.actor.
    actor: Mapped[str] = mapped_column(String(254))
    # "<domain>.<verb>", e.g. "worker.paused", "dlq.requeued" — the prefix
    # before the dot buckets into a UI filter chip (workers/moderacao/dlq/
    # temporada/campeonatos/acesso); see rbac.py::audit_kind.
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(200))
    source_ip: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(16), server_default=text("'ok'"), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )

    __table_args__ = (Index("ix_admin_audit_events_occurred_at", "occurred_at"),)


__all__ = [
    "Base",
    "BigInteger",  # re-export for migration convenience
    "SeasonStatus",
    "RatingMode",
    "Severity",
    "RegistrationSource",
    "TournamentStatus",
    "TournamentMatchStatus",
    "Player",
    "Season",
    "PlayerSeason",
    "Match",
    "MatchParticipant",
    "ChampionStat",
    "IntegrityEvent",
    "PlayerAchievement",
    "CrSnapshot",
    "CrSnapshotRecent",
    "ChampionDailyStat",
    "ChampionComboStat",
    "SeasonRecordCache",
    "IngestMode",
    "MatchBacklog",
    "SeasonIngestState",
    "Tournament",
    "TournamentTeam",
    "TournamentMatch",
    "ChampionBuildRef",
    "OperatorRole",
    "AdminOperator",
    "AdminAuditEvent",
]
