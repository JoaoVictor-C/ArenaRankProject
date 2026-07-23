"""Tests for arena.workers.bulk_processor.

Uses the async FakeRedis fixture from conftest.py and monkeypatches the real
process_match with an async stub so no DB / Riot / rating service is touched.
"""
from __future__ import annotations

from arq.worker import Retry

from arena.core.config import settings
from arena.workers import queues as Q
from arena.workers.bulk_processor import (
    _drain_pending,
    _process_one,
    bulk_process_tick,
)


def _stub_process_match(status: str = "processed"):
    async def _stub(ctx, mid):
        return {"matchId": mid, "status": status}

    return _stub


async def test_drain_priority_first(fake_redis):
    for i in range(5):
        await fake_redis.lpush(Q.SWEEP_PENDING_PRIORITY, f"p{i}")
    for i in range(10):
        await fake_redis.lpush(Q.SWEEP_PENDING_STANDARD, f"s{i}")

    mids = await _drain_pending(fake_redis, 8)

    assert len(mids) == 8
    # First 5 are the priority ids (FIFO), then 3 standard.
    assert mids[:5] == ["p0", "p1", "p2", "p3", "p4"]
    assert mids[5:] == ["s0", "s1", "s2"]


async def test_process_one_success_clears_attempts(fake_redis, monkeypatch):
    monkeypatch.setattr(
        "arena.workers.bulk_processor.process_match", _stub_process_match("processed")
    )
    status = await _process_one(fake_redis, "m1")
    assert status == "processed"
    # Attempts entry removed → hincrby re-creates it at 0.
    assert await fake_redis.hincrby(Q.SWEEP_ATTEMPTS_KEY, "m1", 0) == 0


async def test_process_one_retry_requeues(fake_redis, monkeypatch):
    async def _raises(ctx, mid):
        raise Retry(defer=1)

    monkeypatch.setattr("arena.workers.bulk_processor.process_match", _raises)
    status = await _process_one(fake_redis, "m1")
    assert status == "requeued"
    assert await fake_redis.rpop(Q.SWEEP_PENDING_STANDARD) == b"m1"


async def test_process_one_unexpected_error_requeues(fake_redis, monkeypatch):
    """An unexpected (non-Retry) error must requeue the mid, never drop it."""

    async def _boom(ctx, mid):
        raise RuntimeError("unexpected")

    monkeypatch.setattr("arena.workers.bulk_processor.process_match", _boom)
    status = await _process_one(fake_redis, "m1")
    assert status == "error_requeued"
    assert await fake_redis.rpop(Q.SWEEP_PENDING_STANDARD) == b"m1"


async def test_bulk_tick_processes_batch(fake_redis, monkeypatch):
    monkeypatch.setattr(
        "arena.workers.bulk_processor.process_match", _stub_process_match("processed")
    )
    for i in range(3):
        await fake_redis.lpush(Q.SWEEP_PENDING_PRIORITY, f"m{i}")

    result = await bulk_process_tick({"redis": fake_redis})

    assert result["status"] == "ok"
    assert result["total"] == 3
    assert result.get("processed") == 3


async def test_bulk_tick_drains_backlog_across_multiple_batches(fake_redis, monkeypatch):
    """A backlog bigger than one bulk_batch_size must drain within a single
    tick invocation instead of trickling in over multiple scheduled ticks —
    the fix for the fixed batch-per-tick throughput ceiling."""
    monkeypatch.setattr(
        "arena.workers.bulk_processor.process_match", _stub_process_match("processed")
    )
    monkeypatch.setattr(settings, "bulk_batch_size", 5)
    for i in range(12):
        await fake_redis.lpush(Q.SWEEP_PENDING_STANDARD, f"m{i}")

    result = await bulk_process_tick({"redis": fake_redis})

    assert result["status"] == "ok"
    assert result["total"] == 12
    assert result["batches"] == 3  # 5 + 5 + 2
    assert result["processed"] == 12
    assert await fake_redis.rpop(Q.SWEEP_PENDING_STANDARD) is None


async def test_bulk_tick_stops_at_wall_clock_budget(fake_redis, monkeypatch):
    """A spent time budget must stop draining even with backlog remaining —
    the safety bound that keeps a tick from running past the next one."""
    monkeypatch.setattr(
        "arena.workers.bulk_processor.process_match", _stub_process_match("processed")
    )
    monkeypatch.setattr(settings, "bulk_max_seconds_per_tick", -1)
    await fake_redis.lpush(Q.SWEEP_PENDING_STANDARD, "m0")

    result = await bulk_process_tick({"redis": fake_redis})

    assert result == {"status": "ok", "processed": 0}
    # Untouched — the budget ran out before the first batch was even drained.
    assert await fake_redis.rpop(Q.SWEEP_PENDING_STANDARD) == b"m0"


async def test_bulk_skip_locked(fake_redis):
    await fake_redis.set(Q.worker_tick_lock_key("bulk_processor"), "1")
    result = await bulk_process_tick({"redis": fake_redis})
    assert result == {"status": "skip_locked"}


async def test_bulk_paused(fake_redis):
    await fake_redis.set(Q.worker_enabled_key("bulk_processor"), "0")
    result = await bulk_process_tick({"redis": fake_redis})
    assert result == {"status": "paused"}
