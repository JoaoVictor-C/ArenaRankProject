"""Tests for arena.workers.sweep.sweep_tick.

Uses the async FakeRedis fixture from conftest.py plus monkeypatching to avoid
any DB or Riot API calls.

The real _dedup_new and _update_pressure_mode from ingestion.py are exercised
against FakeRedis so their Redis ops are covered too.
"""
from __future__ import annotations

from arena.workers import queues as Q
from arena.workers.sweep import sweep_tick


# ---------------------------------------------------------------------------
# Shared patch helpers
# ---------------------------------------------------------------------------

_FAKE_PUUIDS = ["pu-a", "pu-b"]
_FAKE_MATCH_IDS = ["m1", "m2", "m3"]


class _FakeRiotClient:
    """Stub client whose list_match_ids always returns the same 3 ids."""

    async def list_match_ids(self, puuid: str, *, start: int = 0, count: int = 10) -> list[str]:
        return list(_FAKE_MATCH_IDS)

    async def get_match(self, riot_match_id: str):
        return None


def _patch_sweep(monkeypatch) -> None:
    """Apply the three common monkeypatches for sweep tests."""
    monkeypatch.setattr(
        "arena.workers.sweep.get_riot_client",
        lambda: _FakeRiotClient(),
    )
    async def _fake_page(offset, limit):
        return list(_FAKE_PUUIDS)

    monkeypatch.setattr("arena.workers.sweep._tracked_puuids_page", _fake_page)
    # _update_pressure_mode uses zcard + exists; with an empty FakeRedis
    # depth=0 < PRESSURE_HIGH_WATERMARK so it returns True naturally.
    # No patch needed, but we use the real function to validate FakeRedis ops.


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_sweep_enqueues_to_standard(fake_redis, monkeypatch):
    """Happy-path: sweep_tick enqueues deduplicated match ids to the standard queue."""
    _patch_sweep(monkeypatch)

    result = await sweep_tick({"redis": fake_redis})

    assert result["status"] == "ok"

    # Both puuids return the same 3 ids -> discovered=6, deduped to 3 fresh.
    assert result["discovered"] == 6
    assert result["enqueued"] == 3

    # Drain the standard queue and verify all 3 ids are there (as bytes).
    items = await fake_redis.rpop(Q.SWEEP_PENDING_STANDARD, 10)
    assert items is not None
    assert set(items) == {b"m1", b"m2", b"m3"}

    # Cursor wraps to 0 because len(puuids)=2 < sweep_batch_size=100.
    cursor_raw = await fake_redis.get(Q.SWEEP_CURSOR_KEY)
    assert cursor_raw == b"0"


async def test_sweep_skip_when_locked(fake_redis, monkeypatch):
    """If the tick lock is already held, sweep_tick returns skip_locked immediately."""
    _patch_sweep(monkeypatch)

    # Pre-acquire the lock so sweep_tick sees it as taken.
    await fake_redis.set(Q.worker_tick_lock_key("sweep"), "1")

    result = await sweep_tick({"redis": fake_redis})

    assert result == {"status": "skip_locked"}

    # Queue must still be empty — nothing was enqueued.
    assert await fake_redis.rpop(Q.SWEEP_PENDING_STANDARD) is None


async def test_sweep_paused(fake_redis, monkeypatch):
    """When the enable flag is '0', sweep_tick returns paused without touching the queue."""
    _patch_sweep(monkeypatch)

    await fake_redis.set(Q.worker_enabled_key("sweep"), "0")

    result = await sweep_tick({"redis": fake_redis})

    assert result == {"status": "paused"}
    assert await fake_redis.rpop(Q.SWEEP_PENDING_STANDARD) is None


async def test_sweep_dedup(fake_redis, monkeypatch):
    """Running sweep_tick twice does not re-enqueue ids already in the seen-set."""
    _patch_sweep(monkeypatch)

    # First tick — enqueues 3 fresh ids.
    result1 = await sweep_tick({"redis": fake_redis})
    assert result1["status"] == "ok"
    assert result1["enqueued"] == 3

    # Release the per-tick lock so the second tick can proceed.
    await fake_redis.delete(Q.worker_tick_lock_key("sweep"))

    # Second tick — same ids are now in the seen-set; nothing new to enqueue.
    result2 = await sweep_tick({"redis": fake_redis})
    assert result2["status"] == "ok"
    assert result2["enqueued"] == 0

    # Queue should contain exactly the 3 ids from the first tick only.
    items = await fake_redis.rpop(Q.SWEEP_PENDING_STANDARD, 20)
    assert items is not None
    assert set(items) == {b"m1", b"m2", b"m3"}
