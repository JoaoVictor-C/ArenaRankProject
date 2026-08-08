"""arq ``WorkerSettings`` entrypoints — one per worker pool.

Run with the arq CLI, each pool scaled independently in Kubernetes
(proposal section 6.3 "separate resource allocation"):

    arq arena.workers.main.PriorityWorker    # priority-lane consumers
    arq arena.workers.main.StandardWorker     # standard-lane consumers
    arq arena.workers.main.IngestionWorker    # Riot poller (single-ish)
    arq arena.workers.main.SchedulerWorker     # cron: season/leaderboard/cache/snapshots

All four share the same Redis (``settings.redis_url``) and call
:func:`arena.core.logging.configure_logging` on startup so worker logs match the
API's structured-JSON shape.

The two consumer pools differ only by the arq ``queue_name`` they subscribe to,
so the priority pool can be given more replicas / resources without the standard
backlog starving it (proposal section 13.1 priority lane).
"""

from __future__ import annotations

from typing import Any

from arq import cron

from arena.core.config import settings
from arena.core.logging import configure_logging, get_logger
from arena.workers import queues as Q
from arena.workers.backfill import backfill_tick
from arena.workers.deps import redis_settings
from arena.workers.ingestion import poll_riot
from arena.workers.processor import MAX_TRIES, process_match
from arena.workers.scheduler import CRON_JOBS
from arena.workers.sweep import (
    priority_sweep_tick,
    reconcile_tick,
    rearm_tick,
    recent_activity_sweep_tick,
    sweep_tick,
)

_log = get_logger("arena.workers.main")


async def _on_startup(ctx: dict[str, Any]) -> None:
    """Shared worker startup: structured logging + a startup log line."""
    configure_logging(log_level=settings.log_level, service_name=settings.service_name)
    role = ctx.get("_role", "worker")
    _log.info("worker.startup", role=role, env=settings.environment)


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    role = ctx.get("_role", "worker")
    _log.info("worker.shutdown", role=role)


# ---------------------------------------------------------------------------
# Consumer pools (priority + standard) — same task set, different queue.
# ---------------------------------------------------------------------------


class _BaseConsumerSettings:
    """Shared arq settings for the match-processing consumers."""

    functions = [process_match]
    redis_settings = redis_settings()
    max_tries = MAX_TRIES
    # Internal retry/DLQ is handled in-task; keep arq from retrying past our cap.
    retry_jobs = True
    job_timeout = 60  # seconds; the rating write is fast but DB-bound
    max_jobs = 10
    health_check_interval = 30
    on_startup = staticmethod(_on_startup)
    on_shutdown = staticmethod(_on_shutdown)


def _flatten(cls: type) -> type:
    """Copy inherited WorkerSettings attributes onto the leaf class __dict__.

    arq 0.28's ``get_kwargs`` reads settings from ``settings_cls.__dict__`` — only
    the class's OWN attributes, NOT inherited ones. A consumer that merely
    subclasses :class:`_BaseConsumerSettings` and sets ``queue_name`` would lose
    ``functions``/``redis_settings``/hooks, and arq raises "at least one function
    or cron_job must be registered". Flattening the base attrs into the leaf
    __dict__ keeps the shared-config base while satisfying arq's lookup.
    """
    for base in cls.__mro__[1:]:
        for key, value in base.__dict__.items():
            if not key.startswith("__") and key not in cls.__dict__:
                setattr(cls, key, value)
    return cls


@_flatten
class PriorityWorker(_BaseConsumerSettings):
    """Consumes the priority lane (Top-1000 involved; sub-5-min SLA, §3.4)."""

    queue_name = Q.PRIORITY_QUEUE
    # More headroom than standard so priority never queues behind the backlog.
    max_jobs = 20


@_flatten
class StandardWorker(_BaseConsumerSettings):
    """Consumes the standard lane (the bulk of traffic)."""

    queue_name = Q.STANDARD_QUEUE


# ---------------------------------------------------------------------------
# Ingestion — its own pool; the poll tick is a startup cron on a fixed cadence.
# ---------------------------------------------------------------------------


