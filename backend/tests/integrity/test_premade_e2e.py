"""End-to-end composition: co-occurrence -> evaluate_premade -> rate().

Proves the user-facing goal across the real engine: at the same winning
placement, an even premade earns LESS than solo, while a premade carrying a
lower-elo mate earns essentially the same as solo (the dampener backs off).
"""

from __future__ import annotations

from arena.integrity.evaluators import evaluate_premade
from arena.integrity.params import DEFAULT_INTEGRITY_PARAMS as IP
from arena.integrity.fingerprint import pair_key
from arena.integrity.types import MatchSnapshot, ParticipantSnapshot
from arena.rating import MatchInput, ParticipantInput, PlayerState, TeamInput, rate
from arena.rating.modifiers import to_cr
from arena.rating.params import DEFAULT_PARAMS

PR = DEFAULT_PARAMS


def _ps(pid: str, cr: float, mu: float = 1000.0, sigma: float = 200.0) -> PlayerState:
    return PlayerState(
        player_id=pid, mu=mu, sigma=sigma, cr=cr,
        current_streak=0, matches_played=20, placement_matches_remaining=0, peak_cr=cr,
    )


def _snapshot(states: dict[str, PlayerState], team_of: dict[str, int]) -> MatchSnapshot:
    return MatchSnapshot(
        match_id="m", mode="TRIOS", team_size=3, duration_seconds=600,
        participants=[
            ParticipantSnapshot(player_id=pid, team_id=team_of[pid], champion_id=0, cr=st.cr)
            for pid, st in states.items()
        ],
    )


def _winner_delta(states: dict[str, PlayerState], team_of: dict[str, int],
                  counts: dict[str, int], winner: str) -> float:
    """Run evaluate_premade + rate() for a 2-team TRIOS lobby; return winner cr_delta."""
    factors = evaluate_premade(_snapshot(states, team_of), counts, IP)
    teams: dict[int, list[ParticipantInput]] = {}
    for pid, st in states.items():
        teams.setdefault(team_of[pid], []).append(
            ParticipantInput(
                player_id=pid, state=st, champion_id=0, eligible_for_progression=True,
                party_penalty_factor=factors.get(pid, 0.0),
            )
        )
    # team 1 wins (placement 1), team 2 loses (placement 2).
    match = MatchInput(
        match_id="m", mode="TRIOS",
        teams=[TeamInput(team_id=t, placement=t, participants=ps) for t, ps in teams.items()],
        params=PR,
    )
    res = {pr.player_id: pr for pr in rate(match).players}
    return res[winner].cr_delta


def _even_lobby():
    # Two trios, all equal CR. Team 1 = {a,b,c}, team 2 = {d,e,f}.
    cr = to_cr(1000.0, 200.0, PR)
    states = {p: _ps(p, cr) for p in ("a", "b", "c", "d", "e", "f")}
    team_of = {"a": 1, "b": 1, "c": 1, "d": 2, "e": 2, "f": 2}
    return states, team_of


def test_even_premade_winner_earns_less_than_solo() -> None:
    states, team_of = _even_lobby()
    no_history = {pair_key(x, y): 1 for x in states for y in states if x < y}
    # Team 1 are a coordinated premade (every pair seen >= threshold).
    premade = dict(no_history)
    for x, y in (("a", "b"), ("a", "c"), ("b", "c")):
        premade[pair_key(x, y)] = IP.premade_repeat_threshold

    solo_gain = _winner_delta(states, team_of, no_history, "a")
    premade_gain = _winner_delta(states, team_of, premade, "a")
    assert solo_gain > 0
    assert premade_gain < solo_gain
    # ~15% strength on the positive mu-step => a few CR less, not a collapse.
    assert premade_gain > 0.5 * solo_gain


def test_carry_premade_winner_earns_like_solo() -> None:
    # Team 1 = strong carrier 'a' + two much lower-elo mates -> big CR spread ->
    # homogeneity ~0 -> dampener backs off even with full co-occurrence history.
    high = to_cr(1000.0, 200.0, PR)
    low = high - (IP.premade_homogeneity_gap + 200.0)
    states = {
        "a": _ps("a", high), "b": _ps("b", low), "c": _ps("c", low),
        "d": _ps("d", high), "e": _ps("e", high), "f": _ps("f", high),
    }
    team_of = {"a": 1, "b": 1, "c": 1, "d": 2, "e": 2, "f": 2}
    no_history = {pair_key(x, y): 1 for x in states for y in states if x < y}
    carry = dict(no_history)
    for x, y in (("a", "b"), ("a", "c"), ("b", "c")):
        carry[pair_key(x, y)] = IP.premade_repeat_threshold

    solo_gain = _winner_delta(states, team_of, no_history, "a")
    carry_gain = _winner_delta(states, team_of, carry, "a")
    assert carry_gain == solo_gain  # no dampening applied to the carrier
