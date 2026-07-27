"""End-to-end: sweep discovers → enqueues process_match jobs onto the real arq
queues (arena:standard / arena:priority).

All Redis via FakeRedis; the Riot client is an async stub. No DB, network, or
rating service touched. Running arq's real dispatch loop against these jobs is
a different testing strategy (would need a real arq Worker) and is out of
scope here — these tests assert what sweep_tick/priority_sweep_tick would
enqueue, via FakeRedis.enqueue_job's call log.
"""
from __future__ import annotations

from arena.workers import queues as Q
from arena.workers.sweep import priority_sweep_tick, sweep_tick


class _StubClient:
    # Signature mirrors the real RiotClient protocol — the sweep passes queue /
    # start_time, and a stub without them raises into the per-call except,
    # making every "enqueued" assertion below vacuously pass on zero work.
    #
    # Ids are namespaced by puuid so the standard sweep (puuid "pu-a") and the
    # priority sweep (puuid "pu-top") never discover the same match id — with a
    # shared id set the second sweep to run would find everything already
    # claimed in the seen-ZSET and enqueue nothing, which would make the
    # queue-separation test vacuously pass on an empty standard queue.
    async def list_match_ids(
        self,
        puuid: str,
        *,
        start: int = 0,
        count: int = 10,
        queue: int | None = None,
        start_time: int | None = None,
    ):
        return [f"{puuid}-m1", f"{puuid}-m2", f"{puuid}-m3"]

    async def get_match(self, mid):
        return None


def _patch(monkeypatch):
    monkeypatch.setattr("arena.workers.sweep.get_riot_client", lambda: _StubClient())

    async def _page(after, limit):
        return ["pu-a"]

    async def _selected():
        return []

    async def _top(limit):
        return []

    monkeypatch.setattr("arena.workers.sweep._tracked_puuids_after", _page)
    monkeypatch.setattr("arena.workers.sweep._selected_puuids", _selected)
    monkeypatch.setattr("arena.workers.sweep._top_n_puuids", _top)


async def test_sweep_enqueues_process_match_jobs_on_the_standard_queue(fake_redis, monkeypatch):
    _patch(monkeypatch)

    sweep_res = await sweep_tick({"redis": fake_redis})

    assert sweep_res["status"] == "ok"
    assert sweep_res["enqueued"] == 3
    ids = {"pu-a-m1", "pu-a-m2", "pu-a-m3"}
    jobs = [j for j in fake_redis.enqueued if j.queue_name == Q.STANDARD_QUEUE]
    assert {j.args[0] for j in jobs} == ids
    assert all(j.task == Q.PROCESS_MATCH_TASK for j in jobs)
    # The match id doubles as the job id — arq's own dedup layer on top of the
    # seen-ZSET claim (see sweep._push_claimed).
    assert {j.job_id for j in jobs} == {f"{Q.PROCESS_MATCH_TASK}:{mid}" for mid in ids}


async def test_priority_and_standard_sweeps_land_on_separate_queues(fake_redis, monkeypatch):
    """StandardWorker/PriorityWorker are two independently-scaled consumer
    pools now (not one pool draining a priority list first) — the queues they
    read from must stay genuinely separate, or a sustained priority sweep could
    starve the standard lane the way the old single-pool drain risked."""
    _patch(monkeypatch)

    await fake_redis.sadd(Q.TOP_PLAYERS_SET, "pu-top")
    await priority_sweep_tick({"redis": fake_redis})
    await sweep_tick({"redis": fake_redis})

    priority_jobs = [j for j in fake_redis.enqueued if j.queue_name == Q.PRIORITY_QUEUE]
    standard_jobs = [j for j in fake_redis.enqueued if j.queue_name == Q.STANDARD_QUEUE]
    assert priority_jobs, "priority sweep must enqueue onto arena:priority"
    assert standard_jobs, "standard sweep must enqueue onto arena:standard"
    assert {j.job_id for j in priority_jobs}.isdisjoint({j.job_id for j in standard_jobs})
