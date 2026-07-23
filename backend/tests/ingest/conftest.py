from __future__ import annotations

from typing import Any


def arena_payload(match_id: str, puuids: list[str], *, queue: int = 1700,
                  start_ms: int = 1_781_481_600_000, duration: int = 600) -> dict[str, Any]:
    """A complete DUOS (8x2) payload from 16 puuids unless fewer are given."""
    parts = []
    for i, pu in enumerate(puuids):
        sub = i // 2 + 1
        place = sub  # deterministic placements 1..8
        parts.append({
            "puuid": pu, "riotIdGameName": pu, "riotIdTagline": "BR1",
            "championId": 10 + i, "playerSubteamId": sub, "subteamPlacement": place,
            "profileIcon": 1, "timePlayed": duration, "gameEndedInEarlySurrender": False,
        })
    return {"metadata": {"matchId": match_id},
            "info": {"queueId": queue, "gameDuration": duration,
                     "gameStartTimestamp": start_ms, "participants": parts}}


class FakeSource:
    """In-memory MatchSource: maps puuid->list[match_id] and match_id->payload.
    Records call counts so tests can assert no-refetch behavior."""

    def __init__(self, ids_by_puuid: dict[str, list[str]], payloads: dict[str, dict]):
        self._ids = ids_by_puuid
        self._payloads = payloads
        self.id_calls = 0
        self.match_calls: list[str] = []

    async def get_match_ids_by_puuid(self, puuid, *, start, count, queue, start_time, end_time):
        self.id_calls += 1
        ids = self._ids.get(puuid, [])
        return ids[start:start + count]  # honors pagination

    async def get_match(self, match_id):
        self.match_calls.append(match_id)
        return self._payloads[match_id]
