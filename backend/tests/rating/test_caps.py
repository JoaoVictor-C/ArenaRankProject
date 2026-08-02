"""Tests for the CR-space (PDL) cap layer — pure functions, no DB.

Design (Trinity caps brief §3): the cap sits ON TOP of the mu-space pipeline. The
(mu, sigma) trajectory is unchanged; this layer clamps the per-match cr_delta to a
placement-relative bound, modulated by a skill-mismatch override (win side) and a
high-CR amount-scaling (win side). Party dampening (R3) is OFF (multiplier 1.0).
"""

from __future__ import annotations

import pytest

from arena.rating.caps import (
    SYMMETRIC_CAPS_6,
    CapParams,
    apply_pdl_cap,
    cap_bounds,
    composite_win_mult,
    high_cr_scale,
    mismatch_override,
)


@pytest.fixture
def cp() -> CapParams:
    return CapParams(base_cap_by_placement=SYMMETRIC_CAPS_6)


# ---- cap_bounds -------------------------------------------------------------


def test_cap_bounds_symmetric_extremes(cp: CapParams) -> None:
    # placement 1 of 6, symmetric {40,34,26,26,34,40}, composites 1.0
    lo, hi = cap_bounds(1, 6, 1.0, 1.0, cp)
    assert hi == pytest.approx(40.0)
    assert lo == pytest.approx(-40.0)  # C_loss uses mirror base[6]=40


def test_cap_bounds_symmetric_middle(cp: CapParams) -> None:
    lo, hi = cap_bounds(3, 6, 1.0, 1.0, cp)
    assert hi == pytest.approx(26.0)  # base[3]
    assert lo == pytest.approx(-26.0)  # mirror base[4]=26


def test_cap_bounds_scaled_by_composite_win(cp: CapParams) -> None:
    # win composite raises only the win bound; loss bound uses its own composite
    lo, hi = cap_bounds(1, 6, 1.25, 1.0, cp)
    assert hi == pytest.approx(50.0)  # 40 * 1.25
    assert lo == pytest.approx(-40.0)


def test_cap_bounds_loss_clamp_override_decouples_loss_from_win() -> None:
    # asymmetric design: gains keep the placement table, losses use a flat looser clamp
    cp = CapParams(base_cap_by_placement=SYMMETRIC_CAPS_6, loss_clamp=68.0)
    lo, hi = cap_bounds(3, 6, 1.0, 1.0, cp)
    assert hi == pytest.approx(26.0)  # win still from the placement table
    assert lo == pytest.approx(-68.0)  # loss from the flat clamp, NOT the mirror (-26)


# ---- apply_pdl_cap ----------------------------------------------------------


def test_apply_pdl_cap_clamps_excessive_gain(cp: CapParams) -> None:
    capped, clamped = apply_pdl_cap(59.0, 1, 6, composite_win=1.0, composite_loss=1.0, cp=cp)
    assert capped == pytest.approx(40.0)
    assert clamped is True


def test_apply_pdl_cap_clamps_excessive_loss(cp: CapParams) -> None:
    capped, clamped = apply_pdl_cap(-77.0, 6, 6, composite_win=1.0, composite_loss=1.0, cp=cp)
    assert capped == pytest.approx(-40.0)  # mirror base[1]=40
    assert clamped is True


def test_apply_pdl_cap_passthrough_within_bounds(cp: CapParams) -> None:
    capped, clamped = apply_pdl_cap(20.0, 3, 6, composite_win=1.0, composite_loss=1.0, cp=cp)
    assert capped == pytest.approx(20.0)
    assert clamped is False


# ---- mismatch_override (R2, win side) ---------------------------------------


def test_mismatch_override_noop_below_threshold(cp: CapParams) -> None:
    # z = (1040 - 1000)/100 = 0.4 < threshold 0.5 -> no override
    assert mismatch_override(1040.0, 1000.0, sigma=100.0, games=10, cp=cp) == pytest.approx(1.0)


def test_mismatch_override_raises_for_strong_player(cp: CapParams) -> None:
    # z = (1100 - 1000)/100 = 1.0 ; ovr = 1 + 0.25*(1.0-0.5) = 1.125 ; gate open (sigma<150)
    assert mismatch_override(1100.0, 1000.0, sigma=100.0, games=10, cp=cp) == pytest.approx(1.125)


def test_mismatch_override_clamped_at_max(cp: CapParams) -> None:
    # huge z -> clamp to max_mult 1.25
    assert mismatch_override(1400.0, 1000.0, sigma=100.0, games=10, cp=cp) == pytest.approx(1.25)


def test_mismatch_override_gated_off_when_provisional(cp: CapParams) -> None:
    # high z but sigma>=150 AND games<5 -> gate closed -> 1.0 (no override)
    assert mismatch_override(1400.0, 1000.0, sigma=200.0, games=1, cp=cp) == pytest.approx(1.0)


# ---- high_cr_scale (R4, win side) -------------------------------------------


