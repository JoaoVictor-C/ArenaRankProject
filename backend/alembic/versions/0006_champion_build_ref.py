"""champion_build_ref — provisional reference build cache

Revision ID: 0006_champion_build_ref
Revises: 0005_champ_first_index

PROVISIONAL. Caches a per-champion Arena aggregate (augment/item/teammate
placement stats) as one JSONB snapshot per (champion_id, patch) to power a
stop-gap "build recomendada" surface until native augment ingestion lands. The
whole feature is self-contained (this table, models.ChampionBuildRef,
scripts/fetch_build_ref.py) so it drops in one pass.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_champion_build_ref"
down_revision: str | None = "0005_champ_first_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "champion_build_ref",
        sa.Column("champion_id", sa.Integer(), nullable=False),
        sa.Column("patch", sa.String(), nullable=False),
        sa.Column("dt", sa.String(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "fetched_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("champion_id", "patch"),
    )


def downgrade() -> None:
    op.drop_table("champion_build_ref")
