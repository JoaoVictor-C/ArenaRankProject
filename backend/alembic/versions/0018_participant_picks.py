"""match_participants.augments/items — native augment/item pick capture

Revision ID: 0018_participant_picks
Revises: 0017_ingest_seeded_at

Until now the parser never extracted ``playerAugment1..6``/``item0..6`` from
the Riot payload at all — the "Build recomendada" panel and the augment
catalog's tier/champions fields were sourced entirely from a third-party
aggregate (``champion_build_ref``, PROVISIONAL). This migration adds the
columns; ``arena/riot/arena.py`` + ``rating_service.py`` now populate them on
every new match, and ``champion_build_stats`` (a later migration) rolls them
up into our own placement-derived stats, replacing the external fetch.

NULLABLE, no backfill in this migration: existing rows predate the capture.
A separate one-time operator run (``scripts/backfill_augments.py``) re-fetches
each already-ingested match from Riot to fill these in — this migration only
adds the columns new rows land in going forward.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_participant_picks"
down_revision: str | None = "0017_ingest_seeded_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "match_participants",
        sa.Column("augments", postgresql.ARRAY(sa.Integer()), nullable=True),
    )
    op.add_column(
        "match_participants",
        sa.Column("items", postgresql.ARRAY(sa.Integer()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("match_participants", "items")
    op.drop_column("match_participants", "augments")
