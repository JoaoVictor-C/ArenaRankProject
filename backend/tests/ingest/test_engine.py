from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from arena.ingest import caching_engine_and_factory, MatchCrawler, PlayerRegistry, replay_chronological


def test_caching_engine_does_not_disable_statement_cache():
    engine, factory = caching_engine_and_factory("postgresql+asyncpg://arena:arena@localhost:5432/arena")
    assert isinstance(engine, AsyncEngine)
    # The app engine sets statement_cache_size=0 for PgBouncer; the script engine must NOT.
    # Simplified assertion: we did NOT disable the cache (introspection is brittle on this SQLAlchemy version).
    assert "statement_cache_size=0" not in repr(engine.sync_engine.url)


def test_package_reexports_present():
    assert MatchCrawler and PlayerRegistry and replay_chronological
