"""Alembic environment — async (asyncpg) configuration.

DSN resolution mirrors :mod:`arena.db.session`: prefer the shared
``arena.core`` settings (``DATABASE_URL``), degrade to a local pydantic
reader so migrations can be generated/inspected even mid-scaffold. For
TimescaleDB policy DDL and other pooler-incompatible statements, run with
``DATABASE_URL`` pointed at the direct (non-PgBouncer) endpoint.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import the metadata so autogenerate has a target.
from arena.db.base import Base
from arena.db import models  # noqa: F401  (registers all tables on Base.metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Logical tables we own in the ORM. Everything else physically present in the
# database — declarative partition children (matches_*, match_participants_pNN,
# integrity_events_*), Timescale hypertable chunks (_timescaledb_internal.*),
# and the alembic bookkeeping table — is owned by raw DDL and MUST be invisible
# to autogenerate/`alembic check`, otherwise every partition child reads as a
# spurious "removed table". This keeps `alembic check` meaningful for the
# logical schema while the physical schema stays hand-managed.
_OWNED_TABLES = set(target_metadata.tables.keys())


def _include_name(name: str | None, type_: str, parent_names: dict) -> bool:
    # Ignore non-public schemas entirely (Timescale internals live elsewhere).
    if type_ == "schema":
        return name is None or name == "public"
    if type_ == "table":
        return name in _OWNED_TABLES
    # Indexes/constraints: keep only those on tables we own.
    parent_table = parent_names.get("table_name")
    if parent_table is not None:
        return parent_table in _OWNED_TABLES
    return True


def _include_object(obj, name, type_, reflected, compare_to) -> bool:  # noqa: ANN001
    if type_ == "table":
        return name in _OWNED_TABLES
    # For indexes/uniques, drop anything attached to a non-owned (partition
    # child) table.
    parent = getattr(obj, "table", None)
    if parent is not None and parent.name not in _OWNED_TABLES:
        return False
    return True


def _resolve_database_url() -> str:
    try:
        from arena.core.config import settings  # type: ignore[import-not-found]

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


def _set_url() -> str:
    url = _resolve_database_url()
    config.set_main_option("sqlalchemy.url", url)
    return url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DBAPI connection."""
    url = _set_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_name=_include_name,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # Partitioned/generated/hypertable objects are owned by raw DDL; keep
        # autogenerate from trying to "correct" them.
        include_schemas=False,
        include_name=_include_name,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations within its connection."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _set_url()

    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        # asyncpg + (optional) PgBouncer tx mode safety.
        connect_args={"statement_cache_size": 0},
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
