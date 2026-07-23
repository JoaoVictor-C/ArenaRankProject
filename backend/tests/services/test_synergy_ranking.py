"""Wilson lower-bound ranking for the champion-synergy showcase.

Pure-math coverage for :func:`arena.services.stats_service._wilson_lower_bound`
and the anti-noise ordering it implies (a perfect run over a handful of games
must never outrank a solid rate over a real sample). The SQL floor itself
(``min_games``) is exercised via the query's ``HAVING`` clause and stays a
constant assertion here so a silent regression to an unfiltered showcase fails
CI.
"""

from __future__ import annotations

import math

import pytest

from arena.services.stats_service import _WILSON_Z, SYNERGY_MIN_GAMES, _wilson_lower_bound


def test_zero_games_is_zero() -> None:
    assert _wilson_lower_bound(0, 0) == 0.0


def test_bounds_are_sane() -> None:
    # Always inside (0, 1) for non-degenerate inputs, below the raw proportion.
    for successes, games in [(1, 2), (10, 15), (15, 15), (60, 100), (999, 1000)]:
        lb = _wilson_lower_bound(successes, games)
        assert 0.0 < lb < 1.0
        assert lb < successes / games or successes == 0


def test_perfect_small_sample_ranks_below_solid_large_sample() -> None:
    # The exact failure the showcase had: 100% over 15 games ranked first.
    perfect_15 = _wilson_lower_bound(15, 15)
    solid_200 = _wilson_lower_bound(170, 200)  # 85% over 200 games
    assert solid_200 > perfect_15


def test_more_games_at_same_rate_ranks_higher() -> None:
    assert _wilson_lower_bound(80, 100) > _wilson_lower_bound(8, 10)


def test_known_value() -> None:
    # Analytic reference at the module's own z (keeps the test in sync).
    p, n, z = 1.0, 15, _WILSON_Z
    z2 = z * z
    expected = (p + z2 / (2 * n) - z * math.sqrt((p * (1 - p) + z2 / (4 * n)) / n)) / (1 + z2 / n)
    assert _wilson_lower_bound(15, 15) == pytest.approx(expected)


def test_showcase_floor_is_enforced_constant() -> None:
    # Provisional floor (young season). Raising it later is fine; dropping it
    # below double digits re-opens the "100% · 5 partidas" credibility hole.
    assert SYNERGY_MIN_GAMES >= 10
