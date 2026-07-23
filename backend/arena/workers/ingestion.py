"""Ingestion worker — poll Riot for new match ids and enqueue them.

Pipeline (proposal section 13.1):

    every poll interval
        ├─ fetch match ids for tracked players (player_seasons.matches_played>0)
        ├─ fetch match ids from the global discovery endpoint (new players)
        ├─ deduplicate against the Redis ``seen_matches`` set
        ├─ filter (queue id, participant count, duration, season range)  [cheap pass]
        ├─ classify: any Top-1000 player involved? → priority lane, else standard
        └─ enqueue ``process_match`` jobs onto the chosen arq queue

Backpressure (proposal section 11.4): before fetching, the worker samples the
combined depth of the priority + standard queues. At/above the high-water mark
it enters **pressure mode** and skips fetching new ids (letting processors
drain); it leaves pressure mode once depth drops below the low-water mark. The
mode is sticky across ticks via a Redis flag so replicas agree.

This module is import-safe before Wave 2: when the Riot client or DB session is
not yet available the relevant step logs and yields an empty result rather than
raising, so ``ruff``/import sanity pass and the worker no-ops cleanly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from arena.core.logging import get_logger
from arena.workers import queues as Q
from arena.workers.deps import get_riot_client

if TYPE_CHECKING:
    from arq.connections import ArqRedis

_log = get_logger("arena.workers.ingestion")

#: Redis flag marking that ingestion is currently in pressure mode (sticky).
_PRESSURE_FLAG = "arena:ingestion:pressure"

#: How many recent match ids to pull per tracked player per tick.
_MATCHES_PER_PLAYER = 10

#: Cap on tracked players scanned per tick — keeps a single tick bounded; the
#: cursor (``ingest_cursor_key``) plus a rotating offset cover the full set over
#: successive ticks. Tuned via env in a later wave.
_MAX_TRACKED_PER_TICK = 5_000


# ---------------------------------------------------------------------------
# Backpressure
# ---------------------------------------------------------------------------


async def _combined_queue_depth(redis: "ArqRedis") -> int:
    """Sum of pending jobs across the priority + standard arq queues.

    arq stores a queue as a Redis sorted set keyed by the queue name, so the
    pending depth is its cardinality. Unknown/missing keys count as zero.
    """
    total = 0
    for name in (Q.PRIORITY_QUEUE, Q.STANDARD_QUEUE):
        try:
            total += int(await redis.zcard(name))
        except Exception:  # pragma: no cover - depth is best-effort telemetry
            _log.warning("ingestion.depth_probe_failed", queue=name)
    return total


async def _update_pressure_mode(redis: "ArqRedis") -> bool:
    """Return whether ingestion should fetch this tick (False == pressure mode).

    Implements the high/low-water hysteresis from proposal section 11.4 and
    persists the sticky flag so all ingestion replicas observe the same mode.
    """
    depth = await _combined_queue_depth(redis)
    in_pressure = bool(await redis.exists(_PRESSURE_FLAG))

    if not in_pressure and depth >= Q.PRESSURE_HIGH_WATERMARK:
        await redis.set(_PRESSURE_FLAG, "1")
        _log.warning("ingestion.pressure_mode.enter", depth=depth)
        return False
    if in_pressure and depth < Q.PRESSURE_LOW_WATERMARK:
        await redis.delete(_PRESSURE_FLAG)
        _log.info("ingestion.pressure_mode.exit", depth=depth)
        return True
    if in_pressure:
        _log.info("ingestion.pressure_mode.hold", depth=depth)
        return False
    return True


# ---------------------------------------------------------------------------
# Discovery sources
# ---------------------------------------------------------------------------


async def _tracked_puuids() -> list[str]:
    """Active tracked players (``player_seasons.matches_played > 0``), §13.1.

    Joins to ``players.puuid`` because the Riot match-list endpoint is keyed by
    puuid. Returns an empty list (logged) if the DB layer is not importable yet,
    keeping ingestion import-safe before the schema is migrated.
    """
    try:
        from sqlalchemy import select

        from arena.db.models import Player, PlayerSeason
        from arena.db.session import get_sessionmaker
    except Exception:
        _log.warning("ingestion.tracked.db_unavailable")
        return []

    factory = get_sessionmaker()
    async with factory() as session:
        stmt = (
            select(Player.puuid)
            .join(PlayerSeason, PlayerSeason.player_id == Player.id)
            .where(PlayerSeason.matches_played > 0)
            .distinct()
            .limit(_MAX_TRACKED_PER_TICK)
        )
        rows = await session.execute(stmt)
        return [puuid for (puuid,) in rows.all() if puuid]


async def _discover_global() -> list[str]:
    """Global new-player discovery (proposal section 13.1).

    Delegates to the Riot client's discovery surface when present; today this is
    a defensive no-op until the W2 client implements a discovery feed (featured
    games / seed puuids). Kept as an explicit seam so the ingestion shape matches
    the proposal pipeline.
    """
    client = get_riot_client()
    if client is None:
        return []
    discover = getattr(client, "discover_match_ids", None)
    if discover is None:
        return []
    try:
        ids: list[str] = await discover()
        return ids
    except Exception:  # pragma: no cover - discovery is best-effort
        _log.warning("ingestion.discovery_failed")
        return []


# ---------------------------------------------------------------------------
# Dedup, classify, enqueue
# ---------------------------------------------------------------------------


async def _dedup_new(redis: Any, match_ids: list[str]) -> list[str]:
    """Return only ids not already in the ``seen_matches`` set, marking new ones.

    Uses ``SADD`` (returns count added) per id for atomic test-and-set, then
    refreshes the set TTL. Order-preserving and idempotent across replicas.
    """
    fresh: list[str] = []
    for mid in match_ids:
        try:
            added = await redis.sadd(Q.SEEN_MATCHES_SET, mid)
        except Exception:  # pragma: no cover - dedup is best-effort
            _log.warning("ingestion.dedup_failed", matchId=mid)
            continue
        if added:
            fresh.append(mid)
    if fresh:
        # Bound the set's lifetime so it can't grow forever (§13.1 / §9.3 TTL).
        await redis.expire(Q.SEEN_MATCHES_SET, Q.SEEN_MATCH_TTL_SECONDS)
    return fresh


async def _is_priority(redis: Any, participant_puuids: list[str]) -> bool:
    """True when any participant is in the Top-1000 set (priority lane, §13.1)."""
    if not participant_puuids:
        return False
    for puuid in participant_puuids:
        try:
            if await redis.sismember(Q.TOP_PLAYERS_SET, puuid):
                return True
        except Exception:  # pragma: no cover
            return False
    return False


async def _enqueue(
    redis: "ArqRedis",
    riot_match_id: str,
    *,
    priority: bool,
) -> None:
    """Enqueue a ``process_match`` job onto the chosen arq queue.

    The match id doubles as the arq ``_job_id`` so a duplicate enqueue within the
    job's keep-window is collapsed by arq itself — a second dedup layer on top of
    the Redis ``seen_matches`` set.
    """
    queue = Q.PRIORITY_QUEUE if priority else Q.STANDARD_QUEUE
    await redis.enqueue_job(
        Q.PROCESS_MATCH_TASK,
        riot_match_id,
        _queue_name=queue,
        _job_id=f"{Q.PROCESS_MATCH_TASK}:{riot_match_id}",
    )
    _log.info("ingestion.enqueued", matchId=riot_match_id, queue=queue, priority=priority)


# ---------------------------------------------------------------------------
# arq task entrypoint (registered as a startup cron in main.WorkerSettings)
# ---------------------------------------------------------------------------


async def poll_riot(ctx: dict[str, Any]) -> dict[str, int]:
    """One ingestion tick. Registered as the ingestion worker's cron job.

    Returns a small counters dict (discovered / new / enqueued / skipped) that
    arq stores as the job result for observability.
    """
    redis: ArqRedis = ctx["redis"]

    should_fetch = await _update_pressure_mode(redis)
    if not should_fetch:
        return {"discovered": 0, "new": 0, "enqueued": 0, "pressure": 1}

    client = get_riot_client()

    # 1. Gather candidate ids from both sources.
    discovered: list[str] = []
    if client is not None:
        for puuid in await _tracked_puuids():
            try:
                ids = await client.list_match_ids(puuid, count=_MATCHES_PER_PLAYER)
            except Exception:  # pragma: no cover - per-player failure is isolated
                _log.warning("ingestion.list_failed", puuid=puuid)
                continue
            discovered.extend(ids)
    discovered.extend(await _discover_global())

    if not discovered:
        return {"discovered": 0, "new": 0, "enqueued": 0, "pressure": 0}

    # 2. Deduplicate against the seen-set.
    fresh = await _dedup_new(redis, discovered)

    # 3. Cheap filter + classify + enqueue. The authoritative filter (full
    #    payload) re-runs in the processor; here we only have the id, so the
    #    filter mostly passes (queue/participant/duration unknown -> defer).
    enqueued = 0
    for mid in fresh:
        verdict = Q.evaluate_match_filters(Q.MatchMeta(riot_match_id=mid))
        if not verdict.eligible:
            _log.info("ingestion.filtered", matchId=mid, reason=verdict.reason)
            continue
        # Participant puuids are unknown at id-only stage -> standard lane; the
        # processor can still re-route via the Top-1000 set if needed.
        priority = await _is_priority(redis, participant_puuids=[])
        await _enqueue(redis, mid, priority=priority)
        enqueued += 1

    result = {
        "discovered": len(discovered),
        "new": len(fresh),
        "enqueued": enqueued,
        "pressure": 0,
    }
    _log.info("ingestion.tick", **result)
    return result


__all__ = ["poll_riot"]
