"""arena.workers — async background pipeline (arq + Redis).

Three cooperating roles (proposal section 6.3 + 13):

* :mod:`arena.workers.ingestion` — polls Riot for new match ids (tracked players
  + global discovery), filters by queue/participant-count/duration/eligibility,
  deduplicates via a Redis set, and enqueues onto the priority/standard streams.
  Honors pressure-mode backpressure (proposal section 11.4).
* :mod:`arena.workers.processor` — the arq consumer. One match per job,
  idempotent via the ``processed`` flag, cache-first match fetch, delegates the
  rating write to the rating service, retries up to 3× then routes to the DLQ,
  and emits ``match.processed``.
* :mod:`arena.workers.scheduler` — arq cron jobs: season transitions,
  leaderboard refresh, cache warm, and ``cr_snapshot`` continuous-aggregate
  maintenance.

:mod:`arena.workers.main` exposes the arq ``WorkerSettings`` classes the
``arq`` CLI loads (``arq arena.workers.main.StandardWorker`` etc.).

Design seams: the processor depends on a *rating service* and a *match cache /
Riot client*, and the ingestion worker depends on a *Riot client* — all of
which land in Wave 2. Until they exist the workers import them defensively (see
:mod:`arena.workers.deps`) and degrade to a clearly-logged no-op rather than
failing at import time, mirroring the codebase's import-order tolerance
(``arena.db.session``).

All log events are structured (``arena.core.logging``); operator-facing strings
stay terse English. No user-facing strings originate here.
"""

from __future__ import annotations

__all__ = [
    "queues",
    "deps",
    "ingestion",
    "processor",
    "scheduler",
    "main",
]
