"""Integrity tunables (proposal §3.2). Pure config, no I/O.

All thresholds are season-tunable; these are the launch defaults. Mirrors the
shape/discipline of ``arena.rating.params`` (frozen dataclass + validator) so
untrusted season config (JSONB) cannot poison the scoring with NaN/Infinity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite


@dataclass(frozen=True, slots=True)
class RdsTier:
    """One tier of the Rating Disparity Score → boosting-penalty ladder.

    A premade pair whose CR gap is ``>= min_cr_gap`` lands in this tier and the
    higher-rated booster's positive Δμ is scaled by ``(1 - penalty_factor)``
    inside the rating engine (``boosting_penalty``). ``penalty_factor`` is 0..1.
    """

    min_cr_gap: float
    penalty_factor: float  # 0..1 → ParticipantInput.boosting_penalty_factor
    severity: str  # 'INFO' | 'WARN' | 'CRITICAL'
    label: str


# Tiered penalties (proposal §3.2 "tiered penalties"). Ordered ascending by gap;
# the matcher picks the *highest* qualifying tier. Mean-1.0 not required here —
# this is a one-sided dampener, not a redistribution.
_DEFAULT_RDS_TIERS: tuple[RdsTier, ...] = (
    RdsTier(min_cr_gap=400.0, penalty_factor=0.25, severity="INFO", label="leve"),
    RdsTier(min_cr_gap=700.0, penalty_factor=0.50, severity="WARN", label="moderada"),
    RdsTier(min_cr_gap=1000.0, penalty_factor=0.80, severity="CRITICAL", label="severa"),
)


@dataclass(frozen=True, slots=True)
class IntegrityParams:
    # ---- RDS / duo-boosting ------------------------------------------------
    rds_tiers: tuple[RdsTier, ...] = field(default_factory=lambda: _DEFAULT_RDS_TIERS)
    # Below this absolute CR gap a premade pair is never penalized (normal duo).
    rds_min_gap: float = 400.0

    # ---- Premade dampener (solo wins worth more) ---------------------------
    # Detected premades earn less CR on a win than solo players, scaled by
    # co-occurrence confidence x intra-subteam CR homogeneity. The factor feeds
    # rating.party_dampener (gains-only). Losses untouched. See evaluate_premade.
    premade_strength: float = 0.15  # max penalty fraction at full confidence + homogeneity
    premade_repeat_threshold: int = 3  # co-occurrence count at which confidence saturates to 1
    premade_window_seconds: int = 1_209_600  # 14d rolling co-occurrence window
    # CR spread at which homogeneity hits 0 (carrying lower-elo => no dampening;
    # aligned to rds_min_gap so RDS takes over exactly where the dampener stops).
    premade_homogeneity_gap: float = 400.0

    # ---- AFK / eligibility -------------------------------------------------
    # A player is ineligible if explicitly AFK, or participated in fewer than
    # this fraction of rounds, or dealt (near) zero damage over a real match.
    afk_min_participation: float = 0.40  # rounds_played / rounds_total
    afk_min_damage: int = 1  # > 0 damage required to count as "played"

    # ---- Unusual duration (statistical outlier on match length) ------------
    # Expected duration per round; outlier if total deviates by > z * sigma.
    duration_mean_seconds: float = 600.0  # ~10 min reference match
    duration_std_seconds: float = 150.0
    duration_z_warn: float = 2.5  # |z| beyond this ⇒ WARN
    duration_z_critical: float = 4.0  # |z| beyond this ⇒ CRITICAL (likely fixed)
    duration_min_seconds: int = 60  # implausibly short → always suspicious

    # ---- Repeated-lobby (same composition 3+ in 24h) -----------------------
    repeated_lobby_window_seconds: int = 86_400  # 24h
    repeated_lobby_threshold: int = 3  # 3rd+ occurrence ⇒ flag
    repeated_lobby_critical: int = 5  # 5th+ ⇒ CRITICAL (match-fixing ring)

    # ---- Rating dispersion -------------------------------------------------
    # Mirrors rating.dispersion (informational): flag when the in-lobby CR
    # spread is extreme — a single dominant account can distort the board.
    dispersion_cr_warn: float = 1200.0
    dispersion_cr_critical: float = 1800.0


DEFAULT_INTEGRITY_PARAMS = IntegrityParams()


def validate_integrity_params(p: IntegrityParams) -> None:
    """Reject non-finite / out-of-range integrity config (untrusted JSONB guard)."""
    scalars = {
        "rds_min_gap": p.rds_min_gap,
        "afk_min_participation": p.afk_min_participation,
        "duration_mean_seconds": p.duration_mean_seconds,
        "duration_std_seconds": p.duration_std_seconds,
        "duration_z_warn": p.duration_z_warn,
        "duration_z_critical": p.duration_z_critical,
        "dispersion_cr_warn": p.dispersion_cr_warn,
        "dispersion_cr_critical": p.dispersion_cr_critical,
    }
    for name, val in scalars.items():
        if not isfinite(val):
            raise ValueError(f"IntegrityParams.{name} is not finite: {val!r}")
    if not (0.0 <= p.afk_min_participation <= 1.0):
        raise ValueError("afk_min_participation must be in [0, 1]")
    if p.afk_min_damage < 0:
        raise ValueError("afk_min_damage must be >= 0")
    if p.duration_std_seconds <= 0:
        raise ValueError("duration_std_seconds must be > 0")
    if p.duration_z_warn <= 0 or p.duration_z_critical <= p.duration_z_warn:
        raise ValueError("require 0 < duration_z_warn < duration_z_critical")
    if p.repeated_lobby_threshold < 1:
        raise ValueError("repeated_lobby_threshold must be >= 1")
    if p.repeated_lobby_critical < p.repeated_lobby_threshold:
        raise ValueError("repeated_lobby_critical must be >= repeated_lobby_threshold")
    if p.dispersion_cr_critical < p.dispersion_cr_warn:
        raise ValueError("dispersion_cr_critical must be >= dispersion_cr_warn")
    if not (0.0 <= p.premade_strength <= 1.0):
        raise ValueError("premade_strength must be in [0, 1]")
    if p.premade_repeat_threshold < 2:
        raise ValueError("premade_repeat_threshold must be >= 2")
    if p.premade_window_seconds <= 0:
        raise ValueError("premade_window_seconds must be > 0")
    if p.premade_homogeneity_gap <= 0:
        raise ValueError("premade_homogeneity_gap must be > 0")
    if not p.rds_tiers:
        raise ValueError("rds_tiers must not be empty")
    for t in p.rds_tiers:
        if not isfinite(t.min_cr_gap) or not isfinite(t.penalty_factor):
            raise ValueError(f"RdsTier has non-finite field: {t!r}")
        if not (0.0 <= t.penalty_factor <= 1.0):
            raise ValueError(f"RdsTier.penalty_factor must be in [0, 1]: {t.penalty_factor!r}")
        if t.severity not in ("INFO", "WARN", "CRITICAL"):
            raise ValueError(f"RdsTier.severity invalid: {t.severity!r}")
