"""Tests for arena.workers.sweep.reconcile_tick — the outage catch-up sweep.

Companion to test_scheduler_heartbeat.py: heartbeat_tick opens the window,
reconcile_tick is what drains it. Uses the same FakeRedis + monkeypatch
conventions as test_sweep.py.
"""
from __future__ import annotations

from arena.core.config import settings
from arena.workers import queues as Q
from arena.workers.sweep import reconcile_tick

_FAKE_PUUIDS = ["pu-a", "pu-b"]


class _OnePagePerQueueClient:
    """Returns exactly one id per (puuid, queue) at start=0, nothing after —
    i.e. the window is fully covered in a single page (the common case)."""

    async def list_match_ids(
        self, puuid: str, *, start: int = 0, count: int = 50, queue=None, start_time=None
    ) -> list[str]:
        assert start_time is not None, "reconcile must always pass a start_time window"
        if start != 0:
            return []
        return [f"m-{puuid}-{queue}"]


class _AlwaysFullPageClient:
    """Always returns a full page — simulates a player with more matches in
    the window than reconcile_max_pages_per_player can paginate through."""

    async def list_match_ids(
        self, puuid: str, *, start: int = 0, count: int = 50, queue=None, start_time=None
    ) -> list[str]:
        return [f"m-{puuid}-{queue}-{start}-{i}" for i in range(count)]


def _patch(monkeypatch, client) -> None:
    monkeypatch.setattr("arena.workers.sweep.get_riot_client", lambda: client)

    async def _fake_page(after, limit):
        # Keyset pager: the first page starts at "", the next one resumes after
        # the last puuid handed out and is empty (the fake set is exhausted).
        return list(_FAKE_PUUIDS) if after == "" else []

    monkeypatch.setattr("arena.workers.sweep._tracked_puuids_after", _fake_page)


async def test_idle_when_no_window_pending(fake_redis, monkeypatch):
    _patch(monkeypatch, _OnePagePerQueueClient())

    result = await reconcile_tick({"redis": fake_redis})

    assert result == {"status": "idle"}


async def test_paused_flag_short_circuits_before_touching_the_window(fake_redis, monkeypatch):
    _patch(monkeypatch, _OnePagePerQueueClient())
    await fake_redis.set(Q.RECONCILE_WINDOW_KEY, "1000000")
    await fake_redis.set(Q.worker_enabled_key("reconcile"), "0")

    result = await reconcile_tick({"redis": fake_redis})

    assert result == {"status": "paused"}
    # Window must still be there — paused means untouched, not consumed.
    assert await fake_redis.get(Q.RECONCILE_WINDOW_KEY) == b"1000000"


async def test_happy_path_drains_window_and_enqueues(fake_redis, monkeypatch):
    _patch(monkeypatch, _OnePagePerQueueClient())
    await fake_redis.set(Q.RECONCILE_WINDOW_KEY, "1000000")

    result = await reconcile_tick({"redis": fake_redis})

    assert result["status"] == "ok"
    assert result["since"] == 1000000
    assert result["playersScanned"] == 2
    # 2 puuids x len(live_queue_ids) queues, one unique id each, none pre-seen.
    expected = len(_FAKE_PUUIDS) * len(settings.live_queue_ids)
    assert result["discovered"] == expected
    assert result["enqueued"] == expected
    assert "truncatedPlayers" not in result

    # The window is consumed so a later tick doesn't redo the work.
    assert await fake_redis.get(Q.RECONCILE_WINDOW_KEY) is None

    jobs = [j for j in fake_redis.enqueued if j.queue_name == Q.STANDARD_QUEUE]
    assert len(jobs) == expected


async def test_player_cap_hit_is_reported_not_silently_dropped(fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "reconcile_max_pages_per_player", 1)
    _patch(monkeypatch, _AlwaysFullPageClient())
    await fake_redis.set(Q.RECONCILE_WINDOW_KEY, "1000000")

    result = await reconcile_tick({"redis": fake_redis})

    assert result["status"] == "ok"
    # Both fake puuids hit the pagination cap on every queue -> deduped to 2.
    assert result["truncatedPlayers"] == 2


async def test_skip_locked_when_tick_already_running(fake_redis, monkeypatch):
    _patch(monkeypatch, _OnePagePerQueueClient())
    await fake_redis.set(Q.RECONCILE_WINDOW_KEY, "1000000")
    await fake_redis.set(Q.worker_tick_lock_key("reconcile"), "1")

    result = await reconcile_tick({"redis": fake_redis})

    assert result == {"status": "skip_locked"}
    # Untouched — a concurrent run owns the window.
    assert await fake_redis.get(Q.RECONCILE_WINDOW_KEY) == b"1000000"