def test_high_cr_scale_noop_far_below_midpoint(cp: CapParams) -> None:
    # CR well below midpoint 1380 -> sigmoid ~0 -> scf ~1.0
    assert high_cr_scale(600.0, cp) == pytest.approx(1.0, abs=1e-3)


def test_high_cr_scale_at_midpoint_is_half_reduction(cp: CapParams) -> None:
    # at midpoint sigmoid=0.5 -> scf = 1 - 0.40*0.5 = 0.80
    assert high_cr_scale(cp.high_cr_midpoint, cp) == pytest.approx(0.80)


def test_high_cr_scale_floor_is_one_minus_max_reduction(cp: CapParams) -> None:
    # very high CR -> sigmoid ~1 -> scf -> 1 - max_reduction = 0.60, never below
    scf = high_cr_scale(1e6, cp)
    assert scf == pytest.approx(0.60, abs=1e-6)
    assert scf >= 1.0 - cp.high_cr_max_reduction


# ---- composite_win_mult -----------------------------------------------------


def test_composite_win_mult_clamped_to_ceiling(cp: CapParams) -> None:
    # ovr 1.25 * scf 1.0 * party 1.0 = 1.25 (at ceiling)
    assert composite_win_mult(1.25, 1.0, 1.0, cp) == pytest.approx(1.25)


def test_composite_win_mult_clamped_to_floor(cp: CapParams) -> None:
    # ovr 1.0 * scf 0.30 * party 1.0 = 0.30 -> clamp up to floor 0.5
    assert composite_win_mult(1.0, 0.30, 1.0, cp) == pytest.approx(0.5)


# ---- tail shaping: position-relative loss caps + minimum gain (2026-08-02) ---


def _tail_cp() -> CapParams:
    """The shipped DEFAULT_PARAMS cap config (both new curves active)."""
    from arena.rating.params import DEFAULT_PARAMS

    assert DEFAULT_PARAMS.caps is not None
    return DEFAULT_PARAMS.caps


def test_loss_curve_takes_precedence_over_flat_clamp() -> None:
    """A near-miss 4th must NOT share the dead-last ceiling (Trinity R1)."""
    cp = _tail_cp()
    lo_4th, _ = cap_bounds(4, 6, 1.0, 1.0, cp)
    lo_6th, _ = cap_bounds(6, 6, 1.0, 1.0, cp)
    assert lo_4th == pytest.approx(-30.0)
    assert lo_6th == pytest.approx(-68.0)  # bottom stays as painful as before
    assert lo_4th > lo_6th


def test_fourth_place_blowout_is_pulled_to_the_curve() -> None:
    """The reported -37 at 4th (strong player, weak lobby) lands on -30."""
    cp = _tail_cp()
    out, changed = apply_pdl_cap(
        -37.4, 4, 6, composite_win=0.75, composite_loss=1.0, cp=cp
    )
    assert out == pytest.approx(-30.0)
    assert changed


def test_minimum_gain_floor_lifts_a_hollow_win() -> None:
    """+7.6 for a 1st place is floored to the placement minimum (Trinity R4)."""
    cp = _tail_cp()
    out, changed = apply_pdl_cap(
        7.6, 1, 6, composite_win=0.75, composite_loss=1.0, cp=cp
    )
    assert out == pytest.approx(15.0)
    assert changed


def test_top_half_placement_is_never_net_negative() -> None:
    """A 2nd place that computed NEGATIVE becomes positive (Trinity R4 made literal)."""
    cp = _tail_cp()
    out, _ = apply_pdl_cap(-8.9, 2, 6, composite_win=0.75, composite_loss=1.0, cp=cp)
    assert out == pytest.approx(10.0)


def test_healthy_gain_is_left_alone() -> None:
    """The floor must not touch a player already earning above it."""
    cp = _tail_cp()
    out, changed = apply_pdl_cap(
        25.5, 1, 6, composite_win=0.75, composite_loss=1.0, cp=cp
    )
    assert out == pytest.approx(25.5)
    assert not changed


def test_flagged_booster_gets_no_free_floor() -> None:
    """gain_floor_mult=0 (fully flagged) must disable the minimum-gain payout."""
    cp = _tail_cp()
    out, _ = apply_pdl_cap(
        0.0, 1, 6, composite_win=0.75, composite_loss=1.0, cp=cp, gain_floor_mult=0.0
    )
    assert out == pytest.approx(0.0)


def test_floor_never_exceeds_the_placement_gain_ceiling() -> None:
    """With a crushed composite the floor is capped by hi, not paid in full."""
    cp = _tail_cp()
    # composite_win 0.5 (floor) -> hi = 26 * 0.5 = 13.0 for a 3rd place; floor is 5.
    _, hi = cap_bounds(3, 6, 0.5, 1.0, cp)
    out, _ = apply_pdl_cap(0.0, 3, 6, composite_win=0.5, composite_loss=1.0, cp=cp)
    assert out <= hi + 1e-9
