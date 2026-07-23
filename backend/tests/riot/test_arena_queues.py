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
