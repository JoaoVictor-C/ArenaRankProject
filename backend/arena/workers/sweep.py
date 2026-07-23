"""Standard sweep worker — poll DB-tracked players and enqueue new match ids.

Each ``sweep_tick`` call:
1. Checks the worker-level enable flag (Redis key).
2. Acquires a per-tick mutex so overlapping cron invocations are a no-op.
3. Delegates to ``_update_pressure_mode`` (ingestion) to honour the
   high/low-water backpressure hysteresis.
4. Pages through tracked players using a rotating DB cursor.
5. Fetches recent match ids from Riot for each player (Wave-2 client).
6. Deduplicates via the shared ``seen_matches`` set (reuses ``_dedup_new``).
7. Cheap-filters and pushes eligible ids onto ``SWEEP_PENDING_STANDARD``.

Also in this module: ``rearm_tick`` (session re-arm re-polls) and
``reconcile_tick`` (bounded, ``start_time``-windowed outage catch-up — see its
own section below for why this exists and what it does differently from the
steady-state sweep above).

Import-safe before Wave 2: all DB / Riot references are wrapped in try/except
so ruff + mypy pass and the worker degrades gracefully.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from arena.core.config import settings
from arena.core.logging import get_logger
from arena.workers import queues as Q
from arena.workers.deps import get_riot_client
from arena.workers.ingestion import _dedup_new


async def _sweep_pending_depth(redis: Any) -> int:
    """Combined depth of the sweep pending lists — the sweep pipeline's OWN
    backpressure signal (the legacy ``_update_pressure_mode`` only measures the
    arq queues, which the sweep pipeline never feeds)."""
    try:
        p = int(await redis.llen(Q.SWEEP_PENDING_PRIORITY) or 0)
        s = int(await redis.llen(Q.SWEEP_PENDING_STANDARD) or 0)
        return p + s
    except Exception:  # noqa: BLE001
        return 0

_log = get_logger("arena.workers.sweep")
_WORKER_SWEEP = "sweep"
_WORKER_PRIORITY_SWEEP = "priority_sweep"
_WORKER_REARM = "rearm"
_WORKER_RECONCILE = "reconcile"


# ---------------------------------------------------------------------------
# Small helpers (tested in isolation via fake_redis fixture)
# ---------------------------------------------------------------------------


async def _check_enabled(redis: Any, name: str) -> bool:
    """Return False only when the flag is explicitly set to b'0'."""
    val = await redis.get(Q.worker_enabled_key(name))
    return bool(val != b"0")


async def _acquire_tick_lock(redis: Any, name: str, ttl: int) -> bool:
    """SET NX EX — returns True when we won the lock, False when already held."""
    return bool(await redis.set(Q.worker_tick_lock_key(name), "1", nx=True, ex=ttl))


async def _tracked_puuids_page(offset: int, limit: int) -> list[str]:
    """One page of tracked-player PUUIDs from the DB (avoids loading all at once).

    Falls back to [] when the DB layer is not yet importable (Wave-1 / test
    environments that monkeypatch this function directly).
    """
    try:
        from sqlalchemy import select

        from arena.db.models import Player, PlayerSeason
        from arena.db.session import get_sessionmaker
    except Exception:  # noqa: BLE001
        return []
    factory = get_sessionmaker()
    async with factory() as session:
        stmt = (
            select(Player.puuid)
            .join(PlayerSeason, PlayerSeason.player_id == Player.id)
            .where(PlayerSeason.matches_played > 0)
            .distinct()
            .order_by(Player.puuid)
            .offset(offset)
            .limit(limit)
        )
        rows = await session.execute(stmt)
        return [p for (p,) in rows.all() if p]


async def _fetch_and_enqueue(
    redis: Any, puuids: list[str], pending_key: str, *, skip_dedup: bool = False
) -> tuple[int, int]:
    """Fetch match ids for *puuids*, dedup, filter, enqueue to *pending_key*.

    ``skip_dedup=True`` (priority catch-up) bypasses the shared seen-set so ids
    already discovered — e.g. buried deep in the standard backlog — are enqueued
    again; ``matches.processed`` idempotency makes repeats cheap no-ops.

    Returns ``(discovered_total, enqueued_fresh)`` counters for the tick result.
    Returns ``(0, 0)`` when the Riot client is not yet available.
    """
    client = get_riot_client()
    if client is None:
        return 0, 0

    # One call per LIVE Arena queue id (match-v5 filters a single queue per
    # call). Only queues in rotation can produce new matches — polling retired
    # ids (1700/1710: zero post-cutoff matches) was pure budget waste. The
    # unfiltered deep sample (_deep_sample) is the safety net that surfaces a
    # brand-new queue id before anyone updates ARENA_LIVE_QUEUE_IDS.
    #
    # Calls run concurrently under a local semaphore — serial awaits left the
    # Riot budget ~90% idle (the client's token bucket is the real ceiling).
    sem = asyncio.Semaphore(settings.sweep_fetch_concurrency)

    async def _fetch_one(puuid: str, queue_id: int) -> list[str]:
        async with sem:
            try:
                return await client.list_match_ids(
                    puuid, count=settings.sweep_matches_per_player, queue=queue_id
                )
            except Exception:  # noqa: BLE001
                _log.warning("sweep.list_failed", puuid=puuid[:8], queue=queue_id)
                return []

    batches = await asyncio.gather(
        *[
            _fetch_one(puuid, queue_id)
            for puuid in puuids
            for queue_id in settings.live_queue_ids
        ]
    )
    discovered: list[str] = [mid for ids in batches for mid in ids]

    if not discovered:
        return 0, 0

    if skip_dedup:
        fresh = list(dict.fromkeys(discovered))  # dedup interno do lote apenas
    else:
        fresh = await _dedup_new(redis, discovered)
    for mid in fresh:
        if Q.evaluate_match_filters(Q.MatchMeta(riot_match_id=mid)).eligible:
            await redis.lpush(pending_key, mid)

    return len(discovered), len(fresh)


async def _deep_sample(redis: Any, puuids: list[str]) -> int:
    """Rotation-detection safety net: one UNFILTERED ids call for a tiny
    rotating sample of the current sweep page, bounded by startTime.

    A brand-new Arena queue id (Riot mints one per rotation) is invisible to
    the live-queue sweep until ARENA_LIVE_QUEUE_IDS is updated — but it shows
    up here, passes the id-only cheap filter, and the processor's CHERRY
    gameMode fallback rates it normally. Non-Arena ids in the sample are
    discarded at processing for the price of a payload fetch — bounded to
    ~deep_sample_per_tick × ticks/day fetches, which is noise.

    Returns the number of ids enqueued.
    """
    sample_n = settings.deep_sample_per_tick
    if sample_n <= 0 or not puuids:
        return 0
    client = get_riot_client()
    if client is None:
        return 0
    offset = int(await redis.get(Q.DEEP_SAMPLE_CURSOR_KEY) or 0)
    sample = [puuids[(offset + i) % len(puuids)] for i in range(min(sample_n, len(puuids)))]
    await redis.set(Q.DEEP_SAMPLE_CURSOR_KEY, str((offset + sample_n) % (10**9)))

    since = int(time.time()) - settings.deep_sample_window_seconds
    discovered: list[str] = []
    for puuid in sample:
        try:
            discovered += await client.list_match_ids(puuid, count=20, start_time=since)
        except Exception:  # noqa: BLE001
            _log.warning("sweep.deep_sample_failed", puuid=puuid[:8])
    if not discovered:
        return 0
    fresh = await _dedup_new(redis, discovered)
    enqueued = 0
    for mid in fresh:
        if Q.evaluate_match_filters(Q.MatchMeta(riot_match_id=mid)).eligible:
            await redis.lpush(Q.SWEEP_PENDING_STANDARD, mid)
            enqueued += 1
    return enqueued


# ---------------------------------------------------------------------------
# arq task entrypoint
# ---------------------------------------------------------------------------


async def sweep_tick(ctx: dict[str, Any]) -> dict[str, Any]:
    """One standard sweep tick.  Registered as a cron job in WorkerSettings.

    Returns a JSON-serialisable dict that arq stores as the job result so
    operators can observe throughput without tailing logs.
    """
    redis = ctx["redis"]
    try:
        if not await _check_enabled(redis, _WORKER_SWEEP):
            return {"status": "paused"}

        ttl = max(settings.sweep_interval_minutes * 60 - 5, 10)
        if not await _acquire_tick_lock(redis, _WORKER_SWEEP, ttl):
            return {"status": "skip_locked"}

        if await _sweep_pending_depth(redis) >= settings.sweep_pending_high_watermark:
            return {"status": "pressure_hold", "discovered": 0, "enqueued": 0}

        cursor = int(await redis.get(Q.SWEEP_CURSOR_KEY) or 0)
        puuids = await _tracked_puuids_page(cursor, settings.sweep_batch_size)

        # Advance cursor; wrap to 0 when this page was smaller than the batch
        # (meaning we've exhausted the player set for this rotation).
        new_cursor = (
            cursor + settings.sweep_batch_size
            if len(puuids) == settings.sweep_batch_size
            else 0
        )
        await redis.set(Q.SWEEP_CURSOR_KEY, str(new_cursor))

        discovered, enqueued = await _fetch_and_enqueue(
            redis, puuids, Q.SWEEP_PENDING_STANDARD
        )
        deep_enqueued = await _deep_sample(redis, puuids)

        result: dict[str, Any] = {
            "status": "ok",
            "cursor": cursor,
            "puuids": len(puuids),
            "discovered": discovered,
            "enqueued": enqueued,
            "deep": deep_enqueued,
        }
        _log.info("sweep.tick", **result)
        return result

    except Exception as exc:  # noqa: BLE001 — must never raise out of a cron tick
        _log.warning("sweep.tick.error", error=str(exc), exc_info=True)
        return {"status": "error", "error": str(exc)}


async def _selected_puuids() -> list[str]:
    try:
        from sqlalchemy import select
        from arena.db.models import Player
        from arena.db.session import get_sessionmaker
    except Exception:  # noqa: BLE001
        return []
    factory = get_sessionmaker()
    async with factory() as session:
        rows = await session.execute(select(Player.puuid).where(Player.is_selected.is_(True)))
        return [p for (p,) in rows.all() if p]


async def _top_n_puuids(limit: int) -> list[str]:
    """Top-N players by CR straight from the DB — keeps the priority sweep
    functional even when the Redis TOP_PLAYERS_SET cache is unpopulated (the
    scheduler maintains it, but the sweep must not depend on it)."""
    try:
        from sqlalchemy import select

        from arena.db.models import Player, PlayerSeason
        from arena.db.session import get_sessionmaker
    except Exception:  # noqa: BLE001
        return []
    factory = get_sessionmaker()
    async with factory() as session:
        stmt = (
            select(Player.puuid)
            .join(PlayerSeason, PlayerSeason.player_id == Player.id)
            .order_by(PlayerSeason.cr.desc())
            .limit(limit)
        )
        rows = await session.execute(stmt)
        return [p for (p,) in rows.all() if p]


async def _priority_seeds(redis: Any) -> list[str]:
    """Top-1000 (Redis cache ∪ DB top-N by CR) plus admin-selected players,
    deduped with a stable order. TOP_PLAYERS_SET is read as a SET (smembers),
    matching the legacy ``ingestion._is_priority`` convention."""
    try:
        top = await redis.smembers(Q.TOP_PLAYERS_SET)
        top_puuids = [p.decode() if isinstance(p, bytes) else p for p in top]
    except Exception:  # noqa: BLE001
        top_puuids = []
    db_top = await _top_n_puuids(settings.priority_top_n)
    selected = await _selected_puuids()
    seen: set[str] = set()
    merged: list[str] = []
    for p in [*top_puuids, *db_top, *selected]:
        if p and p not in seen:
            seen.add(p)
            merged.append(p)
    return merged


async def priority_sweep_tick(ctx: dict[str, Any]) -> dict[str, Any]:
    redis = ctx["redis"]
    try:
        if not await _check_enabled(redis, _WORKER_PRIORITY_SWEEP):
            return {"status": "paused"}
        ttl = max(settings.priority_sweep_interval_minutes * 60 - 5, 10)
        if not await _acquire_tick_lock(redis, _WORKER_PRIORITY_SWEEP, ttl):
            return {"status": "skip_locked"}
        # Priority sweep is EXEMPT from backpressure so Top-1000 / selected
        # players stay fresh even when the standard backlog is deep.
        seeds = await _priority_seeds(redis)
        cursor = int(await redis.get(Q.PRIORITY_SWEEP_CURSOR_KEY) or 0)
        batch = seeds[cursor : cursor + settings.priority_sweep_batch_size]
        new_cursor = cursor + settings.priority_sweep_batch_size if len(batch) == settings.priority_sweep_batch_size else 0
        await redis.set(Q.PRIORITY_SWEEP_CURSOR_KEY, str(new_cursor))
        discovered, enqueued = await _fetch_and_enqueue(
            redis, batch, Q.SWEEP_PENDING_PRIORITY,
            skip_dedup=settings.priority_sweep_skip_dedup,
        )
        result = {"status": "ok", "seeds": len(seeds), "cursor": cursor, "discovered": discovered, "enqueued": enqueued}
        _log.info("priority_sweep.tick", **result)
        return result
    except Exception as exc:  # noqa: BLE001 — never raise out of a cron tick
        _log.warning("priority_sweep.tick.error", error=str(exc), exc_info=True)
        return {"status": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# Session re-arm — quick re-polls for players provably mid-session
# ---------------------------------------------------------------------------


async def rearm_tick(ctx: dict[str, Any]) -> dict[str, Any]:
    """Drain due players from the re-arm schedule and re-poll their live queues.

    The processor feeds ``REARM_ZSET`` with every participant of a recently
    ENDED, PROCESSED match (they are provably in an Arena session). This tick
    polls the due ones; a hit re-arms at the shortest delay, consecutive misses
    back off through ``settings.rearm_delays`` until the player is dropped.
    Discovered ids go to the PRIORITY pending lane — session matches are the
    freshest content the site can show.
    """
    redis = ctx["redis"]
    try:
        if not settings.rearm_enabled:
            return {"status": "disabled"}
        if not await _check_enabled(redis, _WORKER_REARM):
            return {"status": "paused"}
        if not await _acquire_tick_lock(redis, _WORKER_REARM, 55):
            return {"status": "skip_locked"}

        now = time.time()
        raw = await redis.zrangebyscore(
            Q.REARM_ZSET, "-inf", now, start=0, num=settings.rearm_batch_size
        )
        puuids = [p.decode() if isinstance(p, bytes) else p for p in (raw or [])]
        if not puuids:
            return {"status": "ok", "due": 0}
        # Claim the batch: removed here, re-added below on hit/backoff. A crash
        # in between loses only the re-poll (the normal sweep still covers the
        # player), never a discovered match.
        await redis.zrem(Q.REARM_ZSET, *puuids)

        client = get_riot_client()
        if client is None:
            return {"status": "ok", "due": len(puuids), "discovered": 0}

        sem = asyncio.Semaphore(settings.sweep_fetch_concurrency)

        async def _poll(puuid: str) -> tuple[str, list[str]]:
            ids: list[str] = []
            for queue_id in settings.live_queue_ids:
                async with sem:
                    try:
                        ids += await client.list_match_ids(puuid, count=5, queue=queue_id)
                    except Exception:  # noqa: BLE001
                        _log.warning("rearm.list_failed", puuid=puuid[:8], queue=queue_id)
            return puuid, ids

        results = await asyncio.gather(*[_poll(p) for p in puuids])

        delays = settings.rearm_delays
        discovered = enqueued = rearmed = dropped = 0
        for puuid, ids in results:
            fresh = await _dedup_new(redis, ids) if ids else []
            eligible = [
                m for m in fresh
                if Q.evaluate_match_filters(Q.MatchMeta(riot_match_id=m)).eligible
            ]
            for mid in eligible:
                await redis.lpush(Q.SWEEP_PENDING_PRIORITY, mid)
            discovered += len(ids)
            enqueued += len(eligible)
            if eligible:
                await redis.hdel(Q.REARM_MISSES_HASH, puuid)
                await redis.zadd(Q.REARM_ZSET, {puuid: now + delays[0]})
                rearmed += 1
            else:
                misses = int(await redis.hincrby(Q.REARM_MISSES_HASH, puuid, 1))
                if misses >= settings.rearm_max_misses:
                    await redis.hdel(Q.REARM_MISSES_HASH, puuid)
                    dropped += 1
                else:
                    idx = min(misses, len(delays) - 1)
                    await redis.zadd(Q.REARM_ZSET, {puuid: now + delays[idx]})
                    rearmed += 1
        # Housekeeping: orphaned miss counters (crash between zrem and re-add)
        # must not linger forever.
        await redis.expire(Q.REARM_MISSES_HASH, 24 * 3600)

        result: dict[str, Any] = {
            "status": "ok",
            "due": len(puuids),
            "discovered": discovered,
            "enqueued": enqueued,
            "rearmed": rearmed,
            "dropped": dropped,
        }
        _log.info("rearm.tick", **result)
        return result
    except Exception as exc:  # noqa: BLE001 — never raise out of a cron tick
        _log.warning("rearm.tick.error", error=str(exc), exc_info=True)
        return {"status": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# Outage reconciliation — bounded, start_time-windowed catch-up sweep.
#
# Steady-state sweep_tick only ever asks Riot for the newest
# settings.sweep_matches_per_player ids per player, so a worker outage longer
# than that leaves a silent gap. scheduler.heartbeat_tick detects the gap on
# restart and opens Q.RECONCILE_WINDOW_KEY; reconcile_tick below is a cheap
# (two Redis reads) no-op every tick unless that window is open, in which case
# it runs ONE full, start_time-bounded pass over every tracked player and
# clears the window. Discovered ids flow into the normal standard pending list
# so filtering/dedup/processing is the exact same path as the regular sweep.
# ---------------------------------------------------------------------------


async def _reconcile_window(redis: Any) -> int | None:
    """Return the pending reconciliation "since" epoch, or None if idle."""
    raw = await redis.get(Q.RECONCILE_WINDOW_KEY)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


async def reconcile_tick(ctx: dict[str, Any]) -> dict[str, Any]:
    """Drain a pending reconciliation window (see module docstring above)."""
    redis = ctx["redis"]
    try:
        if not await _check_enabled(redis, _WORKER_RECONCILE):
            return {"status": "paused"}
        since = await _reconcile_window(redis)
        if since is None:
            return {"status": "idle"}

        # Generous TTL: a full-ladder scan can take a few sweep intervals.
        # If the process dies mid-run the window stays open (safe — Riot
        # fetch + dedup + filter are all idempotent) and retries next tick.
        ttl = max(settings.sweep_interval_minutes * 60 * 4, 600)
        if not await _acquire_tick_lock(redis, _WORKER_RECONCILE, ttl):
            return {"status": "skip_locked"}

        client = get_riot_client()
        if client is None:
            return {"status": "ok", "since": since, "reason": "riot_client_unavailable"}

        sem = asyncio.Semaphore(settings.sweep_fetch_concurrency)

        async def _fetch_one(puuid: str, queue_id: int) -> tuple[list[str], bool]:
            """Paginate one player/queue since `since`; True = the page cap was
            hit (more matches may remain — logged, not silently dropped)."""
            ids: list[str] = []
            start = 0
            hit_cap = False
            async with sem:
                for _ in range(settings.reconcile_max_pages_per_player):
                    try:
                        got = await client.list_match_ids(
                            puuid,
                            start=start,
                            count=settings.reconcile_matches_per_player,
                            queue=queue_id,
                            start_time=since,
                        )
                    except Exception:  # noqa: BLE001
                        _log.warning("reconcile.list_failed", puuid=puuid[:8], queue=queue_id)
                        break
                    if not got:
                        break
                    ids.extend(got)
                    if len(got) < settings.reconcile_matches_per_player:
                        break
                    start += settings.reconcile_matches_per_player
                else:
                    hit_cap = True
            return ids, hit_cap

        offset = 0
        players_scanned = 0
        discovered_total = 0
        enqueued_total = 0
        truncated_players = 0
        while True:
            page = await _tracked_puuids_page(offset, settings.reconcile_batch_size)
            if not page:
                break
            players_scanned += len(page)

            pairs = [(puuid, queue_id) for puuid in page for queue_id in settings.live_queue_ids]
            results = await asyncio.gather(*[_fetch_one(puuid, queue_id) for puuid, queue_id in pairs])
            page_ids: list[str] = []
            capped_puuids: set[str] = set()
            for (puuid, _queue_id), (ids, hit_cap) in zip(pairs, results):
                page_ids.extend(ids)
                if hit_cap:
                    capped_puuids.add(puuid)
            truncated_players += len(capped_puuids)
            discovered_total += len(page_ids)
            if page_ids:
                fresh = await _dedup_new(redis, page_ids)
                eligible = [
                    m for m in fresh
                    if Q.evaluate_match_filters(Q.MatchMeta(riot_match_id=m)).eligible
                ]
                for mid in eligible:
                    await redis.lpush(Q.SWEEP_PENDING_STANDARD, mid)
                enqueued_total += len(eligible)

            offset += settings.reconcile_batch_size
            if len(page) < settings.reconcile_batch_size:
                break

        await redis.delete(Q.RECONCILE_WINDOW_KEY)
        result: dict[str, Any] = {
            "status": "ok",
            "since": since,
            "windowSeconds": int(time.time()) - since,
            "playersScanned": players_scanned,
            "discovered": discovered_total,
            "enqueued": enqueued_total,
        }
        if truncated_players:
            result["truncatedPlayers"] = truncated_players
            _log.warning("reconcile.player_cap_hit", players=truncated_players, since=since)
        _log.info("reconcile.done", **result)
        return result
    except Exception as exc:  # noqa: BLE001 — never raise out of a cron tick
        _log.warning("reconcile.tick.error", error=str(exc), exc_info=True)
        return {"status": "error", "error": str(exc)}


__all__ = ["sweep_tick", "priority_sweep_tick", "rearm_tick", "reconcile_tick"]
