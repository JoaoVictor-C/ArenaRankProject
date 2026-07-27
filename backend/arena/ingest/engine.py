"""A second, offline-tuned SQLAlchemy engine — separate from the app's.

``arena.db.session`` builds the engine the API/workers use, which disables
asyncpg statement caching (``statement_cache_size=0``) because it runs
against PgBouncer in transaction-pooling mode, where a cached prepared
statement can silently bind to the wrong physical connection on the next
checkout. Backfill scripts connect straight to Postgres (no PgBouncer in the
loop), so that constraint doesn't apply — this module exists purely so those
scripts get a faster engine instead of inheriting the app's more conservative
one.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine,
)


def caching_engine_and_factory(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Dedicated engine for offline scripts that connect DIRECTLY to Postgres.
    Unlike the app engine (statement_cache_size=0 for PgBouncer tx-mode), this
    keeps asyncpg statement caching ON — ~34x faster on the replay hot path.
    synchronous_commit=off is applied at the asyncpg server-settings level so
    every connection from the pool gets relaxed durability without needing a
    per-session SET command."""
    engine = create_async_engine(
        database_url, pool_pre_ping=True,
        connect_args={"server_settings": {"synchronous_commit": "off"}},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    return engine, factory
