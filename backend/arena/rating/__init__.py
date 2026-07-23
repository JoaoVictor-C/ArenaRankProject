"""Gamified CRS rating engine (Plackett-Luce base + modifier pipeline + CR display).

Public API:
    rate(match) -> RatingResult            # process one match
    to_cr(mu, sigma, params) -> float      # conservative CR display
    soft_reset(state, params) -> PlayerState
    DEFAULT_PARAMS, RatingParams, validate_params
    + the dataclass contracts and individual modifier functions
"""

from __future__ import annotations

from .engine import rate
from .modifiers import (
    boosting_penalty,
    dispersion_cap,
    next_streak,
    placement_amp,
    placement_weight,
    soft_cap_factor,
    soft_reset,
    streak_multiplier,
    to_cr,
)
from .params import DEFAULT_PARAMS, RatingParams, validate_params
from .types import (
    AppliedModifiers,
    MatchInput,
    ParticipantInput,
    PlayerRatingResult,
    PlayerState,
    RatingResult,
    TeamInput,
)

__all__ = [
    "rate",
    "to_cr",
    "soft_reset",
    "DEFAULT_PARAMS",
    "RatingParams",
    "validate_params",
    "placement_weight",
    "placement_amp",
    "streak_multiplier",
    "next_streak",
    "soft_cap_factor",
    "boosting_penalty",
    "dispersion_cap",
    "PlayerState",
    "ParticipantInput",
    "TeamInput",
    "MatchInput",
    "AppliedModifiers",
    "PlayerRatingResult",
    "RatingResult",
]
