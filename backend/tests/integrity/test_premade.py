"""Premade detection + scoring (pure ``evaluate_premade`` + ``pair_key``).

The dampener factor per player = premade_strength x confidence x homogeneity:
  * confidence ramps with co-occurrence count, saturating at the repeat threshold;
  * homogeneity -> 0 as the subteam's internal CR spread approaches the gap, so a
    premade carrying lower-elo mates backs off (RDS handles that case instead).
Solo-matched subteams (no repeat co-occurrence) get 0.0.
"""

from __future__ import annotations

import pytest

from arena.integrity.evaluators import evaluate_premade
from arena.integrity.fingerprint import pair_key
from arena.integrity.params import DEFAULT_INTEGRITY_PARAMS
from arena.integrity.types import MatchSnapshot, ParticipantSnapshot


def _part(pid: str, team_id: int, cr: float) -> ParticipantSnapshot:
    return ParticipantSnapshot(player_id=pid, team_id=team_id, champion_id=0, cr=cr)


def _match(*parts: ParticipantSnapshot) -> MatchSnapshot:
    return MatchSnapshot(
        match_id="m", mode="DUOS", team_size=2, duration_seconds=600, participants=list(parts)
    )


P = DEFAULT_INTEGRITY_PARAMS


def test_solo_subteam_has_zero_factor() -> None:
    # A duo with no co-occurrence history (count 1) reads as solo => no dampening.
    match = _match(_part("a", 1, 1000.0), _part("b", 1, 1000.0))
    counts = {pair_key("a", "b"): 1}
    factors = evaluate_premade(match, counts, P)
    assert factors["a"] == pytest.approx(0.0)
    assert factors["b"] == pytest.approx(0.0)


def test_even_premade_is_dampened_at_full_strength() -> None:
    # Repeat co-occurrence >= threshold (confidence 1) + equal CR (homogeneity 1).
    match = _match(_part("a", 1, 1000.0), _part("b", 1, 1000.0))
    counts = {pair_key("a", "b"): P.premade_repeat_threshold}
    factors = evaluate_premade(match, counts, P)
    assert factors["a"] == pytest.approx(P.premade_strength)
    assert factors["b"] == pytest.approx(P.premade_strength)


def test_confidence_ramps_below_threshold() -> None:
    # count=2, threshold=3 => confidence 0.5 => half strength.
    match = _match(_part("a", 1, 1000.0), _part("b", 1, 1000.0))
    counts = {pair_key("a", "b"): 2}
    factors = evaluate_premade(match, counts, P)
    expected = P.premade_strength * ((2 - 1) / (P.premade_repeat_threshold - 1))
    assert factors["a"] == pytest.approx(expected)


def test_carry_backs_off_at_large_cr_spread() -> None:
    # Strong co-occurrence but a CR spread >= the homogeneity gap => factor ~0
    # (carrying lower-elo mates is hard, so it isn't dampened).
    spread = P.premade_homogeneity_gap + 100.0
    match = _match(_part("a", 1, 1000.0), _part("b", 1, 1000.0 + spread))
    counts = {pair_key("a", "b"): P.premade_repeat_threshold}
    factors = evaluate_premade(match, counts, P)
    assert factors["a"] == pytest.approx(0.0)
    assert factors["b"] == pytest.approx(0.0)


def test_pair_key_is_order_independent() -> None:
    assert pair_key("a", "b") == pair_key("b", "a")
    assert pair_key("a", "b") != pair_key("a", "c")
