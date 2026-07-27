"""Dev-seed player resolution (arena/db/seed.py).

Covers the pure Riot-ID parsing plus the account-v1 resolution path, which must
degrade to "skip with a warning" rather than raising — the seed gates
`docker compose up` (every service waits on it completing successfully), so a
missing Riot key or an unknown account must never fail the run.

The DB-writing half (`seed_players`) needs a live Postgres and is exercised by
the compose stack, not here.
"""

from __future__ import annotations

from typing import Any

import pytest

from arena.core.config import settings

# `arena.db.__init__` imports a `seed` FUNCTION, which shadows the submodule
# attribute — import the names directly rather than via `arena.db.seed`.
from arena.db.seed import configured_riot_ids, parse_riot_id, resolve_puuids


# --- pure parsing ----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Presente#1001", ("Presente", "1001")),
        ("CrazzyBoy#Br2", ("CrazzyBoy", "Br2")),
        ("  Spaced Name#BR1  ", ("Spaced Name", "BR1")),
        # rpartition splits on the LAST '#', so a '#' inside the game name works.
        ("od#d#NA1", ("od#d", "NA1")),
    ],
)
def test_parse_riot_id_valid(raw: str, expected: tuple[str, str]) -> None:
    assert parse_riot_id(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "NoTag", "#1001", "Presente#", "#"])
def test_parse_riot_id_rejects_malformed(raw: str) -> None:
    assert parse_riot_id(raw) is None


def test_configured_riot_ids_splits_and_trims(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "seed_players", " Presente#1001 , CrazzyBoy#Br2 ,, ")
    assert configured_riot_ids() == ["Presente#1001", "CrazzyBoy#Br2"]


def test_configured_riot_ids_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "seed_players", "")
    assert configured_riot_ids() == []


# --- account-v1 resolution -------------------------------------------------


class _FakeRedis:
    async def aclose(self) -> None:
        return None


class _FakeClient:
    """Stands in for RiotClient: resolves a fixed table, raises otherwise."""

    def __init__(self, table: dict[tuple[str, str], dict[str, Any]]) -> None:
        self._table = table
        self.calls: list[tuple[str, str]] = []

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_account_by_riot_id(self, game_name: str, tag_line: str) -> dict[str, Any]:
        self.calls.append((game_name, tag_line))
        try:
            return self._table[(game_name, tag_line)]
        except KeyError:
            from arena.riot.errors import RiotNotFoundError

            raise RiotNotFoundError("https://riot/account") from None


def _install_fake_client(
    monkeypatch: pytest.MonkeyPatch, table: dict[tuple[str, str], dict[str, Any]]
) -> _FakeClient:
    import redis.asyncio as redis_asyncio

    from arena.riot import client as riot_client

    fake = _FakeClient(table)
    monkeypatch.setattr(riot_client, "build_default_client", lambda *a, **kw: fake)
    monkeypatch.setattr(
        redis_asyncio.Redis, "from_url", staticmethod(lambda *a, **kw: _FakeRedis())
    )
    return fake


@pytest.mark.asyncio
async def test_resolve_puuids_without_key_skips_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Riot key => no players, but no exception (compose up must stay green)."""
    monkeypatch.setattr(settings, "riot_api_key", "")
    assert await resolve_puuids(["Presente#1001"]) == {}


@pytest.mark.asyncio
async def test_resolve_puuids_returns_riot_canonical_casing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Riot's gameName/tagLine win over the configured spelling."""
    monkeypatch.setattr(settings, "riot_api_key", "fake-key")
    _install_fake_client(
        monkeypatch,
        {("CrazzyBoy", "Br2"): {"puuid": "P" * 78, "gameName": "CrazzYboY", "tagLine": "BR2"}},
    )
    got = await resolve_puuids(["CrazzyBoy#Br2"])
    assert got == {"CrazzyBoy#Br2": ("P" * 78, "CrazzYboY", "BR2")}


@pytest.mark.asyncio
async def test_resolve_puuids_skips_unknown_and_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unresolvable account is dropped, not inserted with a placeholder puuid."""
    monkeypatch.setattr(settings, "riot_api_key", "fake-key")
    _install_fake_client(
        monkeypatch,
        {("Presente", "1001"): {"puuid": "A" * 78, "gameName": "Presente", "tagLine": "1001"}},
    )
    got = await resolve_puuids(["Presente#1001", "GhostAccount#0000", "malformed"])
    assert list(got) == ["Presente#1001"]


@pytest.mark.asyncio
async def test_resolve_puuids_survives_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "riot_api_key", "fake-key")

    class _Boom(_FakeClient):
        async def get_account_by_riot_id(self, game_name: str, tag_line: str) -> dict[str, Any]:
            raise OSError("dns failure")

    import redis.asyncio as redis_asyncio

    from arena.riot import client as riot_client

    monkeypatch.setattr(riot_client, "build_default_client", lambda *a, **kw: _Boom({}))
    monkeypatch.setattr(
        redis_asyncio.Redis, "from_url", staticmethod(lambda *a, **kw: _FakeRedis())
    )
    assert await resolve_puuids(["Presente#1001"]) == {}


@pytest.mark.asyncio
async def test_resolve_puuids_empty_input_makes_no_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "riot_api_key", "fake-key")
    assert await resolve_puuids([]) == {}
