"""Tests for the pure gamified modifier functions (no DB).

Focus: the premade dampener (``party_dampener``) — a gains-only multiplier that
scales DOWN a positive PL delta-mu for detected premades, leaving losses (and
zero/no-op deltas) untouched. Mirrors the existing one-sided ``boosting_penalty``.
"""

from __future__ import annotations

import pytest

from arena.rating.modifiers import party_dampener


# ---- party_dampener ---------------------------------------------------------


def test_party_dampener_noop_when_factor_zero() -> None:
    # factor 0 => full reward (solo / undetected premade).
    assert party_dampener(10.0, 0.0) == pytest.approx(1.0)


def test_party_dampener_scales_positive_delta() -> None:
    # factor 0.15 => keep 85% of the gain.
    assert party_dampener(10.0, 0.15) == pytest.approx(0.85)


def test_party_dampener_ignores_losses() -> None:
    # Negative delta (a loss) is never dampened, regardless of factor.
    assert party_dampener(-10.0, 0.8) == pytest.approx(1.0)


def test_party_dampener_ignores_zero_delta() -> None:
    assert party_dampener(0.0, 0.5) == pytest.approx(1.0)


def test_party_dampener_clamps_factor_above_one() -> None:
    # factor > 1 cannot flip the sign of the gain; multiplier floors at 0.
    assert party_dampener(10.0, 1.7) == pytest.approx(0.0)


def test_party_dampener_clamps_negative_factor() -> None:
    # A negative factor cannot amplify a gain; multiplier ceils at 1.0.
    assert party_dampener(10.0, -0.5) == pytest.approx(1.0)
