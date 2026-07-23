"""Async engine + session factory (asyncpg).

The DSN comes from :mod:`arena.core.config` (pydantic-settings,
``DATABASE_URL``). To keep this module importable even while sibling
``arena.core`` submodules are still being scaffolded, we fall back to a
minimal local settings reader if the shared config package is not yet
importable. Production always resolves to the shared ``settings``.

Two logical pools exist in the deployment (Trinity finding #9):

* web requests  -> PgBouncer **transaction** mode (6432)
* workers       -> PgBouncer **session** mode (6433)

That split is configured at the PgBouncer/DSN layer, not here. When pointing
at a transaction-mode pooler set ``statement_cache_size=0`` on the asyncpg
side (done below) — prepared-statement caching is incompatible with tx
pooling.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _resolve_database_url() -> str:
    """Best-effort DSN resolution.

    Prefer the shared ``arena.core`` settings; degrade gracefully to a local
    pydantic-settings reader so this module never hard-fails on import order.
    """
    try:
        from arena.core.config import settings

        return settings.database_url
    except Exception:  # pragma: no cover - import-order fallback only
        from pydantic import Field
        from pydantic_settings import BaseSettings, SettingsConfigDict

        class _DbSettings(BaseSettings):
            model_config = SettingsConfigDict(env_file=".env", extra="ignore")
            database_url: str = Field(
                default="postgresql+asyncpg://arena:arena@localhost:5432/arena",
            )

        return _DbSettings().database_url


def _resolve_pool_config() -> tuple[int, int]:
    """(pool_size, max_overflow) from shared settings; safe defaults on failure."""
    try:
        from arena.core.config import settings

        return int(settings.db_pool_size), int(settings.db_max_overflow)
    except Exception:  # pragma: no cover - import-order fallback only
        return 20, 10


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Process-wide async engine (lazy, cached).

    ``pool_pre_ping`` guards against pooler-recycled connections;
    ``statement_cache_size=0`` keeps us compatible with PgBouncer tx mode. The
    pool is sized (``db_pool_size`` + ``db_max_overflow``) to cover a worker's
    concurrent ``max_jobs`` so simultaneous matches don't queue on connections.
    """
    pool_size, max_overflow = _resolve_pool_config()
    return create_async_engine(
        _resolve_database_url(),
        echo=False,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        connect_args={"statement_cache_size": 0},
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Cached session factory bound to the process engine."""
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a request-scoped session, always closed."""
    factory = get_sessionmaker()
    async with factory() as session:
        yield session


async def dispose_engine() -> None:
    """Dispose the pooled engine (call on app shutdown)."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
