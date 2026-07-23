"""CR-space (PDL) cap layer — pure functions, no I/O.

A reward-display contract layered ON TOP of the mu-space rating pipeline
(``engine.rate`` / ``modifiers``). The (mu, sigma) posterior trajectory is NOT
touched by this layer — per the Trinity caps brief (§7, B-dominant hybrid), the
mu step keeps its existing ±max_delta_mu clamp; this layer clamps the *displayed*
per-match ``cr_delta`` to a placement-relative bound.

Bound model (Trinity §3):
    C_win  = +base_cap[tc][placement]      · composite_win
    C_loss = −base_cap[tc][tc+1−placement] · composite_loss
    cr_delta_capped = clamp(cr_delta_raw, C_loss, C_win)

``composite_win`` folds the skill-mismatch override (R2, win side) and the high-CR
amount-scaling (R4, win side); party dampening (R3) ships OFF (multiplier 1.0).

These functions are season-tunable via :class:`CapParams` (to be mirrored into
``seasons.config`` when the layer is wired into the engine + ledger). For now they
back the offline what-if simulator (``scripts/sim_params.py``) for the sim-gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import exp


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _sigmoid(x: float) -> float:
    # numerically stable logistic
    if x >= 0.0:
        return 1.0 / (1.0 + exp(-x))
    z = exp(x)
    return z / (1.0 + z)


# Candidate base-cap curves (PDL magnitude allowed per placement, 1-indexed).
# SYMMETRIC: strict mirror — p3==p4 at the win/loss boundary (Trinity default).
SYMMETRIC_CAPS_6: dict[int, list[float]] = {6: [40.0, 34.0, 26.0, 26.0, 34.0, 40.0]}
# ASYMMETRIC: widens the boundary to preserve marginal-win incentive (Trinity §6.6).
ASYMMETRIC_CAPS_6: dict[int, list[float]] = {6: [40.0, 34.0, 28.0, 22.0, 34.0, 40.0]}
# Duos (8 teams) — symmetric.
CAPS_8: dict[int, list[float]] = {8: [40.0, 35.0, 28.0, 22.0, 22.0, 28.0, 35.0, 40.0]}


@dataclass(frozen=True, slots=True)
class CapParams:
    base_cap_by_placement: dict[int, list[float]] = field(
        default_factory=lambda: {**SYMMETRIC_CAPS_6, **CAPS_8}
    )
    # R2 — skill-mismatch override (win side)
    mismatch_beta: float = 100.0
    mismatch_threshold: float = 0.5
    mismatch_slope: float = 0.25
    mismatch_max_mult: float = 1.25
    mismatch_sigma_gate: float = 150.0
    mismatch_games_gate: int = 5
    # R4 — high-CR amount scaling (win side)
    high_cr_midpoint: float = 1380.0
    high_cr_steepness: float = 120.0
    high_cr_max_reduction: float = 0.40
    # composite clamp
    composite_floor: float = 0.5
    composite_ceil: float = 1.25
    # asymmetric loss option: when set, the loss bound is a flat -loss_clamp (·composite_loss)
    # instead of the mirror of the placement table. Decouples "painful loss" from the
    # gain cap (resolves the symmetric-vs-painful spec tension; ~P95 keeps losses near raw).
    loss_clamp: float | None = None


def mismatch_override(
    mu: float, lobby_mean_excl_self: float, *, sigma: float, games: int, cp: CapParams
) -> float:
    """Win-cap multiplier (≥1.0) when the player's skill is materially above the lobby.

    Gated: only fires once the estimate is trustworthy (sigma below gate OR enough
    games). z is the standardized skill gap; below `mismatch_threshold` it is a no-op.
    """
    if not (sigma < cp.mismatch_sigma_gate or games >= cp.mismatch_games_gate):
        return 1.0
    z = (mu - lobby_mean_excl_self) / cp.mismatch_beta
    ovr = 1.0 + cp.mismatch_slope * max(0.0, z - cp.mismatch_threshold)
    return _clamp(ovr, 1.0, cp.mismatch_max_mult)


def high_cr_scale(cr_before: float, cp: CapParams) -> float:
    """Win-cap multiplier (≤1.0) that scales DOWN gains as CR rises past the midpoint.

    Never floors a gain to zero (bounded below by 1 − max_reduction); losses are
    untouched (this is applied to the win side only by the caller).
    """
    return 1.0 - cp.high_cr_max_reduction * _sigmoid(
        (cr_before - cp.high_cr_midpoint) / cp.high_cr_steepness
    )


def composite_win_mult(ovr: float, scf: float, party_mult: float, cp: CapParams) -> float:
    """Fold the win-side multipliers and clamp to [floor, ceil]."""
    return _clamp(ovr * scf * party_mult, cp.composite_floor, cp.composite_ceil)


def cap_bounds(
    placement: int, team_count: int, composite_win: float, composite_loss: float, cp: CapParams
) -> tuple[float, float]:
    """Return (C_loss, C_win) PDL bounds for a placement. Falls back to (-inf, inf) if
    no curve is configured for this team_count."""
    base = cp.base_cap_by_placement.get(team_count)
    if base is None or not (1 <= placement <= len(base)):
        return (float("-inf"), float("inf"))
    c_win = base[placement - 1] * composite_win
    loss_mag = cp.loss_clamp if cp.loss_clamp is not None else base[team_count - placement]
    c_loss = -loss_mag * composite_loss  # mirror table, or flat loss_clamp if set
    return (c_loss, c_win)


def apply_pdl_cap(
    cr_delta_raw: float,
    placement: int,
    team_count: int,
    *,
    composite_win: float,
    composite_loss: float,
    cp: CapParams,
) -> tuple[float, bool]:
    """Clamp a raw cr_delta to the placement-relative PDL bounds.

    Returns (capped_delta, clamped) where `clamped` is True iff the raw value exceeded
    a bound.
    """
    lo, hi = cap_bounds(placement, team_count, composite_win, composite_loss, cp)
    capped = _clamp(cr_delta_raw, lo, hi)
    return capped, (cr_delta_raw < lo or cr_delta_raw > hi)
