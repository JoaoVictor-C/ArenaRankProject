from __future__ import annotations

from arena.workers.deps import get_riot_client
from arena.ingest.crawler import MatchSource


def test_worker_riot_adapter_satisfies_matchsource():
    client = get_riot_client()
    # The crawler needs these two method names; the adapter must expose them.
    assert hasattr(client, "get_match_ids_by_puuid")
    assert hasattr(client, "get_match")
    assert isinstance(client, MatchSource)
