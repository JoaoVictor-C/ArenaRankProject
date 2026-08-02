"""Arena queue-id recognition.

Riot mints a new queueId per Arena iteration. The live 2026-07 mode
"Arena 3v3 Bravura" is queueId 1740 (gameMode CHERRY, 6 subteams x 3). It must be
recognized as TRIOS, else discovery/ingestion silently drops the whole season.
"""
from __future__ import annotations

from arena.riot.arena import (
    ARENA_QUEUE_IDS,
    ArenaMode,
    mode_for_queue,
    parse_arena_match,
)


def _trios_payload(queue_id: int) -> dict:
    """A complete 6-subteam x 3-player (18 participant) CHERRY payload."""
    parts = []
    for sub in range(1, 7):
        for i in range(3):
            parts.append(
                {
                    "puuid": f"p{sub}_{i}",
                    "championId": 10 + sub,
                    "playerSubteamId": sub,
                    "subteamPlacement": sub,
                    "timePlayed": 600,
                }
            )
    return {
        "metadata": {"matchId": f"BR1_{queue_id}"},
        "info": {
            "queueId": queue_id,
            "gameMode": "CHERRY",
            "gameDuration": 1399,
            "gameStartTimestamp": 1_784_400_000_000,
            "participants": parts,
        },
    }


def test_1740_bravura_is_a_known_trios_queue() -> None:
    assert 1740 in ARENA_QUEUE_IDS
    assert mode_for_queue(1740) is ArenaMode.TRIOS


def test_parse_1740_trios_match_is_complete() -> None:
    parsed = parse_arena_match(_trios_payload(1740))
    assert parsed.queue_id == 1740
    assert parsed.mode is ArenaMode.TRIOS
    assert parsed.is_complete
    assert len(parsed.subteams) == 6


def test_parse_combat_telemetry_fields() -> None:
    """Combat primitives extracted verbatim from the Riot payload — field names
    confirmed against a real live match-v5 payload (see the combat-telemetry
    plan). Defaults to 0, never None, when a field is absent from the payload."""
    payload = _trios_payload(1750)
    first = payload["info"]["participants"][0]
    first.update(
        {
            "kills": 7,
            "deaths": 2,
            "assists": 11,
            "totalDamageDealtToChampions": 18770,
            "goldEarned": 7206,
            "champLevel": 13,
            "totalDamageTaken": 20008,
            "totalHeal": 4961,
            "damageSelfMitigated": 19843,
            "largestMultiKill": 2,
            "killingSprees": 1,
            "totalTimeSpentDead": 243,
        }
    )
    parsed = parse_arena_match(payload)
    p = parsed.subteams[0].participants[0]
    assert p.kills == 7
    assert p.deaths == 2
    assert p.assists == 11
    assert p.damage_to_champions == 18770
    assert p.gold_earned == 7206
    assert p.champion_level == 13
    assert p.damage_taken == 20008
    assert p.total_heal == 4961
    assert p.damage_self_mitigated == 19843
    assert p.largest_multi_kill == 2
    assert p.killing_sprees == 1
    assert p.time_spent_dead == 243

    # No combat fields in the payload (the base fixture) -> 0, not None/missing.
    other = parsed.subteams[0].participants[1]
    assert other.kills == 0
    assert other.deaths == 0
    assert other.assists == 0
    assert other.damage_to_champions == 0
