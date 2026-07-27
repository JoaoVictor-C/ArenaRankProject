"""admin_operators — per-operator RBAC identities

Revision ID: 0009_admin_operators
Revises: 0008_extend_partitions_backward

New standalone table backing arena/api/rbac.py's per-route scope checks. The
env ADMIN_API_KEY (arena/core/config.py) stays a separate, permanent "Owner"
bootstrap credential and is never stored here — this table only holds
additional named operators (Admin/Moderador/Analista/Suporte, or extra
Owners). Keys are high-entropy random tokens (never user-chosen), so a fast
SHA-256 hash + unique-index lookup is the right tradeoff (no bcrypt/scrypt
needed, unlike a user password).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_admin_operators"
down_revision: str | None = "0008_extend_partitions_backward"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_ENUM = postgresql.ENUM(
    "owner", "admin", "moderator", "analyst", "support", name="operator_role"
)


def upgrade() -> None:
    _ROLE_ENUM.create(op.get_bind(), checkfirst=True)
    # create_type=False: the type was just created explicitly above (so the
    # checkfirst=True on the *type* itself is meaningful) — without this,
    # create_table's own column-type visitor tries to CREATE TYPE a second
    # time and fails with "type already exists".
    _role_column_type = postgresql.ENUM(
        "owner", "admin", "moderator", "analyst", "support",
        name="operator_role", create_type=False,
    )
    op.create_table(
        "admin_operators",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("role", _role_column_type, nullable=False),
        sa.Column("api_key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=12), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_seen_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("email", name="uq_admin_operators_email"),
        sa.UniqueConstraint("api_key_hash", name="uq_admin_operators_api_key_hash"),
    )
    op.execute(
        "CREATE INDEX ix_admin_operators_active ON admin_operators (revoked_at) "
        "WHERE revoked_at IS NULL;"
    )


def downgrade() -> None:
    op.drop_index("ix_admin_operators_active", table_name="admin_operators")
    op.drop_table("admin_operators")
    _ROLE_ENUM.drop(op.get_bind(), checkfirst=True)
