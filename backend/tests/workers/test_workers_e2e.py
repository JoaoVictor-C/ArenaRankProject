"""End-to-end: sweep discovers → pending list → bulk processor drains+processes.

All Redis via FakeRedis; Riot client and process_match are async stubs. No DB,
network, or rating service touched.
"""
from __future__ import annotations

from arena.workers import queues as Q
from arena.workers.bulk_processor import bulk_process_tick
from arena.workers.sweep import priority_sweep_tick, sweep_tick


class _StubClient:
    async def list_match_ids(self, puuid: str, *, start: int = 0, count: int = 10):
        return ["m1", "m2", "m3"]

    async def get_match(self, mid):
        return None


def _patch(monkeypatch, processed: list[str]):
    monkeypatch.setattr("arena.workers.sweep.get_riot_client", lambda: _StubClient())

    async def _page(offset, limit):
        return ["pu-a"]

    async def _selected():
        return []

    async def _top(limit):
        return []

    monkeypatch.setattr("arena.workers.sweep._tracked_puuids_page", _page)
    monkeypatch.setattr("arena.workers.sweep._selected_puuids", _selected)
    monkeypatch.setattr("arena.workers.sweep._top_n_puuids", _top)

    async def _proc(ctx, mid):
        processed.append(mid)
        return {"matchId": mid, "status": "processed"}

    monkeypatch.setattr("arena.workers.bulk_processor.process_match", _proc)


async def test_sweep_then_bulk_processes_all(fake_redis, monkeypatch):
    processed: list[str] = []
    _patch(monkeypatch, processed)

    sweep_res = await sweep_tick({"redis": fake_redis})
    assert sweep_res["status"] == "ok"
    assert sweep_res["enqueued"] == 3

    bulk_res = await bulk_process_tick({"redis": fake_redis})
    assert bulk_res["status"] == "ok"
    assert bulk_res["total"] == 3
    assert set(processed) == {"m1", "m2", "m3"}
    # Attempts hash cleaned after success.
    assert await fake_redis.hincrby(Q.SWEEP_ATTEMPTS_KEY, "m1", 0) == 0


async def test_priority_drained_before_standard(fake_redis, monkeypatch):
    processed: list[str] = []
    _patch(monkeypatch, processed)

    # Seed one priority player so priority_sweep enqueues to the priority list.
    await fake_redis.sadd(Q.TOP_PLAYERS_SET, "pu-top")
    await priority_sweep_tick({"redis": fake_redis})
    # Standard sweep enqueues the same ids — but they're already in the seen-set,
    # so push a distinct standard id manually to prove ordering.
    await fake_redis.lpush(Q.SWEEP_PENDING_STANDARD, "s-late")

    drained_order: list[str] = []

    async def _proc(ctx, mid):
        drained_order.append(mid)
        return {"status": "processed"}

    monkeypatch.setattr("arena.workers.bulk_processor.process_match", _proc)
    await bulk_process_tick({"redis": fake_redis})

    # Priority ids (m1/m2/m3) come before the standard "s-late".
    assert drained_order[-1] == "s-late"
    assert set(drained_order[:-1]) == {"m1", "m2", "m3"}
