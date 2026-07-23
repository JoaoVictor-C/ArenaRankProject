"""Production wiring of the premade dampener (no DB, no real Redis).

Covers the worker-side adapter that infers premades from co-occurrence and the
RatingService seam that maps the resulting factor onto the engine input.
"""

from __future__ import annotations

import pytest

from arena.rating.types import PlayerState
from arena.services.match_pipeline import EligibilityOnlyIntegrity, PremadeIntegrity
from arena.services.protocols import IntegrityVerdict, RawMatch, RawParticipant


def _state(pid: str, cr: float) -> PlayerState:
    return PlayerState(
        player_id=pid, mu=1000.0, sigma=200.0, cr=cr,
        current_streak=0, matches_played=20, placement_matches_remaining=0, peak_cr=cr,
    )


def _match(*parts: RawParticipant) -> RawMatch:
    return RawMatch(
        match_id="m", riot_match_id="BR1_1", season_id="s", mode="DUOS",
        queue_id=1700, played_at="2023-11-14T00:00:00+00:00", participants=list(parts),
    )


def _duos() -> RawMatch:
    return _match(
        RawParticipant(player_id="a", champion_id=1, team_id=1, placement=1),
        RawParticipant(player_id="b", champion_id=2, team_id=1, placement=1),
        RawParticipant(player_id="c", champion_id=3, team_id=2, placement=2),
        RawParticipant(player_id="d", champion_id=4, team_id=2, placement=2),
    )


class _FakePartyStore:
    def __init__(self, count: int) -> None:
        self._count = count

    async def observe(self, pair_keys, match_id, window_seconds):
        return {pk: self._count for pk in pair_keys}


# ---- IntegrityVerdict.party_for ---------------------------------------------


def test_verdict_party_for_defaults_to_zero() -> None:
    v = IntegrityVerdict()
    assert v.party_for("nobody") == 0.0
    assert v.party_for("x") == pytest.approx(0.0)


# ---- PremadeIntegrity adapter -----------------------------------------------


async def test_premade_integrity_scores_even_premade() -> None:
    from arena.integrity.params import DEFAULT_INTEGRITY_PARAMS as P

    states = {p: _state(p, 1000.0) for p in ("a", "b", "c", "d")}
    integ = PremadeIntegrity(set(), _FakePartyStore(count=P.premade_repeat_threshold))
    verdict = await integ.evaluate(_duos(), states)
    assert verdict.party_for("a") == pytest.approx(P.premade_strength)
    assert verdict.party_for("b") == pytest.approx(P.premade_strength)


async def test_premade_integrity_preserves_ineligible() -> None:
    states = {p: _state(p, 1000.0) for p in ("a", "b", "c", "d")}
    integ = PremadeIntegrity({"d"}, _FakePartyStore(count=9))
    verdict = await integ.evaluate(_duos(), states)
    assert verdict.is_eligible("d") is False
    assert verdict.is_eligible("a") is True


async def test_premade_integrity_no_store_means_no_dampening() -> None:
    states = {p: _state(p, 1000.0) for p in ("a", "b", "c", "d")}
    integ = PremadeIntegrity({"d"}, None)  # no Redis (e.g. redis=None path)
    verdict = await integ.evaluate(_duos(), states)
    assert verdict.party_factors == {}
    assert verdict.is_eligible("d") is False


async def test_premade_integrity_no_states_means_no_dampening() -> None:
    integ = PremadeIntegrity(set(), _FakePartyStore(count=9))
    verdict = await integ.evaluate(_duos(), None)  # states unavailable
    assert verdict.party_factors == {}


async def test_eligibility_only_accepts_states_arg() -> None:
    # Back-compat: widened protocol must not break the eligibility-only default.
    integ = EligibilityOnlyIntegrity({"id-4"})
    verdict = await integ.evaluate(_duos(), {"a": _state("a", 1000.0)})
    assert verdict.is_eligible("id-4") is False


# ---- RatingService maps the factor onto the engine input --------------------


def test_rating_service_maps_party_factor_into_engine_input() -> None:
    from arena.db import models as m
    from arena.services.rating_service import RatingService

    svc = RatingService(EligibilityOnlyIntegrity(set()))
    match = _duos()
    states = {
        p: m.PlayerSeason(
            player_id=p, season_id="s", mu=1000.0, sigma=200.0, cr=650.0,
            current_streak=0, matches_played=20, placement_matches_remaining=0, peak_cr=650.0,
        )
        for p in ("a", "b", "c", "d")
    }
    verdict = IntegrityVerdict(party_factors={"a": 0.15})
    match_input = svc._build_match_input(match, verdict, states)
    by_id = {pt.player_id: pt for t in match_input.teams for pt in t.participants}
    assert by_id["a"].party_penalty_factor == pytest.approx(0.15)
    assert by_id["b"].party_penalty_factor == pytest.approx(0.0)
