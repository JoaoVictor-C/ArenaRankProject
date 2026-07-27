"""Regression test for the sweep's rotation cursor.

The sweep used to page tracked players with ``OFFSET :cursor``. Players are
registered continuously (every processed lobby can mint up to 16 rows) and a
puuid sorts to a random position, so each insert landing BEHIND the live cursor
shifted the remaining pages by one and silently skipped a tracked player for the
rest of the rotation. This pins the keyset paging that replaced it: no tracked
player is dropped from a rotation just because the table grew mid-rotation.
"""

from __future__ import annotations

from arena.core.config import settings
from arena.workers import queues as Q
from arena.workers.sweep import sweep_tick


class _NoopClient:
    async def list_match_ids(self, puuid: str, **kw: object) -> list[str]:
        return []


async def _rotate(fake_redis, monkeypatch, roster: list[str], *, insert_each_tick):
    """Run full ticks until the cursor wraps; return the puuids actually swept."""
    monkeypatch.setattr("arena.workers.sweep.get_riot_client", lambda: _NoopClient())
    monkeypatch.setattr(settings, "sweep_batch_size", 2)
    monkeypatch.setattr(settings, "deep_sample_per_tick", 0)

    seen: list[str] = []

    async def _page(after: str, limit: int) -> list[str]:
        # Stands in for "SELECT puuid ... WHERE puuid > :after ORDER BY puuid".
        page = [p for p in sorted(roster) if p > after][:limit]
        seen.extend(page)
        return page

    monkeypatch.setattr("arena.workers.sweep._tracked_puuids_after", _page)

    for _ in range(20):
        await fake_redis.delete(Q.worker_tick_lock_key("sweep"))
        await sweep_tick({"redis": fake_redis})
        insert_each_tick(roster)
        if await fake_redis.get(Q.SWEEP_CURSOR_PUUID_KEY) == b"":
            break
    return seen


async def test_rotation_covers_every_player_despite_concurrent_inserts(fake_redis, monkeypatch):
    original = [f"pu-{i:02d}" for i in range(6)]
    roster = list(original)
    counter = {"n": 0}

    def _insert(current: list[str]) -> None:
        # Each tick registers a new player that sorts BEFORE the live cursor —
        # exactly the case that used to shift OFFSET pages and drop a player.
        counter["n"] += 1
        current.append(f"pu-00-new-{counter['n']}")

    seen = await _rotate(fake_redis, monkeypatch, roster, insert_each_tick=_insert)

    # Every player present at the start of the rotation was visited.
    assert set(original) <= set(seen)
    # And nobody was visited twice within the rotation.
    assert len(seen) == len(set(seen))


async def test_cursor_advances_to_last_puuid_then_wraps(fake_redis, monkeypatch):
    roster = [f"pu-{i:02d}" for i in range(3)]

    monkeypatch.setattr("arena.workers.sweep.get_riot_client", lambda: _NoopClient())
    monkeypatch.setattr(settings, "sweep_batch_size", 2)
    monkeypatch.setattr(settings, "deep_sample_per_tick", 0)

    async def _page(after: str, limit: int) -> list[str]:
        return [p for p in sorted(roster) if p > after][:limit]

    monkeypatch.setattr("arena.workers.sweep._tracked_puuids_after", _page)

    # Full page -> cursor parks on its last puuid.
    await sweep_tick({"redis": fake_redis})
    assert await fake_redis.get(Q.SWEEP_CURSOR_PUUID_KEY) == b"pu-01"

    # Short page -> rotation exhausted, cursor wraps to the start.
    await fake_redis.delete(Q.worker_tick_lock_key("sweep"))
    await sweep_tick({"redis": fake_redis})
    assert await fake_redis.get(Q.SWEEP_CURSOR_PUUID_KEY) == b""
