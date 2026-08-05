"""The match-modifier breakdown mapper (`_common.map_modifiers`).

Raio-X do resultado (v1.4): reconstructs an :class:`arena.rating.explain.
ExplainInput` from the persisted JSONB snapshot, runs it through the pure
``explain()`` ledger, and renders the UI breakdown with a REAL ``pdl_impact`` per
chip (never a client-side reverse-engineered guess). Must tolerate the new
``partyFactor`` key AND older rows that predate it (neutral default), surface the
premade dampener as a penalty, and — for a "modern" (post-fix, ``explainVersion``
>= 1) snapshot carrying the full cap block — surface the new confiança/teto/piso
chips this feature adds.
"""

from __future__ import annotations

from typing import Any

import pytest

from arena.api.routers._common import map_modifiers

_DEFAULTS: dict[str, Any] = dict(placement=1, team_count=6, cr_before=650.0, eligible=True)


def _snapshot(**overrides: Any) -> dict[str, Any]:
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


def _map(snap: dict[str, Any], *, cr_delta: float = 30.0, **kw: Any) -> list[Any]:
    kwargs = {**_DEFAULTS, "cr_after": _DEFAULTS["cr_before"] + cr_delta, "cr_delta": cr_delta, **kw}
    return map_modifiers(snap, **kwargs)


def test_maps_old_row_without_party_factor() -> None:
    # Pre-feature rows have no partyFactor key — must not crash, no party modifier.
    snap = _snapshot()
    del snap["partyFactor"]
    out = _map(snap)
    assert all(m.kind != "grupo" for m in out)


def test_renders_premade_dampener_as_penalty() -> None:
    out = _map(_snapshot(partyFactor=0.85))
    party = [m for m in out if m.kind == "grupo"]
    assert len(party) == 1
    assert party[0].value < 1.0


def test_no_party_modifier_when_neutral() -> None:
    out = _map(_snapshot(partyFactor=1.0))
    assert all(m.kind != "grupo" for m in out)


def test_every_emitted_modifier_has_a_finite_pdl_impact() -> None:
    """The headline v1.4 guarantee: no chip is ever emitted without a real
    number behind it — this is what lets the frontend's old client-side
    reconstruction (see ``profileRatingSignalModel.ts``) stop engaging."""
    import math

    out = _map(_snapshot(partyFactor=0.7, boostingFactor=0.5, streakMult=1.2))
    assert out  # sanity: this snapshot should produce at least one chip
    for mod in out:
        assert mod.pdl_impact is not None
        assert math.isfinite(mod.pdl_impact)


def test_ineligible_participant_gets_no_modifiers() -> None:
    out = _map(_snapshot(), cr_delta=0.0, eligible=False)
    assert out == []


def test_colocacao_pdl_impact_bundles_base_and_placement() -> None:
    # placementWeight=1.18 (a realistic trios 1st-place curve value); no cap
    # bound (team_count/placement chosen so the raw stays within the gain cap).
    out = _map(_snapshot(plBaseDeltaMu=25.0, placementWeight=1.18, finalDeltaMu=29.5))
    colocacao = next(m for m in out if m.kind == "colocacao")
    assert colocacao.pdl_impact is not None
    assert colocacao.pdl_impact > 0.0


# ---------------------------------------------------------------------------
# "Modern" snapshots (explainVersion >= 1, full cap block) — the new chips.
# ---------------------------------------------------------------------------


def _modern_snapshot(**overrides: Any) -> dict[str, Any]:
    """A snapshot shaped like what _modifiers_to_json persists for a match rated
    after this feature shipped (see arena/services/rating_service.py)."""
    base = _snapshot()
    base.update(
        {
            "explainVersion": 1,
            "paramsEpoch": "2026-08-02",
            "confidencePdl": 3.2,
            "preCapCrDelta": 33.2,
            "teamCount": 6,
            "cap": {
                "active": True,
                "bound": "none",
                "lo": -30.0,
                "hi": 40.0,
                "minGain": 15.0,
                "mismatchOverride": 1.0,
                "highCrScale": 1.0,
                "compositeWin": 1.0,
                "compositeLoss": 1.0,
                "gainFloorMult": 1.0,
                "teamCount": 6,
            },
        }
    )
    base.update(overrides)
    return base


def test_modern_snapshot_surfaces_a_confianca_chip() -> None:
    out = _map(_modern_snapshot(), cr_delta=33.2)
    confianca = [m for m in out if m.kind == "confianca"]
    assert len(confianca) == 1
    assert confianca[0].pdl_impact == 3.2


def test_modern_snapshot_with_gain_cap_surfaces_a_teto_chip() -> None:
    snap = _modern_snapshot(plBaseDeltaMu=60.0, finalDeltaMu=60.0)
    snap["preCapCrDelta"] = 63.2  # base(60) + confidence(3.2), pre-cap
    snap["cap"]["bound"] = "gain_cap"
    out = _map(snap, cr_delta=40.0)  # the gain cap (hi=40.0) bound
    teto = [m for m in out if m.kind == "teto_ganho"]
    assert len(teto) == 1
    assert teto[0].pdl_impact is not None
    assert teto[0].pdl_impact < 0.0  # the cap PULLED the delta down
    assert teto[0].label == "Teto de ganho da colocação"


