from __future__ import annotations

import pytest

from arena.ingest.replay import replay_chronological
from arena.riot.arena import parse_arena_match
from tests.ingest.conftest import arena_payload


class _RecordingRating:
    """Stand-in RatingService: records the order of riot_match_ids it sees."""
    def __init__(self):
        self._integrity = None
        self.order: list[str] = []

    async def process_match(self, session, lock_factory, raw):
        self.order.append(raw.riot_match_id)

        class _O:
            status = "ok"

        return _O()


@pytest.mark.asyncio
async def test_replay_processes_in_chronological_order():
    pus = [f"p{i}" for i in range(16)]
    late = parse_arena_match(arena_payload("late", pus, start_ms=2_000))
    early = parse_arena_match(arena_payload("early", pus, start_ms=1_000))
    id_map = {pu: f"id-{pu}" for pu in pus}
    rating = _RecordingRating()
    stats = await replay_chronological(
        session=None, matches=[late, early], season_id="s1",
        party_store=None, id_map=id_map, rating_service=rating,
    )
    assert stats.processed == 2
    assert rating.order == ["early", "late"]  # sorted by started_at_ms ascending


@pytest.mark.asyncio
async def test_replay_skips_match_with_missing_puuid():
    """Matches whose participants are missing from id_map are skipped (not KeyError-crashed)."""
    pus_a = [f"a{i}" for i in range(16)]
    pus_b = [f"b{i}" for i in range(16)]
    match_a = parse_arena_match(arena_payload("match_a", pus_a, start_ms=1_000))
    match_b = parse_arena_match(arena_payload("match_b", pus_b, start_ms=2_000))
    # id_map only covers pus_b — pus_a are absent, so match_a must be skipped
    id_map = {pu: f"id-{pu}" for pu in pus_b}
    rating = _RecordingRating()
    stats = await replay_chronological(
        session=None, matches=[match_a, match_b], season_id="s1",
        party_store=None, id_map=id_map, rating_service=rating,
    )
    assert stats.processed == 1
    assert rating.order == ["match_b"]
