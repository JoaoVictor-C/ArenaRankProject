"""Pure rating functions: the gamified modifier pipeline, CR display, and soft-reset.

Ports the slice-1 TypeScript modifiers with the Trinity hardening applied
(C1 sigma-scaled dispersion cap, M3 renormalized weights live in params, DEC-B
loss-floor 0.25). All functions are pure and deterministic — no I/O, no clocks.
"""

from __future__ import annotations

from .params import RatingParams
from .types import PlayerState


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


# ---- CR display (D1/D4): conservative, derived from (mu, sigma) ----


def to_cr(mu: float, sigma: float, p: RatingParams) -> float:
    """CR = (mu - 3*sigma) * scale_factor + base_offset, floored at 0.

    Increasing in mu, decreasing in sigma. The floor enforces the invariant that
    a player's PDL (displayed CR) can never be below 0.
    """
    cr = (mu - 3.0 * sigma) * p.scale_factor + p.base_offset
    return cr if cr > 0.0 else 0.0


# ---- Modifier multipliers (applied to the PL base delta-mu) ----


def placement_weight(placement: int, team_count: int, p: RatingParams) -> float:
    curve = p.placement_weights.get(team_count)
    if curve is None or not (1 <= placement <= len(curve)):
        return 1.0
    return curve[placement - 1]


def placement_amp(state: PlayerState, p: RatingParams) -> float:
    return p.placement_amp if state.placement_matches_remaining > 0 else 1.0


def streak_multiplier(current_streak: int, delta_mu_sign: float, p: RatingParams) -> float:
    """Win bonus while on a win streak; loss dampener while on a loss streak. Bounded [floor, ceil]."""
    thr = p.streak_threshold
    if delta_mu_sign > 0 and current_streak > 0:
        return min(
            p.streak_win_ceil, 1.0 + (min(current_streak, thr) / thr) * (p.streak_win_ceil - 1.0)
        )
    if delta_mu_sign < 0 and current_streak < 0:
        return max(
            p.streak_loss_floor,
            1.0 - (min(-current_streak, thr) / thr) * (1.0 - p.streak_loss_floor),
        )
    return 1.0


def next_streak(current_streak: int, is_win: bool) -> int:
    if is_win:
        return current_streak + 1 if current_streak >= 0 else 1
    return current_streak - 1 if current_streak <= 0 else -1


def soft_cap_factor(cr: float, delta_mu: float, p: RatingParams) -> float:
    """Diminishing returns above the soft cap. Positive side only; in (0, 1]."""
    if delta_mu > 0 and cr > p.soft_cap_threshold:
        return 1.0 / (1.0 + (cr - p.soft_cap_threshold) / p.soft_cap_scale)
    return 1.0


def boosting_penalty(delta_mu: float, factor: float) -> float:
    """Booster gains less (positive side only). `factor` (0..1) comes from the integrity layer."""
    if delta_mu > 0:
        return 1.0 - _clamp(factor, 0.0, 1.0)
    return 1.0


def party_dampener(delta_mu: float, factor: float) -> float:
    """Detected premades gain less than solo players (positive side only).

    `factor` (0..1) is the per-player premade-penalty from the integrity layer
    (co-occurrence confidence x intra-party homogeneity x strength). Losses and
    no-op deltas are never dampened, so winning solo stays the most rewarding and
    carrying lower-elo mates (homogeneity -> 0 ⇒ factor -> 0) is unaffected.
    """
    if delta_mu > 0:
        return 1.0 - _clamp(factor, 0.0, 1.0)
    return 1.0


def dispersion_cap(delta_mu: float, sigma_before: float, p: RatingParams) -> tuple[float, bool]:
    """Sigma-scaled clamp (Trinity C1): high uncertainty => higher cap, so legit fast climbers
    and deserved provisional losses are not flattened; established players stay capped near max."""
    effective = p.max_delta_mu * max(1.0, sigma_before / p.dispersion_sigma_ref)
    clamped = abs(delta_mu) > effective
    return _clamp(delta_mu, -effective, effective), clamped


# ---- Season soft-reset (SeasonService calls this at season boundary) ----


def soft_reset(state: PlayerState, p: RatingParams) -> PlayerState:
    new_mu = p.reset_anchor + (state.mu - p.reset_anchor) * p.reset_factor
    new_sigma = min(state.sigma * p.sigma_reset_mult, p.sigma_reset_cap)
    new_cr = to_cr(new_mu, new_sigma, p)
    return PlayerState(
        player_id=state.player_id,
        mu=new_mu,
        sigma=new_sigma,
        cr=new_cr,
        current_streak=0,
        matches_played=0,
        placement_matches_remaining=p.placement_match_count,
        peak_cr=new_cr,
    )
