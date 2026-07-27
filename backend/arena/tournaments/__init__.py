"""Tournaments subsystem — persisted (contract §5) + onboarding/admin + scoring.

First-class persisted subsystem over the normalized schema (``tournaments`` /
``tournament_teams`` / ``tournament_matches``). The scoring source of truth is the
pure :func:`~arena.tournaments.scoring.compute_standings`; standings are recomputed
on every result submission. Read paths return an honest empty state / 404 when
nothing is provisioned yet — no DTO-sample fallback (tournaments are
operator-created and must never be presented as real events).

Public surface:

* :class:`~arena.tournaments.service.TournamentService` — application use cases.
* :data:`~arena.tournaments.router.router` — FastAPI router (mount under ``/api/v1``).
* :func:`~arena.tournaments.scoring.compute_standings` — pure scoring engine.

ToS/contract: tournaments are points-based (``total``/``perMatch``); never expose
mu/sigma. User-facing strings PT-BR; JSON wire keys camelCase (DTO layer).
"""

from __future__ import annotations

from arena.tournaments.scoring import (
    BRAVURA_CAP,
    MatchResult,
    TeamStanding,
    compute_standings,
)
from arena.tournaments.service import TournamentService

__all__ = [
    "TournamentService",
    "compute_standings",
    "MatchResult",
    "TeamStanding",
    "BRAVURA_CAP",
]
