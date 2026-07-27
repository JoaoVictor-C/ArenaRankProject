"""extend monthly partitions for matches_default + integrity_events backward

Revision ID: 0008_extend_partitions_backward
Revises: 0007_cr_snapshots_recent

Migration 0004 extended coverage FORWARD (2026-07 .. 2027-06) on the
assumption the only gap was future months; 0001 shipped only 2026-06. Nothing
ever covered anything before 2026-06, so a match with ``played_at`` in May
2026 or earlier fails the INSERT with ``no partition of relation
"matches_default" found for row``. This surfaced once the sweep pipeline
started re-discovering an old backlog (2026-05-13 .. 2026-05-31 observed
failing in the DLQ). Mirrors 0004's rolling-year approach but backward
(2025-06 .. 2026-06) so a slightly older backlog doesn't need another manual
migration. Idempotent via ``CREATE TABLE IF NOT EXISTS``; targets the direct
Postgres endpoint like all DDL.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008_extend_partitions_backward"
down_revision: str | None = "0007_cr_snapshots_recent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (suffix, from_date, to_date) — monthly bounds, 2025-06 .. 2026-05 inclusive
# (2026-06 is already covered by 0001).
_MONTHS: list[tuple[str, str, str]] = [
    ("2025_06", "2025-06-01", "2025-07-01"),
    ("2025_07", "2025-07-01", "2025-08-01"),
    ("2025_08", "2025-08-01", "2025-09-01"),
    ("2025_09", "2025-09-01", "2025-10-01"),
    ("2025_10", "2025-10-01", "2025-11-01"),
    ("2025_11", "2025-11-01", "2025-12-01"),
    ("2025_12", "2025-12-01", "2026-01-01"),
    ("2026_01", "2026-01-01", "2026-02-01"),
    ("2026_02", "2026-02-01", "2026-03-01"),
    ("2026_03", "2026-03-01", "2026-04-01"),
    ("2026_04", "2026-04-01", "2026-05-01"),
    ("2026_05", "2026-05-01", "2026-06-01"),
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
