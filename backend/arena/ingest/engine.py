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
