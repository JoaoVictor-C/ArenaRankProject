"""add players.profile_icon_id (Data Dragon summoner profile icon)

Revision ID: 0002_profile_icon
Revises: 0001_initial
Create Date: 2026-06-14

Captures the summoner profile icon id from the Riot match-v5 participant
``profileIcon`` field so the frontend can render the OFFICIAL Data Dragon
(ddragon) summoner-icon CDN URL instead of a gradient placeholder. Nullable +
no default: rows registered before this column existed stay NULL until their
next match is ingested. Plain ``ALTER TABLE ... ADD COLUMN`` — ``players`` is
not partitioned, so this is a cheap metadata-only change.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_profile_icon"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "players",
        sa.Column("profile_icon_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("players", "profile_icon_id")
