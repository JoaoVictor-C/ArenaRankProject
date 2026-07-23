"""extend monthly partitions for matches_default + integrity_events

Revision ID: 0004_extend_partitions
Revises: 0003_player_is_selected

Migration 0001 shipped only the 2026-06 monthly sub-partition for
``matches_default`` (and ``integrity_events``), on the assumption the scheduler
would provision future months. It does not yet, so any row dated 2026-07+ fails
with ``no partition of relation ... found for row``. This adds a rolling year of
monthly partitions (2026-07 .. 2027-06) so writes succeed. Idempotent via
``CREATE TABLE IF NOT EXISTS``; targets the direct Postgres endpoint like all DDL.

Follow-up: wire a scheduler cron to provision the next month ahead of time so this
never needs a manual migration again.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_extend_partitions"
down_revision: str | None = "0003_player_is_selected"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (suffix, from_date, to_date) — monthly bounds, 2026-07 .. 2027-06 inclusive.
_MONTHS: list[tuple[str, str, str]] = [
    ("2026_07", "2026-07-01", "2026-08-01"),
    ("2026_08", "2026-08-01", "2026-09-01"),
    ("2026_09", "2026-09-01", "2026-10-01"),
    ("2026_10", "2026-10-01", "2026-11-01"),
    ("2026_11", "2026-11-01", "2026-12-01"),
    ("2026_12", "2026-12-01", "2027-01-01"),
    ("2027_01", "2027-01-01", "2027-02-01"),
    ("2027_02", "2027-02-01", "2027-03-01"),
    ("2027_03", "2027-03-01", "2027-04-01"),
    ("2027_04", "2027-04-01", "2027-05-01"),
    ("2027_05", "2027-05-01", "2027-06-01"),
    ("2027_06", "2027-06-01", "2027-07-01"),
]


def upgrade() -> None:
    for suffix, lo, hi in _MONTHS:
        op.execute(
            f"CREATE TABLE IF NOT EXISTS matches_default_{suffix} "
            f"PARTITION OF matches_default FOR VALUES FROM ('{lo}') TO ('{hi}');"
        )
        op.execute(
            f"CREATE TABLE IF NOT EXISTS integrity_events_{suffix} "
            f"PARTITION OF integrity_events FOR VALUES FROM ('{lo}') TO ('{hi}');"
        )


def downgrade() -> None:
    for suffix, _lo, _hi in reversed(_MONTHS):
        op.execute(f"DROP TABLE IF EXISTS matches_default_{suffix};")
        op.execute(f"DROP TABLE IF EXISTS integrity_events_{suffix};")
