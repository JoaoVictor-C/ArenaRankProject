"""admin_audit_events — immutable trail of privileged actions

Revision ID: 0010_admin_audit_events
Revises: 0009_admin_operators

Backs arena/api/rbac.py::record_audit, called best-effort from every admin
mutation route (season/DLQ/integrity/worker/player/tournament/operator ops).
Written in its own short transaction, independent of whatever DB/Redis
transaction the mutation itself used.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_admin_audit_events"
down_revision: str | None = "0009_admin_operators"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "occurred_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor", sa.String(length=254), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target", sa.String(length=200), nullable=True),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("result", sa.String(length=16), server_default=sa.text("'ok'"), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_admin_audit_events_occurred_at", "admin_audit_events", ["occurred_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_admin_audit_events_occurred_at", table_name="admin_audit_events")
    op.drop_table("admin_audit_events")
