"""Database layer: declarative base, async session, ORM models.

The physical schema (partitioning, generated columns, Timescale hypertable,
partial/GIN indexes) is owned by the Alembic initial migration; this package
owns the logical ORM contract and the async engine/session plumbing.
"""

from __future__ import annotations

from arena.db.base import Base, metadata
from arena.db.seed import CHAMPIONS, seed, seed_dev_season
from arena.db.session import (
    dispose_engine,
    get_engine,
    get_session,
    get_sessionmaker,
)

__all__ = [
    "Base",
    "metadata",
    "get_engine",
    "get_sessionmaker",
    "get_session",
    "dispose_engine",
    "CHAMPIONS",
    "seed",
    "seed_dev_season",
]
