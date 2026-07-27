"""New-player history backfill — the one-shot catch-up for a freshly seen puuid.

A ``players`` row is only ever born as a side effect of a lobby-mate's match
being processed (:func:`arena.services.match_pipeline.register_players`). Before
this module nothing looked at the history that player already had:

* the steady-state sweep only ever asks Riot for the newest
  ``settings.sweep_matches_per_player`` ids, so anything older is never
  requested;
* the sweep does not even *see* the player until
  ``player_seasons.matches_played > 0``, which never happens if their first
  observed match was AFK / early-surrender / frozen (the rating service only
  increments that counter for eligible, non-voided results) — such a player was
  permanently invisible to discovery;
* ``reconcile_tick`` is windowed from the scheduler heartbeat gap, i.e. it is
  outage catch-up, not per-player history.

so the only way to import a player's past was an operator running
``scripts/backfill.py`` by hand.

Flow: ``match_pipeline`` calls :func:`enqueue_backfill` with the puuids its
upsert genuinely INSERTed → they land on ``BACKFILL_PENDING_LIST`` (guarded by
``BACKFILL_CLAIMED_SET`` so the one-shot survives restarts and re-registration)
→ :func:`backfill_tick` drains them, paginates Riot's match-id endpoint back to
the launch-window cutoff, and enqueues what it finds onto the SAME standard arq
queue the sweep feeds. Everything downstream (claim/dedup, cheap filter,
``process_match``, cutoff, idempotency) is therefore byte-for-byte the normal
path — this module only widens *discovery*.

Deliberately a background citizen: it holds when the combined arq queue depth
is above its high-water mark, so importing history never starves live matches.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from arena.core.config import settings
from arena.core.logging import get_logger
from arena.workers import queues as Q
from arena.workers.deps import get_riot_client
from arena.workers.ingestion import _combined_queue_depth, _dedup_new
from arena.workers.sweep import _push_claimed

_log = get_logger("arena.workers.backfill")

_WORKER_BACKFILL = "backfill"


# ---------------------------------------------------------------------------
# Producer — called from the write path
# ---------------------------------------------------------------------------


async def enqueue_backfill(redis: Any, puuids: tuple[str, ...] | list[str]) -> int:
    """Queue *puuids* for their one-shot history backfill. Returns how many were
    newly claimed.

    ``SADD`` on ``BACKFILL_CLAIMED_SET`` is the one-shot guard and is checked
    BEFORE the push, so a player registered twice (two matches of theirs land in
    the same tick) is enqueued once, and a restart mid-drain cannot re-import a
    player whose backfill already ran. The claimed set is intentionally
    permanent: it is one small member per player ever seen, and losing it would
    mean re-walking every player's history.

    Best-effort by contract — this runs after the rating transaction has already
    committed, so a Redis blip must never turn a persisted match into a failure.
    """
    if not puuids or redis is None or not settings.backfill_enabled:
        return 0
    queued = 0
    for puuid in puuids:
        try:
            if not await redis.sadd(Q.BACKFILL_CLAIMED_SET, puuid):
                continue  # already backfilled (or in flight)
            await redis.lpush(Q.BACKFILL_PENDING_LIST, puuid)
            queued += 1
        except Exception:  # noqa: BLE001 - never fail a committed match
            _log.warning("backfill.enqueue_failed", puuid=puuid[:8])
    if queued:
        _log.info("backfill.enqueued", players=queued)
    return queued


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------


def _backfill_since() -> int:
    """Epoch second to paginate back to.

    Never reaches past ``settings.match_min_started_at_ms``: the pipeline drops
    anything older via ``match_pipeline.before_cutoff``, so requesting it would
    burn Riot budget to discover ids that are guaranteed to be filtered. Bounded
    below by ``backfill_window_seconds`` so a long-lived season cannot make each
    new player an unbounded crawl.
    """
    window_floor = int(time.time()) - settings.backfill_window_seconds
    cutoff_s = settings.match_min_started_at_ms // 1000
    return max(window_floor, cutoff_s)


async def _history_for(client: Any, puuid: str, since: int) -> tuple[list[str], bool]:
    """All match ids for *puuid* since *since*, across the live queues.

    Returns ``(ids, ok)``. ``ok`` is False when any queue's pagination aborted on
    a Riot error, which is what makes the player worth retrying — a partial
    import must not be recorded as a completed backfill.
    """
    ids: list[str] = []
    ok = True
    for queue_id in settings.live_queue_ids:
        start = 0
        for _ in range(settings.backfill_max_pages_per_player):
            try:
                got = await client.list_match_ids(
                    puuid,
                    start=start,
                    count=settings.backfill_matches_per_page,
                    queue=queue_id,
                    start_time=since,
                )
            except Exception:  # noqa: BLE001
                _log.warning("backfill.list_failed", puuid=puuid[:8], queue=queue_id)
                ok = False
                break
            if not got:
                break
            ids.extend(got)
            if len(got) < settings.backfill_matches_per_page:
                break
            start += settings.backfill_matches_per_page
    return ids, ok


async def _retry_or_drop(redis: Any, puuid: str) -> str:
    """Requeue *puuid* until ``backfill_max_attempts``, then give up on it.

    On the final drop the claimed-set membership stays, so a player whose Riot
    history is persistently unreadable is not retried forever on every future
    match of theirs. The steady-state sweep still covers them from here on.
    """
    attempts = int(await redis.hincrby(Q.BACKFILL_ATTEMPTS_HASH, puuid, 1))
    if attempts < settings.backfill_max_attempts:
        await redis.lpush(Q.BACKFILL_PENDING_LIST, puuid)
        return "retried"
    await redis.hdel(Q.BACKFILL_ATTEMPTS_HASH, puuid)
    _log.warning("backfill.gave_up", puuid=puuid[:8], attempts=attempts)
    return "dropped"


async def backfill_tick(ctx: dict[str, Any]) -> dict[str, Any]:
    """Drain a batch of newly-registered players and import their history.

    Registered as a cron job on :class:`arena.workers.main.SweepWorker`.
    """
    redis = ctx["redis"]
    try:
        if not settings.backfill_enabled:
            return {"status": "disabled"}
        if await redis.get(Q.worker_enabled_key(_WORKER_BACKFILL)) == b"0":
            return {"status": "paused"}
        ttl = max(settings.backfill_interval_minutes * 60 - 5, 10)
        if not await redis.set(Q.worker_tick_lock_key(_WORKER_BACKFILL), "1", nx=True, ex=ttl):
            return {"status": "skip_locked"}

        # History import is bulk work; never let it starve live matches.
        if await _combined_queue_depth(redis) >= settings.sweep_pending_high_watermark:
            return {"status": "pressure_hold", "discovered": 0, "enqueued": 0}

        raw = await redis.rpop(Q.BACKFILL_PENDING_LIST, settings.backfill_batch_size)
        puuids = [p.decode() if isinstance(p, bytes) else p for p in (raw or [])]
        if not puuids:
            return {"status": "ok", "players": 0}

        client = get_riot_client()
        if client is None:
            # Not a failure of the player's data — put them straight back
            # without burning an attempt.
            for puuid in puuids:
                await redis.lpush(Q.BACKFILL_PENDING_LIST, puuid)
            return {"status": "ok", "players": 0, "reason": "riot_client_unavailable"}

        since = _backfill_since()
        sem = asyncio.Semaphore(settings.backfill_fetch_concurrency)

        async def _bounded(puuid: str) -> tuple[str, list[str], bool]:
            async with sem:
                ids, ok = await _history_for(client, puuid, since)
                return puuid, ids, ok

        results = await asyncio.gather(*[_bounded(p) for p in puuids])

        discovered = enqueued = completed = retried = dropped = 0
        for puuid, ids, ok in results:
            discovered += len(ids)
            if ids:
                fresh = await _dedup_new(redis, ids)
                eligible = [
                    m
                    for m in fresh
                    if Q.evaluate_match_filters(Q.MatchMeta(riot_match_id=m)).eligible
                ]
                enqueued += await _push_claimed(redis, Q.STANDARD_QUEUE, eligible)
            if ok:
                await redis.hdel(Q.BACKFILL_ATTEMPTS_HASH, puuid)
                completed += 1
            elif await _retry_or_drop(redis, puuid) == "retried":
                retried += 1
            else:
                dropped += 1

        result: dict[str, Any] = {
            "status": "ok",
            "players": len(puuids),
            "since": since,
            "discovered": discovered,
            "enqueued": enqueued,
            "completed": completed,
            "retried": retried,
            "dropped": dropped,
        }
        _log.info("backfill.tick", **result)
        return result
    except Exception as exc:  # noqa: BLE001 — never raise out of a cron tick
        _log.warning("backfill.tick.error", error=str(exc), exc_info=True)
        return {"status": "error", "error": str(exc)}


__all__ = ["enqueue_backfill", "backfill_tick"]
