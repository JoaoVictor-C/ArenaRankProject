"""Domain services — orchestration over rating engine, DB, and integrity.

These are the application-layer use cases that sit between the API/workers and
the lower layers:

* :class:`~arena.services.rating_service.RatingService`
      Process one match end-to-end (integrity -> rate -> persist in one tx under
      a per-player Redis lock; idempotent on ``matches.processed``).
* :class:`~arena.services.stats_service.StatsService`
      Champion stats, head-to-head, and streak read models for profiles.
* :class:`~arena.services.season_service.SeasonService`
      Season lifecycle state machine, soft-reset, and Top 1/10/50/100/500
      achievements.
* :class:`~arena.services.leaderboard_service.LeaderboardService`
      Redis read-through with Postgres fallback (Trinity #6 — not a 30s MV).

Supporting modules: :mod:`arena.services.protocols` (DI contracts incl. the
integrity evaluator) and :mod:`arena.services.locks` (per-player Redis lock).

ToS/contract reminders honored by every service: never surface mu/sigma or
augment/item winrate; rank/display by CR/Pontos; user-facing strings are PT-BR;
JSON contract keys are camelCased in the API layer, not here.
"""

from __future__ import annotations

from arena.services.leaderboard_service import (
    LeaderboardEntry,
    LeaderboardPage,
    LeaderboardService,
)
from arena.services.locks import LockAcquireTimeout, RedisLockManager
from arena.services.protocols import (
    AsyncLock,
    IntegrityEvaluator,
    IntegrityFlag,
    IntegrityVerdict,
    RawMatch,
    RawParticipant,
)
from arena.services.rating_service import ProcessOutcome, RatingService
from arena.services.season_service import (
    CloseSeasonResult,
    SeasonService,
    SeasonTransitionError,
    SoftResetResult,
)
from arena.services.stats_service import (
    ChampionStatView,
    HeadToHeadView,
    OtpView,
    StatsService,
    StreakView,
    WinLossView,
)

__all__ = [
    # rating
    "RatingService",
    "ProcessOutcome",
    # stats
    "StatsService",
    "ChampionStatView",
    "HeadToHeadView",
    "StreakView",
    "WinLossView",
    "OtpView",
    # season
    "SeasonService",
    "SeasonTransitionError",
    "CloseSeasonResult",
    "SoftResetResult",
    # leaderboard
    "LeaderboardService",
    "LeaderboardEntry",
    "LeaderboardPage",
    # locks
    "RedisLockManager",
    "LockAcquireTimeout",
    # protocols / DI contracts
    "AsyncLock",
    "IntegrityEvaluator",
    "IntegrityFlag",
    "IntegrityVerdict",
    "RawMatch",
    "RawParticipant",
]
