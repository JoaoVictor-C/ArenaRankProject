"""champion_daily_stats — rollup diário por campeão (tierlist + trend + delta 7d)

Revision ID: 0011_champion_daily_stats
Revises: 0010_admin_audit_events

B1/B2. Tabela PLANA replicável (entra na publicação ``arena_read``): o read path
na réplica lê o rollup em vez de reagregar ``match_participants`` (30d de scan) a
cada request na t3.micro faminta. Deriva de ``match_participants`` (``played_at``
denormalizado) — NÃO precisa de ingestão nova. Escrita: cron
``champion_daily_maintenance`` (dias recentes) + este backfill histórico one-shot.

Backfill: roda no PRIMÁRIO (alembic nunca aponta para a réplica); em DB fresco
(sem partidas) insere zero linhas. Idempotente via ON CONFLICT DO NOTHING. A data
é UTC-explícita (``AT TIME ZONE 'UTC'``) para bater com o cron
(``cast(timezone('UTC', played_at), Date)``) independente do timezone da sessão.
ToS: placement-derived (top-half/1º/colocação), nunca winrate de augment/item.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_champion_daily_stats"
down_revision: str | None = "0010_admin_audit_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "champion_daily_stats",
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("season_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("champion_id", sa.Integer(), nullable=False),
        sa.Column("games", sa.Integer(), nullable=False),
        sa.Column("top4", sa.Integer(), nullable=False),
        sa.Column("first_place", sa.Integer(), nullable=False),
        sa.Column("placement_sum", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "season_id", "champion_id", "snapshot_date", name="pk_champion_daily_stats"
        ),
    )
    op.create_index(
        "ix_champion_daily_stats_season_date",
        "champion_daily_stats",
        ["season_id", "snapshot_date"],
    )

    # Backfill histórico a partir de participants elegíveis (played_at
    # denormalizado). season_id vem da junção com matches.
    op.execute(
        """
        INSERT INTO champion_daily_stats
            (snapshot_date, season_id, champion_id, games, top4, first_place, placement_sum)
        SELECT (mp.played_at AT TIME ZONE 'UTC')::date AS d,
               mm.season_id,
               mp.champion_id,
               count(*),
               count(*) FILTER (WHERE mp.placement <= 4),
               count(*) FILTER (WHERE mp.placement = 1),
               sum(mp.placement)
        FROM match_participants mp
        JOIN matches mm ON mm.id = mp.match_id
        WHERE mp.eligible = true
        GROUP BY d, mm.season_id, mp.champion_id
        ON CONFLICT ON CONSTRAINT pk_champion_daily_stats DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_champion_daily_stats_season_date", table_name="champion_daily_stats")
    op.drop_table("champion_daily_stats")
