"""champion-first index on champion_stats (tierlist + per-champion leaderboard)

Revision ID: 0005_champ_first_index
Revises: 0004_extend_partitions

champion_stats' existing indexes are player-first ((player_id, season_id[, winrate])),
so the GLOBAL champion tierlist aggregation (GROUP BY champion_id WHERE season_id)
seq-scanned the table. This champion-first index makes that aggregation
index-friendly and enables a per-champion "best players" leaderboard: rank players
within a (champion_id, season_id) by matches_played DESC.

Plain CREATE INDEX (not CONCURRENTLY): champion_stats is a small, non-partitioned
table, and alembic runs DDL in a transaction. Idempotent via IF NOT EXISTS.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_champ_first_index"
down_revision: str | None = "0004_extend_partitions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_champion_stats_champion_season_games "
        "ON champion_stats (champion_id, season_id, matches_played DESC);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_champion_stats_champion_season_games;")
