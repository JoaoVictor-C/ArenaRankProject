"""Pure (no DB) tests for ``pdl_explain_service``'s apportionment and DTO
projection — the "displayed integers sum exactly to the displayed total" and
"legacy/fresh ledgers produce well-formed DTOs" guarantees."""

from __future__ import annotations

import random

import dataclasses

from arena.rating import DEFAULT_PARAMS
from arena.rating.caps import CapParams
from arena.services.pdl_explain_service import (
    _apportion,
    _placement_curve,
    _to_dto,
    lobby_context_from_rows,
)
from arena.rating.explain import CapVerdict, LedgerEntry, PdlExplanation


def test_apportion_sums_exactly_to_target_over_a_random_sweep() -> None:
    # n=0 is excluded here: with zero entries there is nowhere to place a
    # nonzero target (see test_apportion_empty_input for that documented edge).
    rng = random.Random(1234)
    for _ in range(500):
        n = rng.randint(1, 8)
        values = [rng.uniform(-50, 50) for _ in range(n)]
        target = rng.randint(-100, 100)
        result = _apportion(values, target)
        assert len(result) == n
        assert sum(result) == target
        for r in result:
            assert isinstance(r, int)


def test_apportion_empty_input() -> None:
    assert _apportion([], 0) == []
    # Documented edge: an empty list has nowhere to place a nonzero target.
    # Real callers never hit this (empty entries only pair with cr_delta=0.0,
    # the frozen/ineligible early return) -- pinned here so the contract stays
    # explicit rather than silently assumed.
    assert _apportion([], 5) == []


def test_apportion_already_exact_leaves_rounding_alone() -> None:
    # 10.0 + 20.0 + 10.0 = 40, target 40 -> no adjustment needed.
    assert _apportion([10.0, 20.0, 10.0], 40) == [10, 20, 10]


def test_apportion_nudges_the_largest_remainder_first() -> None:
    # 1.4 + 1.4 + 1.4 = 4.2 -> naive round gives [1,1,1]=3, target=4 needs +1;
    # all three have the identical remainder (0.4), so the first one wins the tie.
    result = _apportion([1.4, 1.4, 1.4], 4)
    assert sum(result) == 4
    assert sorted(result) == [1, 1, 2]


def test_apportion_handles_negative_target() -> None:
    result = _apportion([-10.3, -5.2, -0.1], -16)
    assert sum(result) == -16


def _mk_entry(kind: str, pdl: float, running: float, *, exact: bool = True) -> LedgerEntry:
    return LedgerEntry(kind=kind, pdl=pdl, multiplier=None, running_total=running, exact=exact)  # type: ignore[arg-type]


def test_to_dto_reconciles_and_apportions_a_simple_exact_ledger() -> None:
    entries = [
        _mk_entry("base", 25.3, 25.3),
        _mk_entry("placement", 4.5, 29.8),
        _mk_entry("confidence", 2.1, 31.9),
    ]
    exp = PdlExplanation(
        fidelity="exato",
        cr_before=650.0,
        cr_after=681.9,
        cr_delta=31.9,
        placement=1,
        team_count=6,
        entries=entries,
        cap=CapVerdict(active=False, bound="none"),
        residual=0.0,
        unrecoverable=(),
    )
    dto = _to_dto(exp)
    assert dto.reconciles is True
    assert sum(e.pdl for e in dto.entries) == dto.total_pdl
    assert dto.total_pdl == 32  # round(31.9)
    assert dto.fidelity == "exato"


def test_to_dto_lumped_parcial_ledger_still_apportions_exactly() -> None:
    entries = [
        _mk_entry("base", 10.0, 10.0),
        _mk_entry("placement", 1.0, 11.0),
        _mk_entry("display_adjust", 6.7, 17.7, exact=False),
    ]
    exp = PdlExplanation(
        fidelity="parcial",
        cr_before=650.0,
        cr_after=667.7,
        cr_delta=17.7,
        placement=3,
        team_count=6,
        entries=entries,
        cap=CapVerdict(active=True, bound="loss_cap"),
        residual=0.0,
        unrecoverable=("confidence", "cap_adjustment"),
    )
    dto = _to_dto(exp)
    assert dto.reconciles is True
    assert sum(e.pdl for e in dto.entries) == dto.total_pdl
    assert dto.fidelity == "parcial"
    adjust_entry = next(e for e in dto.entries if e.kind == "display_adjust")
    assert adjust_entry.exact is False
    assert adjust_entry.note is not None


