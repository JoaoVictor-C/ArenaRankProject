from __future__ import annotations

import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="registry test needs a migrated Postgres (set DATABASE_URL)",
)


@pytest.mark.asyncio
async def test_bulk_ensure_is_idempotent_and_maps_all_puuids():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from arena.core.config import settings
    from arena.ingest.registry import PlayerRegistry
    from tests.ingest.conftest import arena_payload
    from arena.riot.arena import parse_arena_match

    pus = [f"reg-{i}" for i in range(16)]
    parsed = parse_arena_match(arena_payload("reg-m1", pus))
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            id_map_1 = await PlayerRegistry().bulk_ensure(s, [parsed])
            await s.commit()
            assert set(id_map_1) == set(pus)
        async with factory() as s:
            id_map_2 = await PlayerRegistry().bulk_ensure(s, [parsed])  # re-encounter
            await s.commit()
        assert id_map_2 == id_map_1  # same ids, no duplicates
    finally:
        await engine.dispose()
