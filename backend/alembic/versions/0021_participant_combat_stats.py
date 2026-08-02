"""match_participants combat telemetry — native K/D/A/damage/gold/level capture

Revision ID: 0021_participant_combat_stats
Revises: 0020_drop_champion_build_ref

Until now the parser never extracted combat stats (kills/deaths/assists/damage/
gold/level, plus a curated "cheap to grab during the same re-fetch" set —
damage taken, healing, self-mitigation, largest multi-kill, killing sprees, time
spent dead) from the Riot payload at all — the frontend already renders these
per match (`/perfil/:riotId` expanded rows, `/partida/:id`) but every match shows
"aguardando ingestão" placeholders. This migration adds the columns;
``arena/riot/arena.py`` + ``rating_service.py`` now populate them on every new
match. No rollup — these are per-match display fields only, unlike
augments/items -> champion_build_stats.

NULLABLE, no backfill in this migration: existing rows predate the capture.
A separate one-time operator run (``scripts/backfill_participant_telemetry.py``)
re-fetches each already-ingested match from Riot to fill these in — this
migration only adds the columns new rows land in going forward.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_participant_combat_stats"
down_revision: str | None = "0020_drop_champion_build_ref"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    "kills",
    "deaths",
    "assists",
    "damage_to_champions",
    "gold_earned",
    "champion_level",
    "damage_taken",
    "total_heal",
    "damage_self_mitigated",
    "largest_multi_kill",
    "killing_sprees",
    "time_spent_dead",
)


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column(
            "match_participants",
            sa.Column(name, sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    for name in reversed(_COLUMNS):
        op.drop_column("match_participants", name)