# ---------------------------------------------------------------------------
# lobby_context_from_rows — the batch legacy-row lobby reconstruction that
# feeds map_modifiers' state/lobby_mean_mu params (arena/api/routers/_common.py).
# ---------------------------------------------------------------------------


def _sb(mu: float, sigma: float = 5.0, games: int = 40) -> dict:
    return {"mu": mu, "sigma": sigma, "matches_played": games}


def test_lobby_context_excludes_self_from_the_mean() -> None:
    rows = [
        ("m1", "p1", _sb(30.0)),
        ("m1", "p2", _sb(20.0)),
        ("m1", "p3", _sb(10.0)),
    ]
    ctx = lobby_context_from_rows(rows)
    state, lobby_mean = ctx[("m1", "p1")]
    assert state.mu == 30.0
    assert lobby_mean == 15.0  # mean of p2(20) and p3(10), NOT including p1


def test_lobby_context_skips_a_match_with_any_missing_state() -> None:
    rows = [
        ("m1", "p1", _sb(30.0)),
        ("m1", "p2", None),  # one participant missing state_before
        ("m2", "p3", _sb(10.0)),
        ("m2", "p4", _sb(20.0)),
    ]
    ctx = lobby_context_from_rows(rows)
    assert ("m1", "p1") not in ctx
    assert ("m1", "p2") not in ctx
    assert ("m2", "p3") in ctx  # unaffected — a DIFFERENT match


def test_lobby_context_skips_a_match_with_a_single_participant() -> None:
    # n-1 == 0 would divide by zero; shouldn't happen for a real Arena lobby
    # (min 2 subteams) but must degrade safely rather than crash.
    rows = [("m1", "p1", _sb(30.0))]
    assert lobby_context_from_rows(rows) == {}


# ---------------------------------------------------------------------------
# _placement_curve — the baseline (composite=1.0) cap curve exposed as
# PdlCap.placement_curve, so the frontend can show "why does 1st cap at +40
# while 4th's loss only caps at -30" as a property of the curve, not this match.
# ---------------------------------------------------------------------------


def _params_with_caps(**overrides: object) -> object:
    cp = CapParams(
        base_cap_by_placement={6: [40.0, 34.0, 26.0, 26.0, 34.0, 40.0]},
        loss_cap_by_placement={6: [30.0, 30.0, 30.0, 30.0, 45.0, 68.0]},
        min_gain_by_placement={6: [15.0, 10.0, 5.0, 0.0, 0.0, 0.0]},
        **overrides,  # type: ignore[arg-type]
    )
    return dataclasses.replace(DEFAULT_PARAMS, caps=cp)


def test_placement_curve_covers_every_placement_at_this_team_count() -> None:
    curve = _placement_curve(6, _params_with_caps())
    assert [p.placement for p in curve] == [1, 2, 3, 4, 5, 6]
    first = curve[0]
    assert first.gain_cap == 40
    assert first.loss_cap == -30
    assert first.min_gain == 15
    last = curve[5]
    assert last.gain_cap == 40  # symmetric table -> 6th's WIN side mirrors 1st
    assert last.loss_cap == -68
    assert last.min_gain == 0


def test_placement_curve_empty_when_caps_not_configured() -> None:
    assert _placement_curve(6, dataclasses.replace(DEFAULT_PARAMS, caps=None)) == []


def test_placement_curve_empty_for_an_unconfigured_team_count() -> None:
    # base_cap_by_placement only has an entry for 6 in this fixture.
    assert _placement_curve(8, _params_with_caps()) == []


def test_lobby_context_handles_several_matches_in_one_batch() -> None:
    rows = [
        ("m1", "p1", _sb(30.0)),
        ("m1", "p2", _sb(10.0)),
        ("m2", "p1", _sb(50.0)),
        ("m2", "p5", _sb(30.0)),
    ]
    ctx = lobby_context_from_rows(rows)
    assert ctx[("m1", "p1")][1] == 10.0
    assert ctx[("m2", "p1")][1] == 30.0  # same player, different match -> different mean
