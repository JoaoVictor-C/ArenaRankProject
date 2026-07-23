"""Match processor — the arq consumer (proposal section 13.2).

One match per ``process_match`` job:

    1. idempotency  — ``SET NX`` the per-match processed flag; a duplicate
       dequeue exits immediately (proposal section 13.2 Redis atomic GET/SET).
    2. fetch        — full match payload, cache-first, via the Riot client.
    3. filter       — authoritative queue/participant/duration/season check now
       that the full payload is available; a failure marks FILTERED + audit, no
       rating movement.
    4. rate + write — delegate to the Wave-2 rating service, which runs
       :func:`arena.rating.engine.rate` and persists ``player_seasons`` /
       ``match_participants`` / ``champion_stats`` / ``cr_snapshots`` /
       ``integrity_events`` / ``matches.processed`` in one transaction under the
       per-player Redis lock.
    5. emit         — publish ``match.processed`` (cache warmer + webhooks).

Retry / DLQ (proposal section 6.3): arq's ``max_tries`` retries transient
failures up to 3×. On the final failed attempt the job is routed to the DLQ
(a Redis list) with its error context instead of being silently dropped, so the
admin DLQ-review surface (proposal section 4.3) can inspect / replay it.

Idempotency note: the processed flag is set *before* the write transaction. If
the transaction later fails and the job retries, the flag is cleared on the
failure path so the retry is not short-circuited into a false "already done".
The durable ``matches.processed`` column (set inside the rating-service
transaction) is the permanent source of truth; the Redis flag is only a fast
in-flight guard.
"""

from __future__ import annotations

import json
import time
from typing import Any

from arq.worker import Retry

from arena.core.config import settings
from arena.core.logging import get_logger
from arena.workers import queues as Q
from arena.workers.deps import get_rating_service, get_riot_client

_log = get_logger("arena.workers.processor")

#: Total attempts before a job is dead-lettered (proposal section 6.3 "up to 3×").
MAX_TRIES = 3

#: Backoff (seconds) between retries, indexed by the *upcoming* attempt number.
#: Short + bounded; the rating pipeline is CPU/DB-bound, not rate-limited here.
_RETRY_BACKOFF = (0.0, 2.0, 5.0)


def _backoff_for(job_try: int) -> float:
    idx = min(max(job_try - 1, 0), len(_RETRY_BACKOFF) - 1)
    return _RETRY_BACKOFF[idx]


async def _emit_processed(redis: Any, summary: dict[str, Any]) -> None:
    """Publish a ``match.processed`` event for downstream consumers (§13.2)."""
    try:
        await redis.publish(Q.MATCH_PROCESSED_CHANNEL, json.dumps(summary))
    except Exception:  # pragma: no cover - event emission is best-effort
        _log.warning("processor.emit_failed", matchId=summary.get("matchId"))


async def _dead_letter(redis: Any, riot_match_id: str, *, error: str, job_try: int) -> None:
    """Push an exhausted job onto the DLQ list with diagnostic context."""
    entry = {
        "matchId": riot_match_id,
        "error": error,
        "tries": job_try,
        "deadLetteredAt": time.time(),
    }
    try:
        await redis.rpush(Q.DLQ_KEY, json.dumps(entry))
        _log.error("processor.dead_lettered", matchId=riot_match_id, tries=job_try, error=error)
    except Exception:  # pragma: no cover - last-ditch; nothing else to do
        _log.error("processor.dlq_push_failed", matchId=riot_match_id, error=error)


def _payload_meta(riot_match_id: str, payload: dict[str, Any]) -> Q.MatchMeta:
    """Extract the filter descriptor from a full Riot match payload.

    Tolerant of the nested Riot shape (``info.queueId`` /
    ``info.participants`` / ``info.gameDuration``); missing fields degrade to
    ``None`` and defer to a permissive verdict rather than a hard reject.
    """
    info = payload.get("info") if isinstance(payload, dict) else None
    info = info if isinstance(info, dict) else {}
    participants = info.get("participants")
    return Q.MatchMeta(
        riot_match_id=riot_match_id,
        queue_id=info.get("queueId"),
        participant_count=len(participants) if isinstance(participants, list) else None,
        duration_seconds=info.get("gameDuration"),
        in_active_season=None,  # the rating service maps played_at → season window
    )


