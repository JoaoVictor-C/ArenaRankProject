"""Tests for arena.workers.sweep.recent_activity_sweep_tick.

Uses the async FakeRedis fixture from conftest.py plus monkeypatching to avoid
any DB or Riot API calls — mirrors tests/workers/test_priority_sweep.py's
pattern, since this tick shares its shape (seed puuids -> _fetch_and_enqueue
-> priority queue).
"""
from __future__ import annotations

from arena.core.config import settings
from arena.workers import queues as Q
from arena.workers.sweep import recent_activity_sweep_tick


_FAKE_MATCH_IDS = ["m1", "m2", "m3"]


class _FakeRiotClient:
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


async def test_recent_activity_sweep_enqueues_to_priority(fake_redis, monkeypatch):
    """Happy-path: discovered ids land on the PRIORITY queue, same as rearm —
    this is live-session content, not the slow standard backlog."""
    monkeypatch.setattr("arena.workers.sweep.get_riot_client", lambda: _FakeRiotClient())

    async def _fake_recent(window_seconds, limit):
        return ["pu-recent-1", "pu-recent-2"]

    monkeypatch.setattr("arena.workers.sweep._recently_active_puuids", _fake_recent)

    result = await recent_activity_sweep_tick({"redis": fake_redis})

    assert result["status"] == "ok"
    assert result["puuids"] == 2
    jobs = [j for j in fake_redis.enqueued if j.queue_name == Q.PRIORITY_QUEUE]
    assert {j.args[0] for j in jobs} == {"m1", "m2", "m3"}


async def test_recent_activity_sweep_no_active_players_is_a_cheap_noop(fake_redis, monkeypatch):
    monkeypatch.setattr("arena.workers.sweep.get_riot_client", lambda: _FakeRiotClient())

    async def _fake_recent(window_seconds, limit):
        return []

    monkeypatch.setattr("arena.workers.sweep._recently_active_puuids", _fake_recent)

    result = await recent_activity_sweep_tick({"redis": fake_redis})

    assert result == {"status": "ok", "puuids": 0, "discovered": 0, "enqueued": 0}
    assert fake_redis.enqueued == []


async def test_recent_activity_sweep_paused(fake_redis, monkeypatch):
    monkeypatch.setattr("arena.workers.sweep.get_riot_client", lambda: _FakeRiotClient())

    async def _fake_recent(window_seconds, limit):
        return ["pu-recent-1"]

    monkeypatch.setattr("arena.workers.sweep._recently_active_puuids", _fake_recent)
    await fake_redis.set(Q.worker_enabled_key("recent_activity"), "0")

    result = await recent_activity_sweep_tick({"redis": fake_redis})

    assert result == {"status": "paused"}
    assert fake_redis.enqueued == []


async def test_recent_activity_sweep_skip_locked(fake_redis, monkeypatch):
    monkeypatch.setattr("arena.workers.sweep.get_riot_client", lambda: _FakeRiotClient())

    async def _fake_recent(window_seconds, limit):
        return ["pu-recent-1"]

    monkeypatch.setattr("arena.workers.sweep._recently_active_puuids", _fake_recent)
    await fake_redis.set(Q.worker_tick_lock_key("recent_activity"), "1")

    result = await recent_activity_sweep_tick({"redis": fake_redis})

    assert result == {"status": "skip_locked"}
    assert fake_redis.enqueued == []


async def test_recent_activity_sweep_disabled_via_settings(fake_redis, monkeypatch):
    """The settings-level kill switch (not the Redis worker-enable flag) —
    distinct code path, must also short-circuit before touching Riot/DB."""
    monkeypatch.setattr(settings, "recent_activity_enabled", False)

    called = False

    async def _fake_recent(window_seconds, limit):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr("arena.workers.sweep._recently_active_puuids", _fake_recent)

    result = await recent_activity_sweep_tick({"redis": fake_redis})

    assert result == {"status": "disabled"}
    assert called is False
    assert fake_redis.enqueued == []
