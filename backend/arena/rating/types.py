"""Engine contracts — ports the slice-1 TypeScript interfaces (spec section 6)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .params import RatingParams


@dataclass(slots=True)
class PlayerState:
    """Persisted per player-season (mirrors player_seasons columns)."""

    player_id: str
    mu: float
    sigma: float
    cr: float  # materialized to_cr(mu, sigma)
    current_streak: int  # + wins / - losses
    matches_played: int
    placement_matches_remaining: int
    peak_cr: float


@dataclass(slots=True)
class ParticipantInput:
    player_id: str
    state: PlayerState
    champion_id: int
    eligible_for_progression: bool
    is_premade: bool = False
    party_id: str | None = None
    boosting_penalty_factor: float = 0.0  # 0..1, from the integrity layer (upstream)
    party_penalty_factor: float = 0.0  # 0..1, premade dampener (gains-only); from integrity


@dataclass(slots=True)
class TeamInput:
    team_id: int
    placement: int  # 1..T (1 = best); ties allowed
    participants: list[ParticipantInput]


@dataclass(slots=True)
class MatchInput:
    match_id: str
    mode: str  # 'DUOS' | 'TRIOS'
    teams: list[TeamInput]
    params: RatingParams


@dataclass(slots=True)
class AppliedModifiers:
    pl_base_delta_mu: float
    placement_weight: float
    placement_amp: float
    streak_mult: float
    soft_cap_factor: float
    boosting_factor: float
    party_factor: float
    dispersion_clamped: bool
    final_delta_mu: float


@dataclass(slots=True)
class PlayerRatingResult:
    player_id: str
    mu_before: float
    mu_after: float
    sigma_before: float
    sigma_after: float
    cr_before: float
    cr_after: float
    cr_delta: float
    eligible: bool
    is_win: bool
    new_streak: int
    modifiers: AppliedModifiers


@dataclass(slots=True)
class RatingResult:
    match_id: str
    voided: bool
    players: list[PlayerRatingResult] = field(default_factory=list)
