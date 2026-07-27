"""Tests for arena.workers.sweep.priority_sweep_tick and _priority_seeds.

Uses the async FakeRedis fixture from conftest.py plus monkeypatching to avoid
any DB or Riot API calls.
"""
from __future__ import annotations

from arena.workers import queues as Q
from arena.workers.sweep import _priority_seeds, priority_sweep_tick


# ---------------------------------------------------------------------------
# Shared stub
# ---------------------------------------------------------------------------

_FAKE_MATCH_IDS = ["m1", "m2", "m3"]


class _FakeRiotClient:
    """Stub client whose list_match_ids always returns the same 3 ids."""

    async def list_match_ids(
        self,
        puuid: str,
        *,
        start: int = 0,
        count: int = 10,
        queue: int | None = None,
        start_time: int | None = None,
    ) -> list[str]:
        return list(_FAKE_MATCH_IDS)

    async def get_match(self, riot_match_id: str):
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_priority_sweep_enqueues_to_priority(fake_redis, monkeypatch):
    """Happy-path: priority_sweep_tick enqueues match ids to the priority queue."""
    monkeypatch.setattr("arena.workers.sweep.get_riot_client", lambda: _FakeRiotClient())

    async def _fake_selected():
        return ["pu-sel"]

    async def _fake_top(limit):
        return []

    monkeypatch.setattr("arena.workers.sweep._selected_puuids", _fake_selected)
    monkeypatch.setattr("arena.workers.sweep._top_n_puuids", _fake_top)

    await fake_redis.sadd(Q.TOP_PLAYERS_SET, "pu-top")

    result = await priority_sweep_tick({"redis": fake_redis})

    assert result["status"] == "ok"
    assert result["seeds"] == 2

    jobs = [j for j in fake_redis.enqueued if j.queue_name == Q.PRIORITY_QUEUE]
    assert {j.args[0] for j in jobs} == {"m1", "m2", "m3"}


async def test_priority_seeds_union_dedup(fake_redis, monkeypatch):
    """TOP_PLAYERS_SET ∪ selected is deduplicated with top-first order."""

    async def _fake_selected():
        return ["pu-x", "pu-y"]

    async def _fake_top(limit):
        return []

    monkeypatch.setattr("arena.workers.sweep._selected_puuids", _fake_selected)
    monkeypatch.setattr("arena.workers.sweep._top_n_puuids", _fake_top)

    # pu-x appears in both top set AND selected — should appear only once, first.
    await fake_redis.sadd(Q.TOP_PLAYERS_SET, "pu-x")

    seeds = await _priority_seeds(fake_redis)

    assert seeds == ["pu-x", "pu-y"]


async def test_priority_sweep_paused(fake_redis, monkeypatch):
    """When the enable flag is '0', priority_sweep_tick returns paused."""
    monkeypatch.setattr("arena.workers.sweep.get_riot_client", lambda: _FakeRiotClient())

    async def _fake_selected():
        return []

    monkeypatch.setattr("arena.workers.sweep._selected_puuids", _fake_selected)

    await fake_redis.set(Q.worker_enabled_key("priority_sweep"), "0")

    result = await priority_sweep_tick({"redis": fake_redis})

    assert result == {"status": "paused"}
    assert fake_redis.enqueued == []


async def test_priority_sweep_skip_locked(fake_redis, monkeypatch):
    """If the tick lock is already held, priority_sweep_tick returns skip_locked."""
    monkeypatch.setattr("arena.workers.sweep.get_riot_client", lambda: _FakeRiotClient())

    async def _fake_selected():
        return []

    monkeypatch.setattr("arena.workers.sweep._selected_puuids", _fake_selected)

    await fake_redis.set(Q.worker_tick_lock_key("priority_sweep"), "1")

    result = await priority_sweep_tick({"redis": fake_redis})

    assert result == {"status": "skip_locked"}
    assert fake_redis.enqueued == []