def test_modern_snapshot_with_min_gain_surfaces_a_piso_chip() -> None:
    snap = _modern_snapshot(plBaseDeltaMu=0.5, finalDeltaMu=0.5)
    snap["preCapCrDelta"] = 3.7  # base(0.5) + confidence(3.2), a hollow win
    snap["cap"]["bound"] = "min_gain"
    out = _map(snap, cr_delta=15.0)  # the placement-1 floor (minGain=15.0)
    piso = [m for m in out if m.kind == "piso_ganho"]
    assert len(piso) == 1
    assert piso[0].pdl_impact is not None
    assert piso[0].pdl_impact > 0.0  # the floor is a BONUS, must be positive
    assert piso[0].label == "Piso de ganho da colocação"


def test_legacy_snapshot_never_surfaces_confianca_or_cap_chips() -> None:
    """A legacy snapshot (no explainVersion/cap/confidencePdl) has no persisted
    facts for these — map_modifiers must not guess. See explain()'s "Tier B,
    no state" path: it lumps everything past the chain into one entry, surfaced
    here as a single "ajuste" chip (not the per-factor confiança/teto/piso split
    a fresh row gets — see test_modifier_chips_always_reconcile_to_cr_delta)."""
    out = _map(_snapshot())
    assert all(
        m.kind not in ("confianca", "teto_ganho", "teto_perda", "piso_ganho") for m in out
    )


def test_legacy_snapshot_surfaces_the_remainder_as_an_ajuste_chip() -> None:
    """The regression this guards: a legacy row's lumped confiança+teto/piso
    remainder used to be silently dropped from the compact carousel, so its
    chips stopped short of cr_delta on virtually every historical match (this
    is the bug reported as "none of the matches are updated" — confiança alone
    is nearly always nonzero). It must now surface as an honest "ajuste" chip."""
    out = _map(_snapshot(), cr_delta=45.0)  # far from the mu-chain's own total
    ajuste = [m for m in out if m.kind == "ajuste"]
    assert len(ajuste) == 1
    assert ajuste[0].label == "Ajuste de exibição"
    assert ajuste[0].pdl_impact is not None


def test_legacy_snapshot_with_lobby_context_attributes_precisely_instead_of_lumping() -> None:
    """The point of wiring state/lobby_mean_mu into map_modifiers: when the
    caller CAN afford the lobby reconstruction (arena/services/
    pdl_explain_service.py::lobby_context_from_rows) and the cap provably didn't
    bind, a legacy row gets the SAME precise "confiança" attribution the
    drill-down ledger shows — not the opaque "ajuste de exibição" lump that
    fires when state is withheld (see the "None of the matches are updated"
    complaint this was written to fix)."""
    from arena.rating.explain import ExplainState

    state = ExplainState(mu=27.5, sigma=4.5, matches_played=40)
    without_context = _map(_snapshot(), cr_delta=8.0)
    with_context = _map(_snapshot(), cr_delta=8.0, state=state, lobby_mean_mu=27.0)

    assert any(m.kind == "ajuste" for m in without_context)
    assert not any(m.kind == "confianca" for m in without_context)

    assert not any(m.kind == "ajuste" for m in with_context)
    confianca = [m for m in with_context if m.kind == "confianca"]
    assert len(confianca) == 1
    total = sum(m.pdl_impact for m in with_context if m.pdl_impact is not None)
    assert total == pytest.approx(8.0, abs=1e-6)


def test_legacy_snapshot_where_the_cap_bound_names_the_mechanism_in_the_ajuste_label() -> None:
    """The remaining half of the "None of the matches are updated" complaint:
    even when explain() can't split the exact PDL share (a legacy row that
    landed exactly on a cap bound), it DOES know which rule bound — the "ajuste"
    chip must say so instead of the content-free generic label."""
    from arena.rating.explain import ExplainState

    # placement=1, team_count=6 -> the floor (min_gain) for a hollow win.
    state = ExplainState(mu=27.5, sigma=4.5, matches_played=40)
    out = _map(_snapshot(), cr_delta=15.0, state=state, lobby_mean_mu=27.4)
    ajuste = [m for m in out if m.kind == "ajuste"]
    assert len(ajuste) == 1
    assert ajuste[0].label == "Piso de ganho da colocação (parcial)"


def test_modifier_chips_always_reconcile_to_cr_delta() -> None:
    """The headline guarantee this whole feature exists to provide: the compact
    carousel's chips must sum to the SAME cr_delta shown on the match row —
    never just the factors map_modifiers happens to special-case."""
    cases = [
        (_snapshot(), 45.0),
        (_snapshot(streakMult=1.2, partyFactor=0.85, boostingFactor=0.9), -12.0),
        (_modern_snapshot(), 33.2),
        (
            (lambda s: (s["cap"].__setitem__("bound", "gain_cap"), s)[1])(
                _modern_snapshot(plBaseDeltaMu=60.0, finalDeltaMu=60.0, preCapCrDelta=63.2)
            ),
            40.0,
        ),
    ]
    for snap, cr_delta in cases:
        out = _map(snap, cr_delta=cr_delta)
        total = sum(m.pdl_impact for m in out if m.pdl_impact is not None)
        assert total == pytest.approx(cr_delta, abs=1e-6), snap
