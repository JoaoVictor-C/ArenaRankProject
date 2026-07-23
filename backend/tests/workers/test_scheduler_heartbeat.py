"""Tests for arena.workers.scheduler.heartbeat_tick — the outage-gap detector.

Uses the async FakeRedis fixture from tests/workers/conftest.py plus a frozen
clock (monkeypatched ``scheduler.time.time``) so gap math is deterministic.
"""
from __future__ import annotations

from arena.core.config import settings
from arena.workers import queues as Q
from arena.workers import scheduler


def _freeze(monkeypatch, ts: int) -> None:
    monkeypatch.setattr(scheduler.time, "time", lambda: ts)


async def test_first_tick_ever_does_not_open_a_window(fake_redis, monkeypatch):
    """Fresh Redis (no prior heartbeat) is a cold start, not an outage."""
    _freeze(monkeypatch, 1_000_000)

    result = await scheduler.heartbeat_tick({"redis": fake_redis})

    assert result == {"status": "ok", "gap": 0}
    assert await fake_redis.get(Q.SCHEDULER_HEARTBEAT_KEY) == b"1000000"
    assert await fake_redis.get(Q.RECONCILE_WINDOW_KEY) is None


async def test_small_gap_does_not_open_a_window(fake_redis, monkeypatch):
    """A gap under the threshold is normal tick-to-tick jitter, not an outage."""
    await fake_redis.set(Q.SCHEDULER_HEARTBEAT_KEY, "1000000")
    _freeze(monkeypatch, 1_000_000 + settings.reconcile_gap_threshold_seconds - 1)

    result = await scheduler.heartbeat_tick({"redis": fake_redis})

    assert result["status"] == "ok"
    assert result["gap"] == settings.reconcile_gap_threshold_seconds - 1
    assert await fake_redis.get(Q.RECONCILE_WINDOW_KEY) is None


async def test_gap_past_threshold_opens_a_reconcile_window(fake_redis, monkeypatch):
    """A gap over the threshold opens a window starting at the last heartbeat."""
    last = 1_000_000
    await fake_redis.set(Q.SCHEDULER_HEARTBEAT_KEY, str(last))
    now = last + settings.reconcile_gap_threshold_seconds + 1
    _freeze(monkeypatch, now)

    result = await scheduler.heartbeat_tick({"redis": fake_redis})

    assert result["status"] == "ok"
    assert result["since"] == last
    assert result["capped"] is False
    assert result["windowOpened"] is True
    assert await fake_redis.get(Q.RECONCILE_WINDOW_KEY) == str(last).encode()
    # The heartbeat itself always advances, regardless of the gap.
    assert await fake_redis.get(Q.SCHEDULER_HEARTBEAT_KEY) == str(now).encode()


async def test_gap_wider_than_max_is_capped(fake_redis, monkeypatch):
    """An outage longer than reconcile_max_gap_seconds is bounded, not chased in full."""
    monkeypatch.setattr(settings, "reconcile_max_gap_seconds", 100)
    last = 1_000_000
    await fake_redis.set(Q.SCHEDULER_HEARTBEAT_KEY, str(last))
    now = last + 10_000
    _freeze(monkeypatch, now)

    result = await scheduler.heartbeat_tick({"redis": fake_redis})

    assert result["since"] == now - 100
    assert result["capped"] is True


async def test_pending_window_is_never_narrowed(fake_redis, monkeypatch):
    """A second gap detection must not overwrite an already-open, unconsumed window."""
    earlier_since = 500_000
    await fake_redis.set(Q.RECONCILE_WINDOW_KEY, str(earlier_since))
    await fake_redis.set(Q.SCHEDULER_HEARTBEAT_KEY, "1000000")
    _freeze(monkeypatch, 1_000_000 + settings.reconcile_gap_threshold_seconds + 1)

    result = await scheduler.heartbeat_tick({"redis": fake_redis})

    assert result["windowOpened"] is False
    assert await fake_redis.get(Q.RECONCILE_WINDOW_KEY) == str(earlier_since).encode()
