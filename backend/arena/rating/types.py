"""Engine contracts — ports the slice-1 TypeScript interfaces (spec section 6)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .caps import CapBound
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
class CapExplanation:
    """What the CR-space (PDL) cap layer did for one player, for the Raio-X
    transparency explanation (``arena/rating/explain.py``). All fields are CR/PDL
    space except ``lobby_mean_mu``, which is engine-internal and MUST NOT cross the
    API boundary (see ``arena/schemas/common.py``'s never-expose-mu/sigma rule) —
    it exists here only so ``explain()`` can recompute the cap facts for a fresh
    result without re-deriving the lobby mean from ``state_before`` a second time.
    """

    active: bool
    bound: CapBound
    raw_cr_delta: float
    capped_cr_delta: float
    lo: float
    hi: float
    min_gain: float
    mismatch_override: float
    high_cr_scale: float
    composite_win: float
    composite_loss: float
    gain_floor_mult: float
    team_count: int
    lobby_mean_mu: float


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
    # CR-space facts for the Raio-X explanation — additive, always sum with the
    # modifier chain's scaled contribution to reconcile exactly to cr_delta. None/0.0
    # for ineligible (frozen) players, since cr_delta is 0.0 and nothing moved.
    cap: CapExplanation | None = None
    confidence_cr: float = 0.0  # -3 * (sigma_after - sigma_before) * scale_factor
    pre_cap_cr_delta: float = 0.0  # cr_after - cr_before BEFORE the cap layer ran
    # Persisted unconditionally (even when caps=None disables the cap layer, and
    # for frozen/ineligible players) so a read-time reconstruction never needs an
    # extra query just to learn how many teams a match had.
    team_count: int = 0


@dataclass(slots=True)
class RatingResult:
    match_id: str
    voided: bool
    players: list[PlayerRatingResult] = field(default_factory=list)
