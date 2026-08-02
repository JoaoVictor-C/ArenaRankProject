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

# --- Tail shaping for the "strong player in a weak lobby" case (2026-08-02) ----
#
# Measured on 7d of production (99,909 rows per placement, trios):
#   placement | p05   | median | p95   |    <- the TYPICAL player is fine:
#      1      | +22.3 | +37.9  | +41.3 |       1st ≈ +38, 4th is already POSITIVE.
#      4      |  -4.6 |  +5.6  | +16.5 |
#      6      | -68.0 | -47.9  | -20.6 |
#
# The pain reported by players (e.g. +8 for a 1st, -37 for a 4th) is NOT the
# global curve — it is the Plackett-Luce EXPECTATION effect in the tail: a player
# queued with much stronger friends is expected to win, so a win teaches the model
# almost nothing (tiny gain) while a 4th place is a big surprise (large loss).
# Both of the curves below therefore bind ONLY below the 5th percentile — they
# reshape the tail and leave the median player's numbers untouched.

# LOSS caps, per placement (1-indexed), replacing the flat `loss_clamp`. The flat
# clamp made a near-miss 4th and a dead-last 6th share one ceiling (-68), which
# dropped the position-relative loss shaping that Trinity R1 actually asked for.
# 6th keeps -68 (median -47.9 unchanged); 4th is bounded at -30 so only the
# expectation-driven tail is pulled in. Top-half entries are inert (the gain
# floor below keeps a top-half placement net-positive, per Trinity R4).
LOSS_CAPS_6: dict[int, list[float]] = {6: [30.0, 30.0, 30.0, 30.0, 45.0, 68.0]}
LOSS_CAPS_8: dict[int, list[float]] = {8: [30.0, 30.0, 30.0, 30.0, 30.0, 42.0, 55.0, 68.0]}

# GAIN floors, per placement (1-indexed). Trinity R4: "a good placement must
# ALWAYS be net-positive" — this makes that invariant literal instead of merely
# usually-true. Only top-half placements carry a floor; 0.0 means "no floor".
MIN_GAIN_6: dict[int, list[float]] = {6: [15.0, 10.0, 5.0, 0.0, 0.0, 0.0]}
MIN_GAIN_8: dict[int, list[float]] = {8: [15.0, 11.0, 7.0, 4.0, 0.0, 0.0, 0.0, 0.0]}


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
    # Superseded by `loss_cap_by_placement` when that is set (kept for season configs
    # / tests that still pin the flat behavior).
    loss_clamp: float | None = None
    # Position-relative LOSS caps (magnitude, 1-indexed by placement). Takes
    # precedence over `loss_clamp`; falls back to the mirror table when neither set.
    loss_cap_by_placement: dict[int, list[float]] | None = None
    # Position-relative minimum GAIN (Trinity R4). 0.0 / missing => no floor.
    min_gain_by_placement: dict[int, list[float]] | None = None


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
    # Precedence: position-relative loss curve > flat loss_clamp > mirror of the
    # gain table. The mirror stays the fallback so an unconfigured season keeps
    # the original symmetric contract.
    loss_curve = (cp.loss_cap_by_placement or {}).get(team_count)
    if loss_curve is not None and len(loss_curve) == len(base):
        loss_mag = loss_curve[placement - 1]
    elif cp.loss_clamp is not None:
        loss_mag = cp.loss_clamp
    else:
        loss_mag = base[team_count - placement]
    c_loss = -loss_mag * composite_loss
    return (c_loss, c_win)


def min_gain(placement: int, team_count: int, cp: CapParams) -> float:
    """Minimum PDL a placement must pay out (0.0 when no floor is configured)."""
    curve = (cp.min_gain_by_placement or {}).get(team_count)
    if curve is None or not (1 <= placement <= len(curve)):
        return 0.0
    return curve[placement - 1]


def apply_pdl_cap(
    cr_delta_raw: float,
    placement: int,
    team_count: int,
    *,
    composite_win: float,
    composite_loss: float,
    cp: CapParams,
    gain_floor_mult: float = 1.0,
) -> tuple[float, bool]:
    """Clamp a raw cr_delta to the placement-relative PDL bounds, then apply the
    minimum-gain floor for good placements.

    ``gain_floor_mult`` (0..1) scales the floor down; the engine passes
    ``1 - boosting_penalty_factor`` so a flagged booster cannot be handed a free
    floor by a rule meant to protect honest players.

    Returns (adjusted_delta, changed) where `changed` is True iff the raw value was
    moved by either the cap or the floor.
    """
    lo, hi = cap_bounds(placement, team_count, composite_win, composite_loss, cp)
    capped = _clamp(cr_delta_raw, lo, hi)
    floor = min_gain(placement, team_count, cp) * _clamp(gain_floor_mult, 0.0, 1.0)
    if floor > 0.0:
        # Never let the floor exceed this placement's own gain ceiling.
        capped = max(capped, min(floor, hi))
    return capped, (capped != cr_delta_raw)
