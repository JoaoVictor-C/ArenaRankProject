"""Pure unit tests for the worker write-path normalization (no DB / Redis)."""

from __future__ import annotations

from typing import Any

import pytest

import arena.services.match_pipeline as mp
from arena.riot.arena import parse_arena_match
from arena.services.match_pipeline import (
    EligibilityOnlyIntegrity,
    before_cutoff,
    build_raw_participants,
    deterministic_match_id,
    played_at_iso,
)
from arena.services.protocols import RawMatch


def _arena_payload(*, started_ms: int = 1_700_000_000_000) -> dict[str, Any]:
    """A minimal but valid 2-subteam DUOS (queue 1700) match-v5 payload."""

    def part(puuid: str, sub: int, place: int, champ: int, **extra: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "puuid": puuid,
            "riotIdGameName": puuid.upper(),
            "riotIdTagline": "BR1",
            "championId": champ,
            "playerSubteamId": sub,
            "subteamPlacement": place,
            "profileIcon": 23,
            "timePlayed": 600,
            "gameEndedInEarlySurrender": False,
        }
        base.update(extra)
        return base

    return {
        "metadata": {"matchId": "BR1_TEST_0001"},
        "info": {
            "queueId": 1700,
            "gameDuration": 600,
            "gameStartTimestamp": started_ms,
            "participants": [
                part("p1", 1, 1, 11),
                part("p2", 1, 1, 22),
                part("p3", 2, 2, 33),
                part("p4", 2, 2, 44, gameEndedInEarlySurrender=True),  # ineligible
            ],
        },
    }


def test_build_raw_participants_maps_subteams_placement_and_eligibility() -> None:
    parsed = parse_arena_match(_arena_payload())
    id_map = {"p1": "id-1", "p2": "id-2", "p3": "id-3", "p4": "id-4"}

    participants, ineligible = build_raw_participants(parsed, lambda pu: id_map[pu])

    assert len(participants) == 4
    by_id = {p.player_id: p for p in participants}
    assert by_id["id-1"].team_id == 1
    assert by_id["id-1"].placement == 1
    assert by_id["id-1"].champion_id == 11
    assert by_id["id-3"].team_id == 2
    assert by_id["id-3"].placement == 2
    # p4 surrendered early -> frozen by the transport-level eligibility gate.
    assert ineligible == {"id-4"}


def test_deterministic_match_id_is_stable_and_distinct() -> None:
    a = deterministic_match_id("BR1_123")
    assert a == deterministic_match_id("BR1_123")  # stable -> idempotency works
    assert a != deterministic_match_id("BR1_124")
    assert len(a) == 36 and a.count("-") == 4  # looks like a uuid


def test_played_at_uses_real_start_timestamp() -> None:
    # 1.7e12 ms == 1_700_000_000 s == 2023-11-14T22:13:20+00:00.
    iso = played_at_iso(parse_arena_match(_arena_payload(started_ms=1_700_000_000_000)))
    assert iso.startswith("2023-11-14")


def test_played_at_falls_back_to_now_when_missing() -> None:
    payload = _arena_payload()
    payload["info"]["gameStartTimestamp"] = 0
    payload["info"]["gameCreation"] = 0
    payload["info"]["gameEndTimestamp"] = 0
    iso = played_at_iso(parse_arena_match(payload))
    assert iso and "T" in iso  # a valid ISO timestamp (current time)


def test_before_cutoff_policy() -> None:
    cutoff = 1_784_365_200_000  # 2026-07-18T09:00:00Z (06:00 BRT)
    # Disabled: cutoff == 0 never drops.
    assert before_cutoff(1_000, 0) is False
    # Strictly before -> drop.
    assert before_cutoff(cutoff - 1, cutoff) is True
    # Exactly at / after the cutoff -> keep.
    assert before_cutoff(cutoff, cutoff) is False
    assert before_cutoff(cutoff + 1, cutoff) is False
    # Unknown start (0) is never dropped on missing data.
    assert before_cutoff(0, cutoff) is False


