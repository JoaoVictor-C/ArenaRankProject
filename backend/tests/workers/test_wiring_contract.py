"""Regression guard for the worker write-path wiring (the seam that was broken).

These assert that the factories the arq workers import actually exist and return
objects satisfying the worker-side Protocols — exactly the breakage the audit
found: a missing ``arena.riot.get_client`` / ``arena.services.rating_service.
get_rating_service`` plus the ``list_match_ids`` vs ``get_match_ids_by_puuid``
method-name mismatch. No DB, Redis, or network is touched (the Riot client
constructs connection-free).
"""

from __future__ import annotations

from arena.workers.deps import (
    RatingService as RatingServiceProto,
    RiotClient as RiotClientProto,
    get_rating_service,
    get_riot_client,
)


def test_get_rating_service_resolves_and_satisfies_protocol() -> None:
    service = get_rating_service()
    assert service is not None, "worker rating-service factory must resolve (was None)"
    # runtime_checkable Protocol -> verifies process_match is present.
    assert isinstance(service, RatingServiceProto)
    assert callable(service.process_match)


def test_get_riot_client_resolves_and_satisfies_protocol() -> None:
    client = get_riot_client()
    assert client is not None, "worker riot-client factory must resolve (was None)"
    assert isinstance(client, RiotClientProto)
    # The adapter must expose the worker's name, bridging the real client's
    # get_match_ids_by_puuid.
    assert hasattr(client, "list_match_ids")
    assert hasattr(client, "get_match")


def test_real_client_uses_the_canonical_method_name() -> None:
    # Guards against re-introducing a call to a non-existent client method.
    from arena.riot.client import RiotClient

    assert hasattr(RiotClient, "get_match_ids_by_puuid")
    assert not hasattr(RiotClient, "list_match_ids")
