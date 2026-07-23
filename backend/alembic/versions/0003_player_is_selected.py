"""add players.is_selected (admin-selected priority ingestion)

Revision ID: 0003_player_is_selected
Revises: 0002_profile_icon
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_player_is_selected"
down_revision: str | None = "0002_profile_icon"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "players",
        sa.Column("is_selected", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_index(
        "ix_players_is_selected_true",
        "players",
        ["is_selected"],
        postgresql_where=sa.text("is_selected = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_players_is_selected_true", table_name="players")
    op.drop_column("players", "is_selected")