async def test_process_match_drops_pre_cutoff_without_touching_db(monkeypatch: Any) -> None:
    """A match older than the cutoff returns 'filtered' before any DB session.

    get_sessionmaker() is booby-trapped: if the guard let control fall through it
    would be called and raise, so this also proves the early return short-circuits
    the write path.
    """
    cutoff = 1_784_365_200_000  # 2026-07-18T09:00:00Z
    monkeypatch.setattr(mp.settings, "match_min_started_at_ms", cutoff)

    def _boom() -> Any:  # pragma: no cover - only runs if the guard fails
        raise AssertionError("get_sessionmaker must not be called for a pre-cutoff match")

    monkeypatch.setattr(mp, "get_sessionmaker", _boom)

    # started one hour before the cutoff.
    payload = _arena_payload(started_ms=cutoff - 3_600_000)
    result = await mp.WorkerRatingService().process_match("BR1_OLD", payload, redis=None)

    assert result == {"matchId": "BR1_OLD", "status": "filtered", "reason": "before_cutoff"}


async def test_process_match_filters_degenerate_single_team_payload(monkeypatch: Any) -> None:
    """Riot occasionally stamps every participant with playerSubteamId=0 (and
    placement 0) — real, full-length matches with otherwise-valid data. That
    collapses parse_arena_match's grouping into one subteam instead of several,
    which arena.rating.engine.rate() rejects with "a match needs at least 2
    teams" — a real dead-lettered match this regression-tests against (
    BR1_3265476308, 18 participants, all playerSubteamId=0/subteamPlacement=0).
    This must filter before ever reaching the rating engine or a DB session,
    not retry 3x and dead-letter a match that was never ratable.
    """
    monkeypatch.setattr(mp.settings, "match_min_started_at_ms", 0)  # cutoff disabled

    def _boom() -> Any:  # pragma: no cover - only runs if the guard fails
        raise AssertionError("get_sessionmaker must not be called for an unratable match")

    monkeypatch.setattr(mp, "get_sessionmaker", _boom)

    payload = _arena_payload()
    for p in payload["info"]["participants"]:
        p["playerSubteamId"] = 0
        p["subteamPlacement"] = 0

    result = await mp.WorkerRatingService().process_match("BR1_3265476308", payload, redis=None)

    assert result == {
        "matchId": "BR1_3265476308",
        "status": "filtered",
        "reason": "incomplete_teams",
    }


async def test_process_match_keeps_a_smaller_than_canonical_lobby(monkeypatch: Any) -> None:
    """The filter mirrors the engine's own >=2-teams guard, not the mode's full
    canonical shape (is_complete) — a lobby smaller than 8x2/6x3 is still
    genuinely ratable (arena.rating.engine.rate only requires >=2 teams) and
    must not be swept up by the same fix."""
    assert len(parse_arena_match(_arena_payload()).subteams) == 2  # sanity: 2 teams, not 8
    monkeypatch.setattr(mp.settings, "match_min_started_at_ms", 0)

    marker = RuntimeError("reached get_sessionmaker — proves the filter did not fire")
    monkeypatch.setattr(mp, "get_sessionmaker", lambda: (_ for _ in ()).throw(marker))

    with pytest.raises(RuntimeError, match="reached get_sessionmaker"):
        await mp.WorkerRatingService().process_match("BR1_OK", _arena_payload(), redis=None)


async def test_eligibility_only_integrity_freezes_listed_players() -> None:
    integ = EligibilityOnlyIntegrity({"id-4"})
    match = RawMatch(
        match_id="m",
        riot_match_id="BR1_1",
        season_id="s",
        mode="DUOS",
        queue_id=1700,
        played_at="2023-11-14T00:00:00+00:00",
        participants=[],
    )

    verdict = await integ.evaluate(match)

    assert verdict.ineligible_player_ids == {"id-4"}
    assert verdict.is_eligible("id-9") is True
    assert verdict.is_eligible("id-4") is False
    assert verdict.flags == []
    assert verdict.boosting_factors == {}
