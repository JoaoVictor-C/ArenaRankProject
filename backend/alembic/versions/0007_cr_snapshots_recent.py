"""cr_snapshots_recent — carve-out plano da hypertable para replicação lógica

Revision ID: 0007_cr_snapshots_recent
Revises: 0006_champion_build_ref

T2.3 do workaround_readpath. Hypertables Timescale não replicam logicamente
para um Postgres vanilla (chunks são tabelas-filhas), então a janela quente de
``cr_snapshots`` (temporada corrente) vive espelhada nesta tabela PLANA, que
entra na publicação ``arena_read``. Escrita: dual-write no RatingService;
retenção: purge de temporadas antigas no cron do SchedulerWorker; leitura:
``StatsService.delta7d_by_player``.

Backfill one-shot: copia da hypertable a janela da temporada corrente
(aproximada como a temporada de ``starts_at`` mais recente — é assim que o
read path resolve "temporada N"). Idempotente via ON CONFLICT DO NOTHING.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_cr_snapshots_recent"
down_revision: str | None = "0006_champion_build_ref"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cr_snapshots_recent",
        sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("season_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("cr", sa.Float(), nullable=False),
        sa.Column("mu", sa.Float(), nullable=False),
        sa.Column("sigma", sa.Float(), nullable=False),
        sa.Column("matches_played", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "player_id", "season_id", "snapshot_at", name="pk_cr_snapshots_recent"
        ),
    )

    # Backfill da janela corrente. Roda no PRIMÁRIO (alembic nunca aponta para
    # a réplica); em DB fresco (sem seasons/snapshots) copia zero linhas.
    op.execute(
        """
        INSERT INTO cr_snapshots_recent
            (player_id, season_id, snapshot_at, cr, mu, sigma, matches_played)
        SELECT s.player_id, s.season_id, s.snapshot_at,
               s.cr, s.mu, s.sigma, s.matches_played
        FROM cr_snapshots s
        WHERE s.season_id = (
            SELECT id FROM seasons ORDER BY starts_at DESC LIMIT 1
        )
        ON CONFLICT ON CONSTRAINT pk_cr_snapshots_recent DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("cr_snapshots_recent")
