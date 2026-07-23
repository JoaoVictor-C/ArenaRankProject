"""Engine-level integration of the PDL cap layer (option B-pure, no ledger).

When ``RatingParams.caps`` is set, ``rate()`` clamps each eligible player's per-match
cr_delta to the placement-relative PDL bound by adjusting mu_after so the displayed
CR identity ``cr = mu - 3*sigma + 250`` is preserved exactly (valid because arenarank
runs no matchmaking — mu has no posterior-coherence consumer). caps=None leaves the
engine unchanged.
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
from arena.rating.caps import CAPS_8, SYMMETRIC_CAPS_6, CapParams
from arena.rating.modifiers import to_cr
from arena.rating.params import DEFAULT_PARAMS

CP = CapParams(base_cap_by_placement={**SYMMETRIC_CAPS_6, **CAPS_8})


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


def _build(p) -> MatchInput:
    """6 teams x 3 fresh players, placements 1..6."""
    teams = []
    pid = 0
    for placement in range(1, 7):
        parts = []
        for _ in range(3):
            parts.append(
                ParticipantInput(
                    player_id=f"p{pid}",
                    state=_fresh(f"p{pid}", p),
                    champion_id=0,
                    eligible_for_progression=True,
                )
            )
            pid += 1
        teams.append(TeamInput(team_id=placement, placement=placement, participants=parts))
    return MatchInput(match_id="t", mode="TRIOS", teams=teams, params=p)


def _placement_of(match: MatchInput) -> dict[str, int]:
    return {pt.player_id: t.placement for t in match.teams for pt in t.participants}


def test_caps_off_leaves_deltas_uncapped() -> None:
    res = rate(_build(replace(DEFAULT_PARAMS, caps=None)))  # explicitly disable the cap layer
    deltas = [pr.cr_delta for pr in res.players if pr.eligible]
    # fresh 6x3 match: top placement gains exceed the 40 base cap (per real data, +59)
    assert max(deltas) > 40.0


def test_caps_on_clamps_into_envelope() -> None:
    p = replace(DEFAULT_PARAMS, caps=CP)
    res = rate(_build(p))
    for pr in res.players:
        if not pr.eligible:
            continue
        # win side may rise to base*1.25 (mismatch) -> global ceiling 50; loss floor -40
        assert -40.0 - 0.01 <= pr.cr_delta <= 50.0 + 0.01


def test_caps_on_preserves_cr_identity() -> None:
    p = replace(DEFAULT_PARAMS, caps=CP)
    res = rate(_build(p))
    for pr in res.players:
        if not pr.eligible:
            continue
        assert abs(pr.cr_after - to_cr(pr.mu_after, pr.sigma_after, p)) < 1e-6
        assert abs(pr.cr_delta - (pr.cr_after - pr.cr_before)) < 1e-6


def test_caps_actually_change_outcome() -> None:
    res_off = rate(_build(DEFAULT_PARAMS))
    res_on = rate(_build(replace(DEFAULT_PARAMS, caps=CP)))
    off = {pr.player_id: pr.cr_delta for pr in res_off.players}
    changed = [pr.player_id for pr in res_on.players if abs(pr.cr_delta - off[pr.player_id]) > 0.1]
    assert changed  # at least one player's delta was clamped
