"""Golden-output invariance test for the Bug A / Bug B engine fix (Raio-X transparency work).

``engine.py`` has two variable-shadowing bugs (see ``arena/rating/caps.py::decide_pdl_cap``
and the engine docstring once fixed): ``scf`` is reassigned from the soft-cap factor to
``high_cr_scale`` before being recorded, and ``clamped`` is reassigned from the dispersion
flag to the PDL-cap-or-floor flag before being recorded. Both pollute ONLY the persisted
``AppliedModifiers`` snapshot — neither value feeds back into any arithmetic that produces
``mu_after`` / ``sigma_after`` / ``cr_after`` / ``cr_delta``. Fixing them must therefore be
bit-for-bit output-neutral: this file is the proof, so the fix can ship WITHOUT a rerate of
the ~86k matches / ~1.5M participant rows already in production (a full rerate costs ~2h+
and previously caused a replication incident — see git history around 2026-08-03).

``rate_outputs.json`` was captured from the engine BEFORE the fix landed, across a matrix of
matches designed to exercise every branch that could plausibly be perturbed by a refactor
near the shadowed variables: caps on/off, trios/duos, fresh/veteran states, streaks (both
signs, both sides of the threshold), the provisional window, boosting/party factors (partial
and saturated), ineligible participants (including a fully-voided match), a skill-mismatch
lobby (exercises ``mismatch_override``), a high-CR lobby (exercises ``high_cr_scale`` across
its sigmoid range), an artificially very-high-CR winner (exercises the REAL
``soft_cap_factor`` branch, which production CR never reaches), the mu-space dispersion cap,
the CR-space zero floor, and tied placements.

To regenerate the golden file (only ever do this deliberately, from the KNOWN-GOOD engine —
i.e. before touching engine.py, or after re-verifying a rating-output change was intentional
and separately reviewed):

    uv run python tests/rating/test_bugfix_output_invariance.py --regen
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from arena.rating import (
    MatchInput,
    ParticipantInput,
    PlayerState,
    TeamInput,
    rate,
)
from arena.rating.modifiers import to_cr
from arena.rating.params import DEFAULT_PARAMS, RatingParams

GOLDEN_PATH = Path(__file__).parent / "golden" / "rate_outputs.json"

CAPS_ON = DEFAULT_PARAMS
CAPS_OFF = replace(DEFAULT_PARAMS, caps=None)


def _state(
    p: RatingParams,
    pid: str,
    *,
    mu: float | None = None,
    sigma: float | None = None,
    streak: int = 0,
    matches: int = 50,
    remaining: int = 0,
) -> PlayerState:
    mu_v = p.mu0 if mu is None else mu
    sigma_v = p.sigma0 if sigma is None else sigma
    cr = to_cr(mu_v, sigma_v, p)
    return PlayerState(
        player_id=pid,
        mu=mu_v,
        sigma=sigma_v,
        cr=cr,
        current_streak=streak,
        matches_played=matches,
        placement_matches_remaining=remaining,
        peak_cr=cr,
    )


def _match(
    match_id: str,
    p: RatingParams,
    team_count: int,
    *,
    placements: list[int] | None = None,
    states: dict[int, PlayerState] | None = None,
    boosting: dict[int, float] | None = None,
    party: dict[int, float] | None = None,
    ineligible: set[int] | None = None,
    mode: str = "TRIOS",
) -> MatchInput:
    """One participant per team (team_count teams). ``placements`` overrides the default
    1..team_count permutation (allows ties / gaps). ``states``/``boosting``/``party``/
    ``ineligible`` are keyed by the 0-indexed team slot."""
    placements = placements or list(range(1, team_count + 1))
    states = states or {}
    boosting = boosting or {}
    party = party or {}
    ineligible = ineligible or set()

    teams = []
    for i in range(team_count):
        pid = f"{match_id}_p{i}"
        st = states.get(i) or _state(p, pid)
        part = ParticipantInput(
            player_id=pid,
            state=st,
            champion_id=0,
            eligible_for_progression=i not in ineligible,
            boosting_penalty_factor=boosting.get(i, 0.0),
            party_penalty_factor=party.get(i, 0.0),
        )
        teams.append(TeamInput(team_id=i, placement=placements[i], participants=[part]))
    return MatchInput(match_id=match_id, mode=mode, teams=teams, params=p)


def build_matrix() -> dict[str, MatchInput]:
    matches: dict[str, MatchInput] = {}

    # A/B — trios, fresh, caps off/on.
    matches["trios_fresh_caps_off"] = _match("trios_fresh_caps_off", CAPS_OFF, 6)
    matches["trios_fresh_caps_on"] = _match("trios_fresh_caps_on", CAPS_ON, 6)

    # C/D — duos, fresh, caps on/off.
    matches["duos_fresh_caps_on"] = _match("duos_fresh_caps_on", CAPS_ON, 8, mode="DUOS")
    matches["duos_fresh_caps_off"] = _match("duos_fresh_caps_off", CAPS_OFF, 8, mode="DUOS")

    # E/F — veteran, varied streaks (both signs, spanning the threshold=3).
    streak_states_on = {i: _state(CAPS_ON, f"s{i}", mu=1000.0, sigma=90.0, streak=s) for i, s in enumerate([-5, -3, -1, 1, 3, 5])}
    matches["trios_veteran_streaks_caps_on"] = _match(
        "trios_veteran_streaks_caps_on", CAPS_ON, 6, states=streak_states_on
    )
    streak_states_off = {i: _state(CAPS_OFF, f"s{i}", mu=1000.0, sigma=90.0, streak=s) for i, s in enumerate([-5, -3, -1, 1, 3, 5])}
    matches["trios_veteran_streaks_caps_off"] = _match(
        "trios_veteran_streaks_caps_off", CAPS_OFF, 6, states=streak_states_off
    )

    # G — provisional window mixed with converged players.
    prov_states = {
        i: _state(CAPS_ON, f"pr{i}", mu=1000.0, sigma=90.0, remaining=(10 if i % 2 == 0 else 0))
        for i in range(6)
    }
    matches["trios_provisional_mix_caps_on"] = _match(
        "trios_provisional_mix_caps_on", CAPS_ON, 6, states=prov_states
    )

    # H/I — boosting factor spread, caps on/off.
    boosting_map = {0: 0.0, 1: 0.25, 2: 0.5, 3: 0.75, 4: 1.0, 5: 0.0}
    matches["trios_boosting_flagged_caps_on"] = _match(
        "trios_boosting_flagged_caps_on", CAPS_ON, 6, boosting=boosting_map
    )
    matches["trios_boosting_flagged_caps_off"] = _match(
        "trios_boosting_flagged_caps_off", CAPS_OFF, 6, boosting=boosting_map
    )

    # J — party factor spread.
    party_map = {0: 0.0, 1: 0.3, 2: 0.6, 3: 1.0, 4: 0.0, 5: 0.5}
    matches["trios_party_flagged_caps_on"] = _match(
        "trios_party_flagged_caps_on", CAPS_ON, 6, party=party_map
    )

    # K — ineligible participants scattered through a lobby (not fully voided).
    matches["trios_ineligible_mixed_caps_on"] = _match(
        "trios_ineligible_mixed_caps_on", CAPS_ON, 6, ineligible={1, 4}
    )

    # L — every participant ineligible (voided path).
    matches["trios_all_ineligible_voided"] = _match(
        "trios_all_ineligible_voided", CAPS_ON, 6, ineligible={0, 1, 2, 3, 4, 5}
    )

    # M — skill-mismatch lobby: one high-mu player among low-mu opponents (mismatch_override).
    mismatch_states = {0: _state(CAPS_ON, "mm0", mu=1800.0, sigma=80.0, matches=60)}
    for i in range(1, 6):
        mismatch_states[i] = _state(CAPS_ON, f"mm{i}", mu=900.0, sigma=90.0, matches=60)
    matches["trios_skill_mismatch_caps_on"] = _match(
        "trios_skill_mismatch_caps_on", CAPS_ON, 6, states=mismatch_states
    )

    # N — high-CR lobby spanning the high_cr_scale sigmoid's midpoint (1380).
    high_cr_states = {
        i: _state(CAPS_ON, f"hc{i}", mu=mu, sigma=100.0, matches=80)
        for i, mu in enumerate([1200.0, 1500.0, 1800.0, 2100.0, 2400.0, 2700.0])
    }
    matches["trios_high_cr_scale_caps_on"] = _match(
        "trios_high_cr_scale_caps_on", CAPS_ON, 6, states=high_cr_states
    )

    # O — an artificially very-high-CR winner: cr_before > soft_cap_threshold (5000), which
    # exercises the REAL M.soft_cap_factor branch (unreachable in production CR ranges).
    extreme_states = {0: _state(CAPS_ON, "ex0", mu=5000.0, sigma=50.0, matches=100)}
    for i in range(1, 6):
        extreme_states[i] = _state(CAPS_ON, f"ex{i}", mu=1000.0, sigma=90.0)
    matches["trios_extreme_soft_cap_caps_on"] = _match(
        "trios_extreme_soft_cap_caps_on",
        CAPS_ON,
        6,
        states=extreme_states,
        placements=[1, 2, 3, 4, 5, 6],
    )

    # P — duos: boosting + party combined.
    matches["duos_boosting_and_party_combo_caps_on"] = _match(
        "duos_boosting_and_party_combo_caps_on",
        CAPS_ON,
        8,
        mode="DUOS",
        boosting={0: 0.5, 2: 1.0, 4: 0.2},
        party={1: 0.4, 3: 0.8, 6: 1.0},
    )

    # Q/R — extreme mu spread to blow past the mu-space dispersion cap, caps off/on.
    disp_states = {0: _state(CAPS_ON, "d0", mu=3000.0, sigma=90.0, matches=100)}
    for i in range(1, 6):
        disp_states[i] = _state(CAPS_ON, f"d{i}", mu=100.0, sigma=90.0, matches=100)
    matches["trios_dispersion_trigger_caps_off"] = _match(
        "trios_dispersion_trigger_caps_off",
        CAPS_OFF,
        6,
        states={i: replace(st, player_id=f"do{i}") for i, st in disp_states.items()},
        placements=[6, 1, 2, 3, 4, 5],  # the high-mu player placed LAST -> big negative delta
    )
    matches["trios_dispersion_trigger_caps_on"] = _match(
        "trios_dispersion_trigger_caps_on",
        CAPS_ON,
        6,
        states=disp_states,
        placements=[6, 1, 2, 3, 4, 5],
    )

    # S — a player who ALREADY has negative pre-match CR (historically real: the pre-
    # recalibration engine produced this for 15.8% of players, see params.py's docstring)
    # placed last among much stronger opponents, so the additional loss is small but
    # cr_after stays negative -> triggers the CR-space zero floor (re-floored to 0.0,
    # mu_after re-derived). cr is set directly (bypassing to_cr) to construct the edge
    # case regardless of the current engine's ability to reach it organically.
    zero_floor_states = {
        0: replace(_state(CAPS_ON, "zf0", mu=10.0, sigma=100.0, matches=100), cr=-40.0)
    }
    for i in range(1, 8):
        zero_floor_states[i] = _state(CAPS_ON, f"zf{i}", mu=1200.0, sigma=90.0, matches=100)
    matches["duos_zero_floor_trigger_caps_on"] = _match(
        "duos_zero_floor_trigger_caps_on",
        CAPS_ON,
        8,
        mode="DUOS",
        states=zero_floor_states,
        placements=[8, 1, 2, 3, 4, 5, 6, 7],
    )

    # T — tied placements (two teams sharing placement=3, placement 4 skipped).
    matches["trios_ties_in_placement_caps_on"] = _match(
        "trios_ties_in_placement_caps_on",
        CAPS_ON,
        6,
        placements=[1, 2, 3, 3, 5, 6],
    )

    # U — negative streak reinforced by another loss (loss-dampener branch, sign<0).
    loss_streak_states = {
        i: _state(CAPS_ON, f"ls{i}", mu=1000.0, sigma=90.0, streak=-4)
        for i in range(6)
    }
    matches["trios_negative_streak_loss_caps_on"] = _match(
        "trios_negative_streak_loss_caps_on", CAPS_ON, 6, states=loss_streak_states
    )

    # V — clean win-streak reinforcement, caps off (isolates the mu-space modifier).
    win_streak_states = {
        i: _state(CAPS_OFF, f"ws{i}", mu=1000.0, sigma=90.0, streak=4)
        for i in range(6)
    }
    matches["trios_positive_streak_win_caps_off"] = _match(
        "trios_positive_streak_win_caps_off", CAPS_OFF, 6, states=win_streak_states
    )

    # W — kitchen sink: duos, mixed mu/sigma/streak/provisional/boosting/party/ineligible.
    sink_states = {
        0: _state(CAPS_ON, "ks0", mu=1900.0, sigma=70.0, streak=3, matches=120),
        1: _state(CAPS_ON, "ks1", mu=700.0, sigma=180.0, streak=-2, remaining=6),
        2: _state(CAPS_ON, "ks2", mu=1300.0, sigma=95.0, streak=1),
        3: _state(CAPS_ON, "ks3", mu=1000.0, sigma=200.0, remaining=10),
        4: _state(CAPS_ON, "ks4", mu=1600.0, sigma=110.0, streak=-4),
        5: _state(CAPS_ON, "ks5", mu=400.0, sigma=90.0, streak=5),
        6: _state(CAPS_ON, "ks6", mu=1000.0, sigma=90.0),
        7: _state(CAPS_ON, "ks7", mu=2200.0, sigma=60.0, matches=150),
    }
    matches["duos_kitchen_sink_caps_on"] = _match(
        "duos_kitchen_sink_caps_on",
        CAPS_ON,
        8,
        mode="DUOS",
        states=sink_states,
        boosting={0: 0.6},
        party={5: 0.5, 6: 0.5},
        ineligible={3},
    )

    return matches


def _serialize(matches: dict[str, MatchInput]) -> dict[str, object]:
    out: dict[str, object] = {}
    for match_id, m in matches.items():
        result = rate(m)
        players = {}
        for pr in result.players:
            players[pr.player_id] = {
                "mu_after": pr.mu_after,
                "sigma_after": pr.sigma_after,
                "cr_after": pr.cr_after,
                "cr_delta": pr.cr_delta,
                "eligible": pr.eligible,
                "is_win": pr.is_win,
                "new_streak": pr.new_streak,
            }
        out[match_id] = {"voided": result.voided, "players": players}
    return out


def _regenerate() -> None:
    matrix = build_matrix()
    payload = _serialize(matrix)
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {len(payload)} matches to {GOLDEN_PATH}")


@pytest.fixture(scope="module")
def golden() -> dict[str, object]:
    if not GOLDEN_PATH.exists():
        pytest.fail(
            f"{GOLDEN_PATH} is missing. Regenerate from a KNOWN-GOOD engine with: "
            f"uv run python tests/rating/test_bugfix_output_invariance.py --regen"
        )
    data: dict[str, object] = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    return data


def test_golden_file_covers_the_full_matrix(golden: dict[str, object]) -> None:
    assert set(golden.keys()) == set(build_matrix().keys())


def test_rate_output_matches_golden_exactly(golden: dict[str, object]) -> None:
    matrix = build_matrix()
    actual = _serialize(matrix)
    for match_id, expected_match in golden.items():
        assert match_id in actual, f"missing match {match_id!r} in current output"
        expected = expected_match  # type: ignore[assignment]
        got = actual[match_id]
        assert got["voided"] == expected["voided"], f"{match_id}: voided flag changed"  # type: ignore[index]
        expected_players = expected["players"]  # type: ignore[index]
        got_players = got["players"]  # type: ignore[index]
        assert set(got_players.keys()) == set(expected_players.keys()), (
            f"{match_id}: player set changed"
        )
        for pid, exp in expected_players.items():
            act = got_players[pid]
            for field in ("mu_after", "sigma_after", "cr_after", "cr_delta"):
                assert act[field] == pytest.approx(exp[field], abs=1e-12), (
                    f"{match_id}/{pid}.{field}: {act[field]!r} != golden {exp[field]!r}"
                )
            for field in ("eligible", "is_win", "new_streak"):
                assert act[field] == exp[field], (
                    f"{match_id}/{pid}.{field}: {act[field]!r} != golden {exp[field]!r}"
                )


if __name__ == "__main__":
    if "--regen" in sys.argv:
        _regenerate()
    else:
        print(__doc__)
        sys.exit(1)
