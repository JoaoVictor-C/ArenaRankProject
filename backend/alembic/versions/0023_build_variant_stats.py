"""champion_build_variant_stats — itemizações por augment prismático materializadas

Revision ID: 0023_build_variant_stats
Revises: 0022_champion_versus_stats

Backs GET /champions/{id}/builds (o painel "BUILDS DE {campeão} por tier").
Agrupa pelo augment PRISMÁTICO (a escolha que de fato define o rumo da build
no Arena — ver docstring do modelo em arena/db/models.py) em vez de tentar
clusterizar itemizações inteiras, o que evitaria tanto uma explosão
combinatória de variantes quanto o problema de NOMEAR cada cluster sem
inventar rótulo (o augment já tem nome real via CDragon).

Sem backfill nesta migração — o cron (``champion_build_variant_maintenance``)
e uma população manual inicial preenchem depois. A tabela começa vazia.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_build_variant_stats"
down_revision: str | None = "0022_champion_versus_stats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "champion_build_variant_stats",
        sa.Column("season_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("champion_id", sa.Integer(), nullable=False),
        sa.Column("augment_id", sa.Integer(), nullable=False),  # the PRISMATIC augment
        sa.Column("games", sa.Integer(), nullable=False),
        sa.Column("top1", sa.Integer(), nullable=False),  # placement == 1
        sa.Column("top4", sa.Integer(), nullable=False),  # placement <= 4
        sa.Column("placement_sum", sa.Integer(), nullable=False),
        sa.Column("items", postgresql.ARRAY(sa.Integer()), nullable=False),  # ranked, capped
        sa.PrimaryKeyConstraint(
            "season_id", "champion_id", "augment_id", name="pk_champion_build_variant_stats"
        ),
    )
    op.create_index(
        "ix_champion_build_variant_stats_champion_games",
        "champion_build_variant_stats",
        ["season_id", "champion_id", "games"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_champion_build_variant_stats_champion_games", table_name="champion_build_variant_stats"
    )
    op.drop_table("champion_build_variant_stats")
