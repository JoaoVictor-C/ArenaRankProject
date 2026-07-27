"""Scheduler — arq cron jobs (proposal section 13.3 + 6.3 scheduler role).

Periodic maintenance, each a thin coroutine that delegates the real work to the
Wave-2 service layer and stays import-safe before those services exist:

* :func:`season_transition` — drive ``ACTIVE→SOFT_LOCK→ENDED`` and run the new
  season's soft-reset at ``starts_at`` (proposal section 13.3). Delegates to
  ``arena.services.season_service``.
* :func:`leaderboard_refresh` — refresh the leaderboard read model and the
  Redis ``Top-1000`` set that ingestion uses for priority classification
  (proposal sections 3.4 / 13.1). Delegates to
  ``arena.services.leaderboard_service``.
* :func:`cache_warm` — pre-warm hot read caches (top players, recent matches)
  so the public API stays sub-100ms (proposal section 9.2).
* :func:`cr_snapshot_maintenance` — maintain the ``cr_snapshots`` Timescale
  continuous aggregate / compression / retention (Trinity #4, proposal
  section 8.3): refresh the aggregate window and drop/compress aged chunks.
* :func:`heartbeat_tick` — stamps a liveness timestamp every tick and, when it
  finds the PREVIOUS stamp older than ``settings.reconcile_gap_threshold_seconds``
  (i.e. this process was down or unable to tick for a while), opens a
  reconciliation window that :func:`arena.workers.sweep.reconcile_tick` picks
  up to run one bounded, time-windowed catch-up sweep. This is what lets an
  outage self-heal without an operator manually running a backfill.

The :data:`CRON_JOBS` list is consumed by :mod:`arena.workers.main`. Schedules
use arq's cron spec (``hour``/``minute``/``second`` sets, or ``second={...}``
for sub-minute cadence).
"""

from __future__ import annotations

import time
from typing import Any

from arq import cron

from arena.core.config import settings
from arena.core.logging import get_logger
from arena.workers import queues as Q

_log = get_logger("arena.workers.scheduler")


# ---------------------------------------------------------------------------
# Cron coroutines
# ---------------------------------------------------------------------------


async def season_transition(ctx: dict[str, Any]) -> dict[str, Any]:
    """Advance season lifecycle + run due soft-resets (proposal section 13.3).

    Idempotent by design: the season service only acts on seasons whose clock
    has actually crossed a boundary, so running every few minutes is safe.
    """
    try:
        from arena.services.season_service import (  # type: ignore[attr-defined]
            get_season_service,
        )
    except Exception:
        _log.info("scheduler.season_transition.skipped", reason="season_service unavailable (W2)")
        return {"status": "skipped"}

    service = get_season_service()
    result: dict[str, Any] = await service.run_transitions()
    _log.info("scheduler.season_transition.done", **result)
    return result


async def leaderboard_refresh(ctx: dict[str, Any]) -> dict[str, Any]:
    """Refresh the leaderboard read model + Redis Top-1000 set (§3.4 / §13.1).

    The Top-1000 set is the priority-classification source ingestion reads, so
    this job closes the loop between rating writes and the priority lane.
    """
    redis: Any = ctx["redis"]
    try:
        from arena.services.leaderboard_service import (  # type: ignore[attr-defined]
            get_leaderboard_service,
        )
    except Exception:
        _log.info(
            "scheduler.leaderboard_refresh.skipped",
            reason="leaderboard_service unavailable (W2)",
        )
        return {"status": "skipped"}

    service = get_leaderboard_service()
    result: dict[str, Any] = await service.refresh(redis=redis)
    _log.info("scheduler.leaderboard_refresh.done", **result)
    return result


async def cache_warm(ctx: dict[str, Any]) -> dict[str, Any]:
    """Pre-warm hot read caches so public reads stay fast (proposal §9.2)."""
    redis: Any = ctx["redis"]
    try:
        from arena.services.leaderboard_service import (  # type: ignore[attr-defined]
            get_leaderboard_service,
        )
    except Exception:
        _log.info("scheduler.cache_warm.skipped", reason="services unavailable (W2)")
        return {"status": "skipped"}

    service = get_leaderboard_service()
    warm = getattr(service, "warm_cache", None)
    if warm is None:
        return {"status": "skipped", "reason": "no warm_cache"}
    result: dict[str, Any] = await warm(redis=redis)
    _log.info("scheduler.cache_warm.done", **result)
    return result


async def cr_snapshot_maintenance(ctx: dict[str, Any]) -> dict[str, Any]:
    """Maintain the ``cr_snapshots`` continuous aggregate (Trinity #4 / §8.3).

    Refreshes the Timescale continuous aggregate over the recent window and
    applies compression/retention to aged chunks. Delegates to the season
    service's maintenance hook (it owns the snapshot schema); no-ops until W2.

    T2.3: também mantém a janela do espelho plano ``cr_snapshots_recent``
    (dual-write do RatingService): purge das linhas de temporadas que não são
    mais a corrente, para a tabela replicada não crescer para sempre.
    """
    purged = await _purge_cr_snapshots_recent()

    try:
        from arena.services.season_service import (  # type: ignore[attr-defined]
            get_season_service,
        )
    except Exception:
        _log.info(
            "scheduler.cr_snapshot_maintenance.skipped",
            reason="season_service unavailable (W2)",
            recent_purged=purged,
        )
        return {"status": "skipped", "recentPurged": purged}

    service = get_season_service()
    maintain = getattr(service, "maintain_cr_snapshots", None)
    if maintain is None:
        return {"status": "skipped", "reason": "no maintain_cr_snapshots", "recentPurged": purged}
    result: dict[str, Any] = await maintain()
    result["recentPurged"] = purged
    _log.info("scheduler.cr_snapshot_maintenance.done", **result)
    return result


