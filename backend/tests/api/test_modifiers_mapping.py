"""The match-modifier breakdown mapper (`_common.map_modifiers`).

Reconstructs an ``AppliedModifiers`` from the persisted JSONB snapshot and renders
the UI breakdown. Must tolerate the new ``partyFactor`` key AND older rows that
predate it (neutral default), and surface the premade dampener as a penalty.
"""

from __future__ import annotations

from arena.api.routers._common import map_modifiers


def _snapshot(**overrides) -> dict:
    base = {
        "plBaseDeltaMu": 30.0,
        "placementWeight": 1.0,
        "placementAmp": 1.0,
        "streakMult": 1.0,
        "softCapFactor": 1.0,
        "boostingFactor": 1.0,
        "partyFactor": 1.0,
        "dispersionClamped": False,
        "finalDeltaMu": 30.0,
    }
    base.update(overrides)
    return base


def test_maps_old_row_without_party_factor() -> None:
    # Pre-feature rows have no partyFactor key — must not crash, no party modifier.
    snap = _snapshot()
    del snap["partyFactor"]
    out = map_modifiers(snap)
    assert all(m.kind != "grupo" for m in out)


def test_renders_premade_dampener_as_penalty() -> None:
    out = map_modifiers(_snapshot(partyFactor=0.85))
    party = [m for m in out if m.kind == "grupo"]
    assert len(party) == 1
    assert party[0].value < 1.0


def test_no_party_modifier_when_neutral() -> None:
    out = map_modifiers(_snapshot(partyFactor=1.0))
    assert all(m.kind != "grupo" for m in out)
