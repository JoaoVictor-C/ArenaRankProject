"""Engine-level integration of the premade dampener.

A detected premade (``ParticipantInput.party_penalty_factor`` > 0) earns LESS CR
on a win than an identical solo player at the same placement, while losses and the
sigma trajectory are untouched. caps disabled so the mu-space modifier flows
straight through to cr_delta (the cap layer would otherwise mask small effects).
"""

from __future__ import annotations

from dataclasses import replace

from arena.rating import (
    MatchInput,
    ParticipantInput,
    PlayerState,
    TeamInput,
    rate,
)
from arena.rating.modifiers import to_cr
from arena.rating.params import DEFAULT_PARAMS

P = replace(DEFAULT_PARAMS, caps=None)  # isolate the mu-space modifier


def _fresh(pid: str, p) -> PlayerState:
    cr = to_cr(p.mu0, p.sigma0, p)
    return PlayerState(
        player_id=pid,
        mu=p.mu0,
        sigma=p.sigma0,
        cr=cr,
        current_streak=0,
        matches_played=0,
        placement_matches_remaining=p.placement_match_count,
        peak_cr=cr,
    )


def _build(p, factors: dict[str, float] | None = None) -> MatchInput:
    """6 teams x 3 fresh players, placements 1..6; optional per-player party factor."""
    factors = factors or {}
    teams = []
    pid = 0
    for placement in range(1, 7):
        parts = []
        for _ in range(3):
            name = f"p{pid}"
            parts.append(
                ParticipantInput(
                    player_id=name,
                    state=_fresh(name, p),
                    champion_id=0,
                    eligible_for_progression=True,
                    party_penalty_factor=factors.get(name, 0.0),
                )
            )
            pid += 1
        teams.append(TeamInput(team_id=placement, placement=placement, participants=parts))
    return MatchInput(match_id="t", mode="TRIOS", teams=teams, params=p)


def _by_id(res):
    return {pr.player_id: pr for pr in res.players}


def test_premade_winner_gains_less_than_solo() -> None:
    # p0 is on the 1st-place team (a win). Dampening it must reduce its gain but
    # keep it positive (a premade still climbs, just slower than solo).
    base = _by_id(rate(_build(P)))["p0"]
    damp = _by_id(rate(_build(P, {"p0": 0.15})))["p0"]
    assert base.cr_delta > 0
    assert 0 < damp.cr_delta < base.cr_delta


def test_premade_factor_does_not_affect_losses() -> None:
    # p17 is on the last-place team (a loss, negative delta). Unchanged by the factor.
    base = _by_id(rate(_build(P)))["p17"]
    damp = _by_id(rate(_build(P, {"p17": 0.8})))["p17"]
    assert base.cr_delta < 0
    assert damp.cr_delta == base.cr_delta


def test_premade_factor_does_not_touch_sigma() -> None:
    base = _by_id(rate(_build(P)))["p0"]
    damp = _by_id(rate(_build(P, {"p0": 0.15})))["p0"]
    assert damp.sigma_after == base.sigma_after


def test_premade_factor_recorded_in_modifiers() -> None:
    damp = _by_id(rate(_build(P, {"p0": 0.15})))["p0"]
    assert damp.modifiers.party_factor < 1.0  # multiplier applied (1 - 0.15 = 0.85)
