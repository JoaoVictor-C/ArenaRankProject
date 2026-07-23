"""Rating hyperparameters for the gamified CRS engine.

Ports the slice-1 TypeScript `RatingParams` / `DEFAULT_PARAMS` (proposal design)
including the Trinity hardening: renormalized placement weights (M3, per-curve mean
1.0), the sigma-scaled dispersion cap reference (C1), and the streak floor/ceil (DEC-B).

All values are season-tunable; these are the launch defaults. Pure, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite

from .caps import CAPS_8, SYMMETRIC_CAPS_6, CapParams


def _renorm(weights: list[float]) -> list[float]:
    """Normalize a placement-weight curve to mean 1.0 (Trinity M3 — no net |Δμ| drift)."""
    mean = sum(weights) / len(weights)
    return [w / mean for w in weights]


# Symmetric mild emphasis on extremes, renormalized to mean 1.0 (Trinity M3).
_DEFAULT_PLACEMENT_WEIGHTS: dict[int, list[float]] = {
    8: _renorm([1.20, 1.12, 1.06, 1.01, 1.01, 1.06, 1.12, 1.20]),  # 2v2 / Duos
    6: _renorm([1.18, 1.08, 1.02, 1.02, 1.08, 1.18]),  # 3v3 / Trios
}


@dataclass(frozen=True, slots=True)
class RatingParams:
    # Plackett-Luce / OpenSkill core
    # RECALIBRATION 2026-06-15 (Trinity meta_validation run 5bb0 + what-if sim):
    # production showed 15.8% of players with NEGATIVE CR and per-match swings up
    # to -572. Root cause = the conservative display CR=(mu-3*sigma)+offset is
    # dishonest when sigma0 is huge (350): mu-3*sigma0 = -50, so a new/low-mu
    # player displays negative, and because sigma barely converges in this
    # 6-team / ~1.85-games-per-player regime the -3*sigma penalty never unwinds.
    # Fix (Trinity's own "preferred Bayesian-coherent" path, viable here because
    # we fully RE-RATE the dev season — there are no live standings to preserve):
    # halve sigma0 so mu-3*sigma0 = +400 (new player CR = 650, the median) and PL
    # steps shrink with sigma. beta=sigma0/2, tau lowered to let sigma converge.
    mu0: float = 1000.0
    sigma0: float = 200.0  # was 350.0 — fixes negative CR at the source
    beta: float = 100.0  # performance noise (sigma0 / 2)
    tau: float = 1.5  # dynamics — lowered (Trinity R4) to reduce sigma re-inflation
    kappa: float = 1e-4  # variance floor multiplier

    # Conservative CR display: CR = (mu - 3*sigma) * scale + offset  (D1/D4).
    # Kept as mu-3*sigma (no display overhaul) — honest now that sigma0 is small.
    scale_factor: float = 1.0
    base_offset: float = 250.0

    # Placement weight curves keyed by team count (Trinity M3 renormalized)
    placement_weights: dict[int, list[float]] = field(
        default_factory=lambda: {k: list(v) for k, v in _DEFAULT_PLACEMENT_WEIGHTS.items()}
    )

    # Placement-match amplification (provisional window).
    # RECALIBRATION: was 2.0 — doubling the mu-delta during the provisional window
    # amplified noise into the DISPLAY precisely for the least-converged players
    # (the -572 swing was a -270 raw step *2.0). Set to 1.0 (no doubling); the
    # provisional window still exists for tagging/telemetry. (Trinity R3 proposed
    # redirecting amplification into sigma-shrink instead; deferred to Phase-2 as
    # engine surgery — moot for the 70% single-game cohort.)
    placement_amp: float = 1.0
    placement_match_count: int = 10

    # Streak modifier. RECALIBRATION (Trinity R5): loss-floor 0.25 -> 0.5 so the
    # win-ceil/loss-floor ratio is 2.7x (was 5.4x) — reduces the streak-driven
    # asymmetry contribution to the per-match drift.
    streak_loss_floor: float = 0.5
    streak_win_ceil: float = 1.35
    streak_threshold: int = 3

    # Soft cap (diminishing returns above threshold; positive side only)
    soft_cap_threshold: float = 5000.0
    soft_cap_scale: float = 1000.0

    # Dispersion cap (applied last). RECALIBRATION (Trinity R2 — revert C1): the
    # sigma-scaled cap E = 150*max(1, sigma/85) evaluated to ~617 at sigma~350, so
    # it NEVER bound on the pathology it was meant to catch (worst |Δμ| was 582).
    # New: a near-flat cap that binds in the realized regime — with ref=sigma0=200,
    # max(1, sigma/200) ~= 1, so E ~= 80 (mu-space) throughout. Worst observed
    # post-fix per-match CR swing in simulation: -77 / +59.
    max_delta_mu: float = 80.0
    dispersion_sigma_ref: float = 200.0

    # Season soft-reset
    reset_anchor: float = 1000.0
    reset_factor: float = 0.5
    sigma_reset_mult: float = 1.5
    sigma_reset_cap: float = 200.0  # coherence with new sigma0 (was 350.0)

    # CR-space (PDL) cap layer (Trinity caps brief). None => disabled (current
    # behavior). When set, the engine clamps per-match cr_delta to a placement-
    # relative bound via option B-pure (adjust mu_after to hit the capped delta;
    # CR identity preserved). Valid because arenarank runs no matchmaking, so mu
    # has no posterior-coherence consumer. Season-tunable (mirror to seasons.config).
    caps: CapParams | None = None


# Cap layer ACTIVE (Trinity caps brief + empirical gates, 2026-06-15): asymmetric —
# gains use the symmetric placement table (peak 40, mismatch override → ~50); losses
# decoupled to a flat ~P95 clamp (68) so losses stay painful (mean ≈ raw −59) AND the
# cap does not inflate (mean cr_delta +3.7, below the +4.2 baseline). See pdl-cap-layer.
DEFAULT_PARAMS = RatingParams(
    caps=CapParams(
        base_cap_by_placement={**SYMMETRIC_CAPS_6, **CAPS_8},
        loss_clamp=68.0,
    )
)


def validate_params(p: RatingParams) -> None:
    """Zero-dependency guard. Rejects non-finite / out-of-range params (closes Trinity G2).

    Raises ValueError on any violation so untrusted season config (JSONB) cannot
    poison the engine with NaN/Infinity.
    """
    scalars = {
        "mu0": p.mu0,
        "sigma0": p.sigma0,
        "beta": p.beta,
        "tau": p.tau,
        "kappa": p.kappa,
        "scale_factor": p.scale_factor,
        "base_offset": p.base_offset,
        "placement_amp": p.placement_amp,
        "placement_match_count": p.placement_match_count,
        "streak_loss_floor": p.streak_loss_floor,
        "streak_win_ceil": p.streak_win_ceil,
        "streak_threshold": p.streak_threshold,
        "soft_cap_threshold": p.soft_cap_threshold,
        "soft_cap_scale": p.soft_cap_scale,
        "max_delta_mu": p.max_delta_mu,
        "dispersion_sigma_ref": p.dispersion_sigma_ref,
        "reset_anchor": p.reset_anchor,
        "reset_factor": p.reset_factor,
        "sigma_reset_mult": p.sigma_reset_mult,
        "sigma_reset_cap": p.sigma_reset_cap,
    }
    for name, val in scalars.items():
        if not isfinite(val):
            raise ValueError(f"RatingParams.{name} is not finite: {val!r}")
    if p.sigma0 <= 0 or p.beta <= 0:
        raise ValueError("sigma0 and beta must be > 0")
    if not (0.0 < p.kappa < 1.0):
        raise ValueError("kappa must be in (0, 1)")
    if p.dispersion_sigma_ref <= 0 or p.soft_cap_scale <= 0:
        raise ValueError("dispersion_sigma_ref and soft_cap_scale must be > 0")
    if p.streak_loss_floor > 1.0 or p.streak_win_ceil < 1.0:
        raise ValueError("streak_loss_floor must be <= 1 and streak_win_ceil must be >= 1")
    if not p.placement_weights:
        raise ValueError("placement_weights must not be empty")
    for team_count, curve in p.placement_weights.items():
        if len(curve) != team_count:
            raise ValueError(f"placement_weights[{team_count}] must have {team_count} entries")
        for w in curve:
            if not isfinite(w):
                raise ValueError(f"placement_weights[{team_count}] has non-finite entry {w!r}")
