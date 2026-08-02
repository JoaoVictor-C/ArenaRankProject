"""drop champion_build_ref — external aggregate retired for native rollup

Revision ID: 0020_drop_champion_build_ref
Revises: 0019_champion_build_stats

``champion_build_ref`` (migration 0006) cached a per-champion Arena aggregate
from a third-party site (``scripts/fetch_build_ref.py``) to back the "Build
recomendada" panel and "Augments em alta" rail — PROVISIONAL from the day it
landed, explicitly "remove when native augment ingestion lands" (see its own
migration/model docstrings).

Native ingestion landed this session: ``match_participants.augments``/
``.items`` (migration 0018) capture real Riot picks, and
``champion_build_stats`` (migration 0019) rolls them up — OUR OWN data,
placement-derived, same posture as every other rollup in this schema. The
read path (``arena/api/routers/champions.py``) now serves entirely off that;
nothing reads ``champion_build_ref`` anymore. ``build_ref_service.py`` keeps
its CDragon name/icon/rarity resolution (still needed — Riot's payload only
gives us numeric augment/item ids, never display info) but the fetch script,
the cron, and this table are gone.

No data migration: this table was always a disposable cache of an external
snapshot, never a source of truth for anything we couldn't re-derive.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_drop_champion_build_ref"
down_revision: str | None = "0019_champion_build_stats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("champion_build_ref")


def downgrade() -> None:
    op.create_table(
        "champion_build_ref",
        sa.Column("champion_id", sa.Integer(), primary_key=True),
        sa.Column("patch", sa.String(), primary_key=True),
        sa.Column("dt", sa.String(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "fetched_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