async def heartbeat_tick(ctx: dict[str, Any]) -> dict[str, Any]:
    """Stamp liveness + detect an outage gap on restart (proposal §13.3 gap).

    ``run_at_startup=True`` is the whole mechanism: the tick right after a
    restart reads the heartbeat written before the process went down, compares
    it to "now", and — if the gap is wider than
    ``settings.reconcile_gap_threshold_seconds`` — opens a reconciliation
    window (``SET NX`` so an already-pending, not-yet-consumed window is never
    narrowed). The window is capped at ``reconcile_max_gap_seconds`` back from
    now; anything older is out of scope for the automatic catch-up and needs a
    manual ``scripts/backfill.py --mode refresh`` run.
    """
    redis: Any = ctx["redis"]
    now = int(time.time())
    try:
        raw = await redis.get(Q.SCHEDULER_HEARTBEAT_KEY)
        await redis.set(Q.SCHEDULER_HEARTBEAT_KEY, str(now))
    except Exception as exc:  # noqa: BLE001 — heartbeat is best-effort, never fatal
        _log.warning("scheduler.heartbeat.failed", error=str(exc))
        return {"status": "error", "error": str(exc)}

    if raw is None:
        # First tick ever (fresh Redis) — nothing to reconcile, not an outage.
        return {"status": "ok", "gap": 0}

    last = int(raw)
    gap = now - last
    if gap <= settings.reconcile_gap_threshold_seconds:
        return {"status": "ok", "gap": gap}

    since = max(last, now - settings.reconcile_max_gap_seconds)
    capped = since > last
    opened = bool(await redis.set(Q.RECONCILE_WINDOW_KEY, str(since), nx=True))
    _log.warning(
        "scheduler.gap_detected",
        gapSeconds=gap,
        since=since,
        capped=capped,
        windowOpened=opened,
    )
    return {"status": "ok", "gap": gap, "since": since, "capped": capped, "windowOpened": opened}


async def _purge_cr_snapshots_recent() -> int:
    """Delete ``cr_snapshots_recent`` rows outside the current-season window.

    "Corrente" = temporada de ``starts_at`` mais recente (mesma resolução do
    read path). Best-effort: DB fora do ar loga e devolve 0 — o cron tenta de
    novo na próxima hora. Roda no PRIMÁRIO (o purge replica para a réplica).
    """
    try:
        from typing import Any, cast

        from sqlalchemy import delete, select
        from sqlalchemy.engine import CursorResult

        from arena.db import models as m
        from arena.db.session import get_sessionmaker

        async with get_sessionmaker()() as session:
            current = (
                select(m.Season.id).order_by(m.Season.starts_at.desc()).limit(1)
            ).scalar_subquery()
            result = await session.execute(
                delete(m.CrSnapshotRecent).where(m.CrSnapshotRecent.season_id != current)
            )
            await session.commit()
            purged = int(cast(CursorResult[Any], result).rowcount or 0)
            if purged:
                _log.info("scheduler.cr_snapshots_recent.purged", rows=purged)
            return purged
    except Exception:
        _log.warning("scheduler.cr_snapshots_recent.purge_failed", exc_info=True)
        return 0


# ---------------------------------------------------------------------------
# Cron schedule registry (consumed by main.SchedulerWorker)
# ---------------------------------------------------------------------------

#: arq CronJob specs. ``run_at_startup`` is off for transitions (avoid acting on
#: a half-warm process) but on for the maintenance jobs so a fresh deploy warms
#: caches / the Top-1000 set immediately.
CRON_JOBS = [
    # Season lifecycle — every 5 minutes.
    cron(season_transition, minute=set(range(0, 60, 5)), run_at_startup=False),
    # Leaderboard + Top-1000 set — every minute (priority-lane SLA, §3.4).
    cron(leaderboard_refresh, minute=set(range(0, 60)), run_at_startup=True),
    # Cache warm — every 5 minutes, offset from the transition tick.
    cron(cache_warm, minute=set(range(2, 60, 5)), run_at_startup=True),
    # cr_snapshot continuous-aggregate maintenance — hourly at :07.
    cron(cr_snapshot_maintenance, minute={7}, run_at_startup=False),
    # Outage-gap heartbeat — every minute, AND at startup so a restart detects
    # the gap immediately instead of waiting up to a minute.
    cron(heartbeat_tick, minute=set(range(0, 60)), run_at_startup=True),
]


__all__ = [
    "season_transition",
    "leaderboard_refresh",
    "cache_warm",
    "cr_snapshot_maintenance",
    "heartbeat_tick",
    "CRON_JOBS",
]
