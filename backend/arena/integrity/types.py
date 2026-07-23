"""Integrity-layer contracts (proposal §3.2 + §13.2).

These dataclasses are worker-side, NOT API-for-UI: they may carry mu/sigma
because they feed the rating engine and the admin integrity queue, never the
public UI. The public surface only ever sees CR/Pontos (see ``arena.schemas``).

The layer is a *pure scoring function*: ``evaluate(match)`` reads a match
snapshot and produces
  * zero or more :class:`IntegrityFlag` objects (audit log → ``integrity_events``);
  * per-participant ``boosting_penalty_factor`` (0..1) and
    ``eligible_for_progression`` (bool),
both of which the rating engine consumes via ``arena.rating.ParticipantInput``.
It NEVER mutates the match snapshot it is given.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FlagSeverity(str, Enum):
    """Mirrors ``arena.db.models.Severity`` (stored UPPER in the PG enum)."""

    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


class FlagType(str, Enum):
    """Canonical ``flag_type`` values (fit ``integrity_events.flag_type`` VARCHAR(32))."""

    BOOSTING_RDS = "boosting_rds"
    AFK_INELIGIBLE = "afk_ineligible"
    REPEATED_LOBBY = "repeated_lobby"
    UNUSUAL_DURATION = "unusual_duration"
    RATING_DISPERSION = "rating_dispersion"


@dataclass(slots=True)
class IntegrityFlag:
    """Structured, immutable observation about a match (or a participant in it).

    Persisted 1:1 to ``integrity_events`` (``player_id`` ``None`` ⇒ match-level).
    ``metadata`` is a JSON-serializable dict; keep keys snake_case (worker-side).
    """

    flag_type: FlagType
    severity: FlagSeverity
    metadata: dict[str, object] = field(default_factory=dict)
    player_id: str | None = None  # None => match-scoped flag


@dataclass(slots=True)
class ParticipantSnapshot:
    """Read-only view of one participant as seen by the integrity layer.

    A subset/superset of ``rating.ParticipantInput`` inputs: carries the signals
    integrity needs (party grouping, AFK telemetry, current rating) without
    importing the rating engine. ``mu``/``sigma``/``cr`` are pre-match values.
    """

    player_id: str
    team_id: int
    champion_id: int
    party_id: str | None = None
    # AFK / participation telemetry from the match payload.
    afk: bool = False
    rounds_played: int = 0
    rounds_total: int = 0
    damage_dealt: int = 0
    # Pre-match rating snapshot (worker-side only — never surfaced to UI).
    mu: float = 0.0
    sigma: float = 0.0
    cr: float = 0.0
    # Matches played this season (provisional accounts climb faster ⇒ less suspect).
    matches_played: int = 0


@dataclass(slots=True)
class MatchSnapshot:
    """Read-only match payload handed to :func:`arena.integrity.evaluate`."""

    match_id: str
    mode: str  # 'DUOS' | 'TRIOS'
    team_size: int  # players per team (2 for duos, 3 for trios)
    duration_seconds: int
    participants: list[ParticipantSnapshot]


@dataclass(slots=True)
class ParticipantVerdict:
    """Per-participant integrity outputs the rating engine consumes."""

    player_id: str
    boosting_penalty_factor: float  # 0..1 → rating.ParticipantInput.boosting_penalty_factor
    eligible_for_progression: bool  # → rating.ParticipantInput.eligible_for_progression
    party_penalty_factor: float = 0.0  # 0..1 → rating.ParticipantInput.party_penalty_factor


@dataclass(slots=True)
class EvaluationResult:
    """Full output of :func:`arena.integrity.evaluate`.

    ``flags`` → audit log; ``verdicts`` → rating-engine inputs (keyed by player).
    Pure data — the caller owns persistence and enforcement.
    """

    match_id: str
    flags: list[IntegrityFlag] = field(default_factory=list)
    verdicts: dict[str, ParticipantVerdict] = field(default_factory=dict)

    def verdict_for(self, player_id: str) -> ParticipantVerdict:
        return self.verdicts[player_id]
