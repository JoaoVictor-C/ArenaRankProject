"""Cross-service dependency contracts (typing Protocols).

The domain services in this package orchestrate three collaborators:

* the rating engine            -> :mod:`arena.rating` (already ported, imported directly)
* the persistence layer        -> :mod:`arena.db` models + an async session
* the integrity / anti-abuse   -> :mod:`arena.integrity` (sibling wave W2)

To keep ``arena.services`` importable and type-checkable *before* the
``arena.integrity`` package lands — and to keep the services unit-testable with
fakes — we depend on **structural** Protocols here rather than on concrete
sibling-module classes. The W2 integrity module only has to provide an object
whose ``evaluate`` is shape-compatible with :class:`IntegrityEvaluator`; no
import-time coupling is created.

Nothing here is user-facing; English docs are fine. User-facing strings live in
the individual services and are PT-BR per the contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from arena.rating import PlayerState

# ---------------------------------------------------------------------------
# Integrity layer contract (proposal §3.2). The integrity service inspects a
# raw match and emits zero or more flags + per-player boosting factors that
# feed the rating engine's modifier pipeline (``boosting_penalty_factor`` and
# ``eligible_for_progression`` on ParticipantInput).
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class IntegrityFlag:
    """One emitted integrity signal (becomes an ``integrity_events`` row).

    ``flag_type`` is a stable machine code (e.g. ``"RDS_BOOSTING"``,
    ``"REPEATED_LOBBY"``, ``"DURATION_OUTLIER"``, ``"AFK"``). ``severity`` is
    one of ``"INFO" | "WARN" | "CRITICAL"`` (matches the PG ``severity`` enum).
    ``player_id`` is ``None`` for match-scoped flags (e.g. repeated lobby).
    """

    flag_type: str
    severity: str
    player_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class IntegrityVerdict:
    """Result of evaluating a whole match.

    * ``flags``               — every emitted :class:`IntegrityFlag`.
    * ``boosting_factors``    — per ``player_id`` boosting penalty in ``[0, 1]``
      (0 = clean). Fed verbatim into ``ParticipantInput.boosting_penalty_factor``.
    * ``ineligible_player_ids`` — players the engine must freeze (AFK / ineligible).
    """

    flags: list[IntegrityFlag] = field(default_factory=list)
    boosting_factors: dict[str, float] = field(default_factory=dict)
    ineligible_player_ids: set[str] = field(default_factory=set)
    party_factors: dict[str, float] = field(default_factory=dict)

    def boosting_for(self, player_id: str) -> float:
        return self.boosting_factors.get(player_id, 0.0)

    def party_for(self, player_id: str) -> float:
        return self.party_factors.get(player_id, 0.0)

    def is_eligible(self, player_id: str) -> bool:
        return player_id not in self.ineligible_player_ids


@runtime_checkable
class IntegrityEvaluator(Protocol):
    """Shape the W2 ``arena.integrity`` service must satisfy.

    The rating service calls ``evaluate`` *before* building the engine input so
    boosting factors and AFK eligibility can be wired into the modifier
    pipeline (proposal §13.2 step "Run IntegrityService.evaluate").

    ``states`` carries each player's pre-match rating snapshot (CR-bearing),
    needed by signals like the premade dampener that compare intra-party skill.
    It is optional so eligibility-only evaluators ignore it.
    """

    async def evaluate(
        self, match: RawMatch, states: "Mapping[str, PlayerState] | None" = None
    ) -> IntegrityVerdict: ...


# ---------------------------------------------------------------------------
# Raw match shape handed to the pipeline (post-ingestion, pre-rating). This is
# the normalized form the ingestion worker produces from the Riot payload; the
# rating service turns it into a rating-engine ``MatchInput``.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RawParticipant:
    player_id: str
    champion_id: int
    team_id: int
    placement: int
    is_premade: bool = False
    party_id: str | None = None


@dataclass(slots=True)
class RawMatch:
    """Normalized match handed to :class:`RatingService.process_match`."""

    match_id: str  # internal matches.id (uuid str)
    riot_match_id: str
    season_id: str
    mode: str  # "DUOS" | "TRIOS"
    queue_id: int
    played_at: str  # ISO-8601
    participants: list[RawParticipant] = field(default_factory=list)
    duration_seconds: int | None = None


# ---------------------------------------------------------------------------
# Distributed-lock contract. The concrete implementation is the Redis
# per-player lock (see :mod:`arena.services.locks`); tests can pass a no-op.
# ---------------------------------------------------------------------------


class AsyncLock(Protocol):
    async def __aenter__(self) -> object: ...
    async def __aexit__(self, *exc: object) -> bool | None: ...


__all__ = [
    "IntegrityFlag",
    "IntegrityVerdict",
    "IntegrityEvaluator",
    "RawParticipant",
    "RawMatch",
    "AsyncLock",
]
