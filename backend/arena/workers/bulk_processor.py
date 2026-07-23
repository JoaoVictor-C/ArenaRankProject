from __future__ import annotations

import asyncio
import time
from typing import Any

from arq.worker import Retry

from arena.core.config import settings
from arena.core.logging import get_logger
from arena.workers import queues as Q
from arena.workers.processor import MAX_TRIES, process_match

_log = get_logger("arena.workers.bulk_processor")
_WORKER_NAME = "bulk_processor"


async def _drain_pending(redis: Any, batch_size: int) -> list[str]:
    """RPOP COUNT from the priority list first, fill remainder from standard."""
    mids: list[str] = []
    if batch_size <= 0:
        return mids
    raw_p = await redis.rpop(Q.SWEEP_PENDING_PRIORITY, batch_size)
    if raw_p:
        mids.extend(m.decode() if isinstance(m, bytes) else m for m in raw_p)
    remaining = batch_size - len(mids)
    if remaining > 0:
        raw_s = await redis.rpop(Q.SWEEP_PENDING_STANDARD, remaining)
        if raw_s:
            mids.extend(m.decode() if isinstance(m, bytes) else m for m in raw_s)
    return mids


async def _process_one(redis: Any, mid: str) -> str:
    job_try = int(await redis.hincrby(Q.SWEEP_ATTEMPTS_KEY, mid, 1))
    await redis.expire(Q.SWEEP_ATTEMPTS_KEY, 7 * 24 * 3600)
    fake_ctx = {"redis": redis, "job_try": job_try, "job_id": f"bulk:{mid}"}
    try:
        result = await process_match(fake_ctx, mid)
        status = str(result.get("status", "processed")) if isinstance(result, dict) else "processed"
        # All dict statuses (processed / filtered / skipped / dead_lettered) are
        # terminal — clean up the attempts entry so the hash can't grow forever.
        await redis.hdel(Q.SWEEP_ATTEMPTS_KEY, mid)
        return status
    except Retry:
        # job_try < MAX_TRIES — requeue to standard for the next bulk tick.
        await redis.lpush(Q.SWEEP_PENDING_STANDARD, mid)
        return "requeued"
    except Exception as exc:  # noqa: BLE001
        # Unexpected error escaping process_match: the mid was already RPOP'd, so
        # requeue it (until MAX_TRIES) instead of silently dropping the match.
        _log.warning("bulk_processor.process_one_error", matchId=mid, error=str(exc), job_try=job_try)
        if job_try < MAX_TRIES:
            try:
                await redis.lpush(Q.SWEEP_PENDING_STANDARD, mid)
            except Exception:  # noqa: BLE001 — redis down; best-effort
                return "error"
            return "error_requeued"
        await redis.hdel(Q.SWEEP_ATTEMPTS_KEY, mid)
        return "error_dropped"


async def bulk_process_tick(ctx: dict[str, Any]) -> dict[str, Any]:
    """Drain the sweep pending lists in back-to-back batches (priority first).

    A single batch (``bulk_batch_size``) per tick used to be the hard ceiling:
    with a 1-minute tick interval, throughput was capped at
    ``bulk_batch_size / bulk_processor_interval_minutes`` regardless of how
    much backlog was waiting or how fast individual matches actually process
    (I/O-bound — usually far faster than that). This now loops batches until
    the pending lists are empty or ``bulk_max_seconds_per_tick`` is spent, so a
    backlog spike drains in one tick instead of trickling in over many.
    """
    redis = ctx["redis"]
    try:
        if await redis.get(Q.worker_enabled_key(_WORKER_NAME)) == b"0":
            return {"status": "paused"}
        ttl = max(settings.bulk_processor_interval_minutes * 60 - 5, 10)
        if not await redis.set(Q.worker_tick_lock_key(_WORKER_NAME), "1", nx=True, ex=ttl):
            return {"status": "skip_locked"}

        sem = asyncio.Semaphore(settings.bulk_concurrency)

        async def _bounded(mid: str) -> str:
            async with sem:
                return await _process_one(redis, mid)

        deadline = time.monotonic() + settings.bulk_max_seconds_per_tick
        counts: dict[str, int] = {}
        total = 0
        batches = 0
        while time.monotonic() < deadline:
            mids = await _drain_pending(redis, settings.bulk_batch_size)
            if not mids:
                break
            batches += 1
            total += len(mids)
            results = await asyncio.gather(*[_bounded(m) for m in mids], return_exceptions=True)
            for r in results:
                key = r if isinstance(r, str) else "exception"
                counts[key] = counts.get(key, 0) + 1

        if total == 0:
            return {"status": "ok", "processed": 0}
        _log.info("bulk_processor.tick", total=total, batches=batches, **counts)
        return {"status": "ok", "total": total, "batches": batches, **counts}
    except Exception as exc:  # noqa: BLE001 — never raise out of a cron tick
        _log.warning("bulk_processor.tick.error", error=str(exc), exc_info=True)
        return {"status": "error", "error": str(exc)}


__all__ = ["bulk_process_tick", "_drain_pending", "_process_one"]
