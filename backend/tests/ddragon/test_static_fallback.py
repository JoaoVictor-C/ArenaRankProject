"""Tests for the bundled offline champion catalog fallback (ddragon.service).

Guards the regression where a cold ddragon cache (``warm`` never ran / failed,
no network) made the leaderboard render numeric champion ids as names
("TOP 13 555") and drop champion icons. The bundled ``champions_static.json``
is the last-ditch fallback so sync resolution always yields real names + icons.
"""

from __future__ import annotations

from arena.ddragon.service import (
    FALLBACK_VERSION,
    DDragonService,
    _static_champion_map,
)


def test_static_catalog_loads_known_champions() -> None:
    catalog = _static_champion_map()
    assert len(catalog) > 150  # full Arena roster, not empty
    assert catalog[555] == {"key": "Pyke", "name": "Pyke"}
    assert catalog[29] == {"key": "Twitch", "name": "Twitch"}


def test_cold_cache_resolves_name_via_static_bundle() -> None:
    # No warm(), no Redis -> the in-process cache is cold.
    svc = DDragonService(redis=None)
    # Before the fix this returned "555" (the numeric id) instead of the name.
    assert svc.champion_name_sync(555) == "Pyke"
    assert svc.champion_name_sync(29) == "Twitch"


def test_cold_cache_resolves_icon_url_via_static_bundle() -> None:
    svc = DDragonService(redis=None)
    url = svc.champion_icon_url_sync(555)
    assert url is not None
    # Uses the bundled asset key + the fallback patch (kept in step with the JSON).
    assert url.endswith(f"/cdn/{FALLBACK_VERSION}/img/champion/Pyke.png")


def test_cold_cache_still_none_safe_for_unknown_and_none() -> None:
    svc = DDragonService(redis=None)
    # None -> empty label; unknown id -> numeric fallback (unchanged contract).
    assert svc.champion_name_sync(None) == ""
    assert svc.champion_name_sync(999_999) == "999999"
    assert svc.champion_icon_url_sync(999_999) is None
