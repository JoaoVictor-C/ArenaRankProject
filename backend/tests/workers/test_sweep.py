"""Tests for arena.workers.sweep.sweep_tick.

Uses the async FakeRedis fixture from conftest.py plus monkeypatching to avoid
any DB or Riot API calls.

The real _dedup_new and _update_pressure_mode from ingestion.py are exercised
against FakeRedis so their Redis ops are covered too.
"""
from __future__ import annotations

from arena.core.config import settings
from arena.workers import queues as Q
from arena.workers.sweep import sweep_tick


# ---------------------------------------------------------------------------
# Shared patch helpers
# ---------------------------------------------------------------------------

_FAKE_PUUIDS = ["pu-a", "pu-b"]
_FAKE_MATCH_IDS = ["m1", "m2", "m3"]


class _FakeRiotClient:
    """Stub client whose list_match_ids always returns the same 3 ids.

    Signature must mirror the real ``RiotClient`` protocol (``queue`` /
    ``start_time``): the sweep passes both, and a stub missing them raises
    TypeError into the per-call ``except`` — which silently turned every
    assertion below into "0 discovered, 0 enqueued" and passed anyway.
    """

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


def _patch_sweep(monkeypatch) -> None:
    """Apply the three common monkeypatches for sweep tests."""
    monkeypatch.setattr(
        "arena.workers.sweep.get_riot_client",
        lambda: _FakeRiotClient(),
    )
    async def _fake_page(after, limit):
        return list(_FAKE_PUUIDS)

    monkeypatch.setattr("arena.workers.sweep._tracked_puuids_after", _fake_page)
    # _update_pressure_mode uses zcard + exists; with an empty FakeRedis
    # depth=0 < PRESSURE_HIGH_WATERMARK so it returns True naturally.
    # No patch needed, but we use the real function to validate FakeRedis ops.


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _standard_job_ids(fake_redis) -> set[str]:
    return {j.args[0] for j in fake_redis.enqueued if j.queue_name == Q.STANDARD_QUEUE}


async def test_sweep_enqueues_to_standard(fake_redis, monkeypatch):
    """Happy-path: sweep_tick enqueues deduplicated match ids to the standard queue."""
    _patch_sweep(monkeypatch)

    result = await sweep_tick({"redis": fake_redis})

    assert result["status"] == "ok"

    # One ids call per (puuid, live queue), each returning the same 3 ids ->
    # 2 x len(live_queue_ids) x 3 discovered, all collapsing to 3 fresh claims.
    assert result["discovered"] == len(_FAKE_PUUIDS) * len(settings.live_queue_ids) * 3
    assert result["enqueued"] == 3

    assert _standard_job_ids(fake_redis) == {"m1", "m2", "m3"}

    # Keyset cursor wraps to "" (start of rotation) because the page came back
    # short: len(puuids)=2 < sweep_batch_size=100.
    cursor_raw = await fake_redis.get(Q.SWEEP_CURSOR_PUUID_KEY)
    assert cursor_raw == b""


async def test_sweep_skip_when_locked(fake_redis, monkeypatch):
    """If the tick lock is already held, sweep_tick returns skip_locked immediately."""
    _patch_sweep(monkeypatch)

    # Pre-acquire the lock so sweep_tick sees it as taken.
    await fake_redis.set(Q.worker_tick_lock_key("sweep"), "1")

    result = await sweep_tick({"redis": fake_redis})

    assert result == {"status": "skip_locked"}

    # Nothing was enqueued.
    assert fake_redis.enqueued == []


async def test_sweep_paused(fake_redis, monkeypatch):
    """When the enable flag is '0', sweep_tick returns paused without touching the queue."""
    _patch_sweep(monkeypatch)

    await fake_redis.set(Q.worker_enabled_key("sweep"), "0")

    result = await sweep_tick({"redis": fake_redis})

    assert result == {"status": "paused"}
    assert fake_redis.enqueued == []


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

    # Only the 3 ids from the first tick were ever enqueued.
    assert _standard_job_ids(fake_redis) == {"m1", "m2", "m3"}
