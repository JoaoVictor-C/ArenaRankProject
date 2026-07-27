"""Tests for arena.workers.backfill — the one-shot new-player history import.

Same conventions as test_sweep.py: FakeRedis + monkeypatch, no DB or network.
"""

from __future__ import annotations

from arena.core.config import settings
from arena.workers import queues as Q
from arena.workers.backfill import backfill_tick, enqueue_backfill


class _HistoryClient:
    """Two full pages then a short one, per (puuid, queue)."""

    def __init__(self, pages: int = 2) -> None:
        self.pages = pages
        self.calls: list[tuple[str, int | None, int | None]] = []

    async def list_match_ids(
        self,
        puuid: str,
        *,
        start: int = 0,
        count: int = 100,
        queue: int | None = None,
        start_time: int | None = None,
    ) -> list[str]:
        self.calls.append((puuid, queue, start_time))
        page = start // count
        if page >= self.pages:
            return []
        n = count if page < self.pages - 1 else 1
        return [f"m-{puuid}-{queue}-{start + i}" for i in range(n)]


class _BrokenClient:
    async def list_match_ids(self, puuid: str, **kw: object) -> list[str]:
        raise RuntimeError("riot down")


def _patch(monkeypatch, client) -> None:
    monkeypatch.setattr("arena.workers.backfill.get_riot_client", lambda: client)
    monkeypatch.setattr(settings, "backfill_matches_per_page", 5)
    monkeypatch.setattr(settings, "backfill_max_pages_per_player", 4)


# ---------------------------------------------------------------------------
# Producer
# ---------------------------------------------------------------------------


async def test_enqueue_is_one_shot_per_player(fake_redis):
    assert await enqueue_backfill(fake_redis, ("pu-a", "pu-b")) == 2
    # Re-registering the same players must NOT queue a second import.
    assert await enqueue_backfill(fake_redis, ("pu-a", "pu-b")) == 0

    queued = await fake_redis.rpop(Q.BACKFILL_PENDING_LIST, 10)
    assert sorted(queued) == [b"pu-a", b"pu-b"]


async def test_enqueue_deduplicates_within_one_call(fake_redis):
    assert await enqueue_backfill(fake_redis, ("pu-a", "pu-a")) == 1


async def test_enqueue_noop_when_disabled(fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "backfill_enabled", False)
    assert await enqueue_backfill(fake_redis, ("pu-a",)) == 0
    assert await fake_redis.rpop(Q.BACKFILL_PENDING_LIST) is None


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------


async def test_tick_imports_history_onto_the_standard_queue(fake_redis, monkeypatch):
    client = _HistoryClient(pages=2)
    _patch(monkeypatch, client)
    await enqueue_backfill(fake_redis, ("pu-a",))

    result = await backfill_tick({"redis": fake_redis})

    assert result["status"] == "ok"
    assert result["players"] == 1
    assert result["completed"] == 1
    # Per queue: one full page (5) + one short page (1) = 6 ids.
    per_queue = settings.backfill_matches_per_page + 1
    assert result["discovered"] == per_queue * len(settings.live_queue_ids)
    assert result["enqueued"] == result["discovered"]

    # Everything lands on the SAME arq queue the sweep feeds — no bypass path.
    jobs = [j for j in fake_redis.enqueued if j.queue_name == Q.STANDARD_QUEUE]
    assert len(jobs) == result["enqueued"]

    # Riot was always asked for a bounded window, never the whole history.
    assert all(start_time is not None for _, _, start_time in client.calls)


async def test_tick_is_bounded_by_max_pages(fake_redis, monkeypatch):
    _patch(monkeypatch, _HistoryClient(pages=99))
    monkeypatch.setattr(settings, "backfill_max_pages_per_player", 2)
    await enqueue_backfill(fake_redis, ("pu-a",))

    result = await backfill_tick({"redis": fake_redis})

    # 2 pages x 5 per page x queues — the cap holds, no unbounded crawl.
    expected = 2 * settings.backfill_matches_per_page * len(settings.live_queue_ids)
    assert result["discovered"] == expected


async def test_riot_failure_retries_then_gives_up(fake_redis, monkeypatch):
    _patch(monkeypatch, _BrokenClient())
    monkeypatch.setattr(settings, "backfill_max_attempts", 2)
    await enqueue_backfill(fake_redis, ("pu-a",))

    first = await backfill_tick({"redis": fake_redis})
    assert first["retried"] == 1
    # Back on the pending list — a partial import is never recorded as done.
    assert await fake_redis.llen(Q.BACKFILL_PENDING_LIST) == 1

    await fake_redis.delete(Q.worker_tick_lock_key("backfill"))
    second = await backfill_tick({"redis": fake_redis})
    assert second["dropped"] == 1
    assert await fake_redis.llen(Q.BACKFILL_PENDING_LIST) == 0


async def test_missing_riot_client_requeues_without_burning_an_attempt(fake_redis, monkeypatch):
    monkeypatch.setattr("arena.workers.backfill.get_riot_client", lambda: None)
    await enqueue_backfill(fake_redis, ("pu-a",))

    result = await backfill_tick({"redis": fake_redis})

    assert result["reason"] == "riot_client_unavailable"
    assert await fake_redis.llen(Q.BACKFILL_PENDING_LIST) == 1
    assert await fake_redis.hincrby(Q.BACKFILL_ATTEMPTS_HASH, "pu-a", 0) == 0


async def test_holds_under_sweep_backpressure(fake_redis, monkeypatch):
    _patch(monkeypatch, _HistoryClient())
    monkeypatch.setattr(settings, "sweep_pending_high_watermark", 1)
    await enqueue_backfill(fake_redis, ("pu-a",))
    # Simulate arq queue depth at/above the watermark (real depth = zcard).
    await fake_redis.zadd(Q.STANDARD_QUEUE, {"live-1": 1, "live-2": 2})

    result = await backfill_tick({"redis": fake_redis})

    # History import must never crowd out live matches.
    assert result["status"] == "pressure_hold"
    assert await fake_redis.llen(Q.BACKFILL_PENDING_LIST) == 1


async def test_paused_and_locked_short_circuit(fake_redis, monkeypatch):
    _patch(monkeypatch, _HistoryClient())
    await fake_redis.set(Q.worker_enabled_key("backfill"), "0")
    assert (await backfill_tick({"redis": fake_redis}))["status"] == "paused"

    await fake_redis.delete(Q.worker_enabled_key("backfill"))
    await fake_redis.set(Q.worker_tick_lock_key("backfill"), "1")
    assert (await backfill_tick({"redis": fake_redis}))["status"] == "skip_locked"
