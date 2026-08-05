"""Reconciliation and sign-semantics tests for ``arena/rating/explain.py``.

The headline invariant: for every player in every match, ``sum(entry.pdl for entry
in explanation.entries) == cr_delta`` (to float precision). This file proves that
holds for the fresh-result path (``explain_result``, Tier A / ``fidelity="exato"``)
across the full Phase-0 fixture matrix (chosen because it already exercises every
branch that matters here: caps on/off, trios/duos, streaks both signs, the
provisional window, boosting/party factors, ineligible/voided players, a
skill-mismatch lobby, a high-CR lobby, an artificially very-high-CR winner, the
mu-space dispersion cap, the CR-space zero floor, and tied placements) plus a
forced-bound grid targeting each cap rule individually. Legacy (Tier B)
reconstruction is covered separately in ``test_explain_legacy.py``.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_bugfix_output_invariance import build_matrix  # noqa: E402

from arena.rating import (  # noqa: E402
    MatchInput,
    ParticipantInput,
    PlayerState,
    TeamInput,
    rate,
)
from arena.rating.explain import explain_result  # noqa: E402
from arena.rating.modifiers import to_cr  # noqa: E402
from arena.rating.params import DEFAULT_PARAMS  # noqa: E402

_EPS = 1e-6


def _reconcile(match: MatchInput):
    """Yield (participant, placement, explanation) for every player in a rated match."""
    result = rate(match)
    placement_by_pid = {pt.player_id: t.placement for t in match.teams for pt in t.participants}
    team_count = len(match.teams)
    for pr in result.players:
        exp = explain_result(match.params, placement_by_pid[pr.player_id], team_count, pr)
        yield pr, exp


# ---------------------------------------------------------------------------
# Reconciliation across the full Phase-0 fixture matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("match_id", sorted(build_matrix().keys()))
def test_ledger_reconciles_exactly_across_the_fixture_matrix(match_id: str) -> None:
    matrix = build_matrix()
    for pr, exp in _reconcile(matrix[match_id]):
        ledger_sum = sum(e.pdl for e in exp.entries)
        assert ledger_sum == pytest.approx(pr.cr_delta, abs=_EPS), (
            f"{match_id}/{pr.player_id}: ledger sums to {ledger_sum!r}, "
            f"cr_delta is {pr.cr_delta!r}"
        )
        assert exp.residual == pytest.approx(0.0, abs=_EPS)


@pytest.mark.parametrize("match_id", sorted(build_matrix().keys()))
def test_fresh_results_are_always_exato(match_id: str) -> None:
    """Every eligible OR frozen player rated through explain_result has full
    persisted facts -> fidelity is always "exato", never "derivado"/"parcial"."""
    matrix = build_matrix()
    for _pr, exp in _reconcile(matrix[match_id]):
        assert exp.fidelity == "exato"
        assert exp.unrecoverable == ()


def test_ineligible_players_get_an_empty_reconciling_ledger() -> None:
    matrix = build_matrix()
    match = matrix["trios_ineligible_mixed_caps_on"]
    for pr, exp in _reconcile(match):
        if pr.eligible:
            continue
        assert pr.cr_delta == 0.0
        assert exp.entries == []
        assert exp.cap.active is False
        assert sum(e.pdl for e in exp.entries) == pytest.approx(pr.cr_delta, abs=_EPS)


def test_voided_match_all_players_reconcile_trivially() -> None:
    matrix = build_matrix()
    match = matrix["trios_all_ineligible_voided"]
    for pr, exp in _reconcile(match):
        assert exp.entries == []
        assert exp.residual == pytest.approx(0.0, abs=_EPS)


# ---------------------------------------------------------------------------
# Entry order is fixed and documented
# ---------------------------------------------------------------------------


def test_chain_entry_order_is_fixed() -> None:
    matrix = build_matrix()
    match = matrix["trios_boosting_flagged_caps_on"]
    for pr, exp in _reconcile(match):
        if not pr.eligible:
            continue
        chain_kinds = [e.kind for e in exp.entries[:8]]
        assert chain_kinds == [
            "base",
            "placement",
            "provisional",
            "streak",
            "soft_cap",
            "boosting",
            "party",
            "dispersion",
        ]
        # confidence always follows the chain+dispersion block when not lumped.
        remaining = [e.kind for e in exp.entries[8:]]
        assert remaining[0] in ("confidence",)


# ---------------------------------------------------------------------------
# Forced cap outcomes — each rule individually, each reconciling and reporting
# the right bound.
# ---------------------------------------------------------------------------


def _fresh(pid: str, p, mu: float | None = None, sigma: float | None = None) -> PlayerState:
    mu_v = p.mu0 if mu is None else mu
    sigma_v = p.sigma0 if sigma is None else sigma
    cr = to_cr(mu_v, sigma_v, p)
    return PlayerState(
        player_id=pid,
        mu=mu_v,
        sigma=sigma_v,
        cr=cr,
        current_streak=0,
        matches_played=0,
        placement_matches_remaining=0,
        peak_cr=cr,
    )


def _six_player_match(match_id: str, p, *, boosting: dict[int, float] | None = None) -> MatchInput:
    """6 teams x1 fresh player, placements 1..6 — reliably produces a big spread of
    raw deltas (fresh players => large PL surprise), so every cap rule fires
    somewhere in the lobby."""
    boosting = boosting or {}
    teams = []
    for i, placement in enumerate(range(1, 7)):
        pid = f"{match_id}_p{i}"
        part = ParticipantInput(
            player_id=pid,
            state=_fresh(pid, p),
            champion_id=0,
            eligible_for_progression=True,
            boosting_penalty_factor=boosting.get(i, 0.0),
        )
        teams.append(TeamInput(team_id=i, placement=placement, participants=[part]))
    return MatchInput(match_id=match_id, mode="TRIOS", teams=teams, params=p)


def test_forced_gain_cap_reconciles_and_reports_bound() -> None:
    match = _six_player_match("gaincap", DEFAULT_PARAMS)
    for pr, exp in _reconcile(match):
        if exp.cap.bound == "gain_cap":
            assert exp.cap.gain_cap is not None
            assert pr.cr_delta == pytest.approx(exp.cap.gain_cap, abs=_EPS)
            assert sum(e.pdl for e in exp.entries) == pytest.approx(pr.cr_delta, abs=_EPS)
            return
    pytest.fail("no player hit the gain cap in this fixture; strengthen the matchup")


def test_forced_loss_cap_reconciles_and_reports_bound() -> None:
    # A very-high-mu player placed dead last is a big surprise loss -> loss cap.
    p = DEFAULT_PARAMS
    teams = []
    strong = ParticipantInput(
        player_id="lc_strong", state=_fresh("lc_strong", p, mu=2000.0, sigma=80.0),
        champion_id=0, eligible_for_progression=True,
    )
    teams.append(TeamInput(team_id=0, placement=6, participants=[strong]))
    for i in range(1, 6):
        pid = f"lc_weak{i}"
        part = ParticipantInput(
            player_id=pid, state=_fresh(pid, p, mu=700.0, sigma=90.0),
            champion_id=0, eligible_for_progression=True,
        )
        teams.append(TeamInput(team_id=i, placement=i, participants=[part]))
    match = MatchInput(match_id="losscap", mode="TRIOS", teams=teams, params=p)

    pr, exp = next((pr, exp) for pr, exp in _reconcile(match) if pr.player_id == "lc_strong")
    assert exp.cap.bound == "loss_cap"
    assert exp.cap.loss_cap is not None
    assert pr.cr_delta == pytest.approx(exp.cap.loss_cap, abs=_EPS)
    assert sum(e.pdl for e in exp.entries) == pytest.approx(pr.cr_delta, abs=_EPS)


def test_forced_min_gain_floor_reconciles_and_reports_bound() -> None:
    # A very-high-mu winner: the PL delta for winning is tiny (expected outcome),
    # so the raw gain is hollow -> the placement-1 minimum-gain floor lifts it.
    p = DEFAULT_PARAMS
    teams = []
    strong = ParticipantInput(
        player_id="mg_strong", state=_fresh("mg_strong", p, mu=3000.0, sigma=60.0),
        champion_id=0, eligible_for_progression=True,
    )
    teams.append(TeamInput(team_id=0, placement=1, participants=[strong]))
    for i in range(1, 6):
        pid = f"mg_weak{i}"
        part = ParticipantInput(
            player_id=pid, state=_fresh(pid, p, mu=700.0, sigma=90.0),
            champion_id=0, eligible_for_progression=True,
        )
        teams.append(TeamInput(team_id=i, placement=i + 1, participants=[part]))
    match = MatchInput(match_id="mingain", mode="TRIOS", teams=teams, params=p)

    pr, exp = next((pr, exp) for pr, exp in _reconcile(match) if pr.player_id == "mg_strong")
    assert exp.cap.bound == "min_gain"
    assert exp.cap.min_gain is not None
    assert pr.cr_delta == pytest.approx(exp.cap.min_gain, abs=_EPS)
    assert sum(e.pdl for e in exp.entries) == pytest.approx(pr.cr_delta, abs=_EPS)


def test_forced_dispersion_reconciles() -> None:
    matrix = build_matrix()
    match = matrix["trios_dispersion_trigger_caps_off"]
    hit_dispersion = False
    for pr, exp in _reconcile(match):
        disp_entry = next(e for e in exp.entries if e.kind == "dispersion")
        if abs(disp_entry.pdl) > _EPS:
            hit_dispersion = True
            assert sum(e.pdl for e in exp.entries) == pytest.approx(pr.cr_delta, abs=_EPS)
    assert hit_dispersion, "no player's dispersion entry fired; strengthen the matchup"


def test_forced_zero_floor_reconciles_and_labels_exact() -> None:
    matrix = build_matrix()
    match = matrix["duos_zero_floor_trigger_caps_on"]
    pr, exp = next(
        (pr, exp)
        for pr, exp in _reconcile(match)
        if pr.player_id == "duos_zero_floor_trigger_caps_on_p0"
    )
    assert pr.cr_after == 0.0
    zero_floor_entries = [e for e in exp.entries if e.kind == "zero_floor"]
    assert len(zero_floor_entries) == 1
    assert zero_floor_entries[0].exact is True
    assert exp.fidelity == "exato"
    assert sum(e.pdl for e in exp.entries) == pytest.approx(pr.cr_delta, abs=_EPS)


def test_caps_disabled_never_reports_a_bound() -> None:
    p = replace(DEFAULT_PARAMS, caps=None)
    match = _six_player_match("nocaps", p)
    for pr, exp in _reconcile(match):
        assert exp.cap.active is False
        assert exp.cap.bound == "none"
        assert sum(e.pdl for e in exp.entries) == pytest.approx(pr.cr_delta, abs=_EPS)


# ---------------------------------------------------------------------------
# Sign semantics — the single most misreadable number in the feature.
# ---------------------------------------------------------------------------


def test_loss_streak_dampener_on_a_loss_is_a_positive_entry() -> None:
    """A player on a losing streak who loses AGAIN gets a dampened (smaller-
    magnitude) loss than an identical player with no streak. In additive PDL
    terms that dampening shows up as a POSITIVE streak-entry ("you lost less"),
    not a penalty — the most misreadable sign in the whole feature."""
    p = replace(DEFAULT_PARAMS, caps=None)  # isolate the mu-space modifier
    teams_baseline = []
    teams_streaking = []
    for i, placement in enumerate(range(1, 7)):
        base_state = _fresh(f"base_p{i}", p, mu=1000.0, sigma=90.0)
        streak_state = replace(base_state, player_id=f"streak_p{i}", current_streak=-4)
        teams_baseline.append(
            TeamInput(
                team_id=i,
                placement=placement,
                participants=[
                    ParticipantInput(
                        player_id=f"base_p{i}", state=base_state, champion_id=0,
                        eligible_for_progression=True,
                    )
                ],
            )
        )
        teams_streaking.append(
            TeamInput(
                team_id=i,
                placement=placement,
                participants=[
                    ParticipantInput(
                        player_id=f"streak_p{i}", state=streak_state, champion_id=0,
                        eligible_for_progression=True,
                    )
                ],
            )
        )
    baseline = rate(MatchInput(match_id="baseline", mode="TRIOS", teams=teams_baseline, params=p))
    streaking = rate(MatchInput(match_id="streaking", mode="TRIOS", teams=teams_streaking, params=p))

    # The last-place player (index 5, placement=6) is the clean loss case: a loss
    # streak reinforced by another loss.
    base_last = next(pr for pr in baseline.players if pr.player_id == "base_p5")
    streak_last = next(pr for pr in streaking.players if pr.player_id == "streak_p5")
    assert base_last.cr_delta < 0.0
    assert streak_last.cr_delta < 0.0
    # Dampened loss -> smaller-magnitude negative cr_delta than the undampened one.
    assert streak_last.cr_delta > base_last.cr_delta

    exp = explain_result(p, 6, 6, streak_last)
    streak_entry = next(e for e in exp.entries if e.kind == "streak")
    assert streak_entry.pdl > 0.0, "loss-streak dampener on a loss must be a POSITIVE entry"
    assert sum(e.pdl for e in exp.entries) == pytest.approx(streak_last.cr_delta, abs=_EPS)


def test_min_gain_floor_entry_is_positive_not_a_penalty() -> None:
    p = DEFAULT_PARAMS
    teams = []
    strong = ParticipantInput(
        player_id="pos_strong", state=_fresh("pos_strong", p, mu=3000.0, sigma=60.0),
        champion_id=0, eligible_for_progression=True,
    )
    teams.append(TeamInput(team_id=0, placement=1, participants=[strong]))
    for i in range(1, 6):
        pid = f"pos_weak{i}"
        part = ParticipantInput(
            player_id=pid, state=_fresh(pid, p, mu=700.0, sigma=90.0),
            champion_id=0, eligible_for_progression=True,
        )
        teams.append(TeamInput(team_id=i, placement=i + 1, participants=[part]))
    match = MatchInput(match_id="posfloor", mode="TRIOS", teams=teams, params=p)
    pr, exp = next((pr, exp) for pr, exp in _reconcile(match) if pr.player_id == "pos_strong")
    assert exp.cap.bound == "min_gain"
    cap_entry = next(e for e in exp.entries if e.kind == "cap")
    assert cap_entry.pdl > 0.0, "the minimum-gain floor is a BONUS, must be a positive entry"