class IngestionWorker:
    """Polls Riot for new match ids and enqueues them (proposal §13.1).

    The poll is modeled as an arq cron firing every 60 seconds (proposal §6.3
    "configurable polling interval"). Keep this pool small (1–2 replicas): the
    Redis ``seen_matches`` dedup + per-job ``_job_id`` make concurrent ticks
    safe, but a single ticker is the common case.
    """

    queue_name = "arena:cron:ingestion"
    functions: list[Any] = []
    cron_jobs = [cron(poll_riot, second={0}, run_at_startup=True)]
    redis_settings = redis_settings()
    on_startup = staticmethod(_on_startup)
    on_shutdown = staticmethod(_on_shutdown)
    health_check_interval = 30


# ---------------------------------------------------------------------------
# Scheduler — cron-only pool (season/leaderboard/cache/snapshot maintenance).
# ---------------------------------------------------------------------------


class SchedulerWorker:
    """Runs the maintenance cron jobs (proposal §13.3). Single replica."""

    queue_name = "arena:cron:scheduler"
    functions: list[Any] = []
    cron_jobs = CRON_JOBS
    redis_settings = redis_settings()
    on_startup = staticmethod(_on_startup)
    on_shutdown = staticmethod(_on_shutdown)
    health_check_interval = 30


# ---------------------------------------------------------------------------
# Sweep pools (cron-driven discovery; each toggled via Redis enable flag and
# independently start/stoppable as its own docker-compose service). They
# enqueue discovered match ids straight onto the arq queues above — processing
# is PriorityWorker/StandardWorker's job, not the sweep's; there is no separate
# drain step. Intervals come from settings (env); each value must divide 60.
# ---------------------------------------------------------------------------


class SweepWorker:
    """Rotating sweep over ALL tracked players → the standard arq queue.

    Also hosts the session re-arm tick (every minute): quick re-polls of
    players whose match was just processed, feeding the priority queue; the
    outage-reconciliation tick (every minute, no-op unless SchedulerWorker's
    heartbeat_tick flagged a gap), which runs one bounded catch-up sweep after
    a restart instead of requiring a manual backfill; and the new-player
    backfill tick, which imports the history of accounts the write path has just
    seen for the first time.
    """

    # Own queue so its cron jobs don't collide with the other cron workers
    # (a shared queue makes a worker pick up jobs whose function it lacks).
    queue_name = "arena:cron:sweep"
    functions: list[Any] = []
    cron_jobs = [
        cron(
            sweep_tick,
            minute=set(range(0, 60, settings.sweep_interval_minutes)),
            run_at_startup=True,
        ),
        cron(
            rearm_tick,
            minute=set(range(60)),
            run_at_startup=False,
        ),
        # Outage catch-up: cheap no-op every tick unless scheduler.heartbeat_tick
        # has flagged a gap; run_at_startup so a restart is caught immediately.
        cron(
            reconcile_tick,
            minute=set(range(60)),
            run_at_startup=True,
        ),
        # New-player history import. Drains its own pending list, so a tick with
        # nothing queued is two cheap Redis reads.
        cron(
            backfill_tick,
            minute=set(range(0, 60, settings.backfill_interval_minutes)),
            run_at_startup=True,
        ),
    ]
    redis_settings = redis_settings()
    on_startup = staticmethod(_on_startup)
    on_shutdown = staticmethod(_on_shutdown)
    health_check_interval = 30


class PrioritySweepWorker:
    """Sweep over Top-1000 + admin-selected players → the priority arq queue.

    Also hosts the recent-activity sweep tick: a CR-independent "played a
    match in the last few hours" re-check that closes the coverage gap
    rearm_tick's short leash + the standard sweep's (very slow, full-pool)
    rotation leave for non-priority players — see
    ``Settings.recent_activity_enabled``'s docstring.
    """

    queue_name = "arena:cron:priority_sweep"
    functions: list[Any] = []
    cron_jobs = [
        cron(
            priority_sweep_tick,
            minute=set(range(0, 60, settings.priority_sweep_interval_minutes)),
            run_at_startup=True,
        ),
        cron(
            recent_activity_sweep_tick,
            minute=set(range(0, 60, settings.recent_activity_sweep_interval_minutes)),
            run_at_startup=True,
        ),
    ]
    redis_settings = redis_settings()
    on_startup = staticmethod(_on_startup)
    on_shutdown = staticmethod(_on_shutdown)
    health_check_interval = 30


__all__ = [
    "PriorityWorker",
    "StandardWorker",
    "IngestionWorker",
    "SchedulerWorker",
    "SweepWorker",
    "PrioritySweepWorker",
]