async def process_match(ctx: dict[str, Any], riot_match_id: str) -> dict[str, Any]:
    """Process a single match. Registered as the ``process_match`` arq task.

    ``ctx`` carries arq's ``redis`` pool, ``job_try`` (1-based attempt) and
    ``job_id``. Raising :class:`arq.worker.Retry` requeues with backoff; on the
    final attempt the error is caught, dead-lettered, and a terminal summary is
    returned so the job is not retried further.
    """
    redis: Any = ctx["redis"]
    job_try: int = int(ctx.get("job_try", 1))
    flag_key = Q.processed_flag_key(riot_match_id)

    # 1. Idempotency guard (atomic SET NX). Already-set -> someone else did it.
    try:
        acquired = await redis.set(flag_key, "1", nx=True, ex=Q.PROCESSED_FLAG_TTL_SECONDS)
    except Exception as exc:
        _log.warning("processor.flag_set_failed", matchId=riot_match_id, error=str(exc))
        acquired = True  # fail open: better to risk a redo than to drop the match

    if not acquired:
        _log.info("processor.skip_already_processed", matchId=riot_match_id)
        return {"matchId": riot_match_id, "status": "skipped", "reason": "already_processed"}

    try:
        return await _run_pipeline(ctx, redis, riot_match_id, job_try)
    except Retry:
        # Retry path: release the in-flight flag so the requeued attempt is not
        # short-circuited by its own prior SET NX.
        await _release_flag(redis, flag_key)
        raise
    except Exception as exc:  # noqa: BLE001 - boundary: classify into retry vs DLQ
        await _release_flag(redis, flag_key)
        if job_try < MAX_TRIES:
            _log.warning(
                "processor.retry",
                matchId=riot_match_id,
                tries=job_try,
                error=str(exc),
            )
            raise Retry(defer=_backoff_for(job_try + 1)) from exc
        await _dead_letter(redis, riot_match_id, error=str(exc), job_try=job_try)
        return {"matchId": riot_match_id, "status": "dead_lettered", "error": str(exc)}


async def _run_pipeline(
    ctx: dict[str, Any],
    redis: Any,
    riot_match_id: str,
    job_try: int,
) -> dict[str, Any]:
    """The non-idempotency body of :func:`process_match` (steps 2–5)."""
    # 2. Fetch (cache-first) the full payload.
    client = get_riot_client()
    if client is None:
        # Dependency not yet wired (W2) — retryable, not a permanent failure.
        raise RuntimeError("riot_client_unavailable")

    payload = await client.get_match(riot_match_id)
    if payload is None:
        # Transient (cache miss + upstream blip) — let arq retry / DLQ it.
        raise RuntimeError("match_payload_unavailable")

    # 3. Authoritative filter now that the full payload is known.
    verdict = Q.evaluate_match_filters(_payload_meta(riot_match_id, payload))
    if not verdict.eligible:
        _log.info("processor.filtered", matchId=riot_match_id, reason=verdict.reason)
        # FILTERED is a terminal, non-error outcome: keep the processed flag set
        # so we never re-fetch this match, and emit an audit line.
        return {"matchId": riot_match_id, "status": "filtered", "reason": verdict.reason}

    # 4. Rate + persist via the Wave-2 transactional service.
    service = get_rating_service()
    if service is None:
        raise RuntimeError("rating_service_unavailable")

    summary = await service.process_match(riot_match_id, payload, redis=redis)
    summary.setdefault("matchId", riot_match_id)
    summary.setdefault("status", "processed")

    # 5. Emit the downstream event + schedule session re-arm re-polls.
    await _emit_processed(redis, summary)
    await _schedule_rearm(redis, payload)
    _log.info("processor.processed", matchId=riot_match_id, tries=job_try)
    return summary


async def _schedule_rearm(redis: Any, payload: dict[str, Any]) -> None:
    """Schedule quick re-polls for every participant of a recent match.

    A PROCESSED match that ended minutes ago proves its 16-18 players are in
    an Arena session right now — their next match is the highest-value thing
    the sweep can discover. The recency gate keeps backlog catch-up (old
    matches processed late) from scheduling pointless polls. ZADD LT: a fresh
    match always pulls a player's next poll EARLIER, never postpones it.
    Best-effort by design — a failure here never fails the processed match.
    """
    if not settings.rearm_enabled:
        return
    try:
        info = payload.get("info") if isinstance(payload, dict) else None
        info = info if isinstance(info, dict) else {}
        end_ms = info.get("gameEndTimestamp") or 0
        if not end_ms:
            start_ms = info.get("gameStartTimestamp") or 0
            duration = info.get("gameDuration") or 0
            end_ms = start_ms + duration * 1000 if start_ms else 0
        now = time.time()
        if not end_ms or (now - end_ms / 1000.0) > settings.rearm_recency_seconds:
            return
        meta = payload.get("metadata") if isinstance(payload, dict) else None
        meta = meta if isinstance(meta, dict) else {}
        puuids = [p for p in (meta.get("participants") or []) if isinstance(p, str) and p]
        if not puuids:
            return
        due = now + settings.rearm_delays[0]
        await redis.zadd(Q.REARM_ZSET, {p: due for p in puuids}, lt=True)
        await redis.hdel(Q.REARM_MISSES_HASH, *puuids)
    except Exception:  # noqa: BLE001 — best-effort side channel
        _log.warning("processor.rearm_schedule_failed", matchId=payload.get("metadata", {}).get("matchId") if isinstance(payload, dict) else None)


async def _release_flag(redis: Any, flag_key: str) -> None:
    """Best-effort clear of the in-flight processed flag (retry/failure paths)."""
    try:
        await redis.delete(flag_key)
    except Exception:  # pragma: no cover - flag has a TTL backstop anyway
        _log.warning("processor.flag_release_failed", key=flag_key)


__all__ = ["process_match", "MAX_TRIES"]
