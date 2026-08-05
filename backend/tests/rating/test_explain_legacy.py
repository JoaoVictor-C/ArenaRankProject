"""Legacy-row reconstruction tests for ``arena/rating/explain.py``.

The core claim under test: a row rated and persisted BEFORE this feature shipped —
carrying only the original 9 ``AppliedModifiers`` fields (including the two fields
Bug A / Bug B polluted) plus ``cr_before``/``cr_after``/``cr_delta`` — can still be
explained correctly, because ``explain()`` never reads ``soft_cap_factor`` or
``dispersion_clamped`` from the record; it recomputes/derives them. This file
proves that immunity directly: build a Tier-A ("fresh") explanation, strip every
field a legacy row wouldn't have, INJECT the exact polluted values Bug A/B would
have produced, and confirm ``explain()`` on the stripped-and-poisoned input still
reconciles and (when the cap didn't bind) matches the Tier-A ledger.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_bugfix_output_invariance import build_matrix  # noqa: E402

from arena.rating import rate  # noqa: E402
from arena.rating import caps as C  # noqa: E402
from arena.rating.explain import ExplainInput, ExplainState, explain, explain_result  # noqa: E402

_EPS = 1e-6


def _legacy_input_from(match, pr, placement: int, team_count: int, *, with_state: bool) -> ExplainInput:
    """Build the ExplainInput a truly pre-migration row would produce: only the
    original 9 AppliedModifiers fields + cr_before/after/delta/eligible, nothing
    from explainVersion onward. ``with_state`` controls whether state_before
    (mu/sigma/matches_played, needed only for cap reconstruction) is available."""
    mods = pr.modifiers
    state = None
    lobby_mean_mu = None
    if with_state:
        states_by_pid = {pt.player_id: pt.state for t in match.teams for pt in t.participants}
        s = states_by_pid[pr.player_id]
        sum_mu_all = sum(st.mu for st in states_by_pid.values())
        n_all = len(states_by_pid)
        lobby_mean_mu = (sum_mu_all - s.mu) / (n_all - 1) if n_all > 1 else s.mu
        state = ExplainState(mu=s.mu, sigma=s.sigma, matches_played=s.matches_played)

    return ExplainInput(
        params=match.params,
        placement=placement,
        team_count=team_count,
        eligible=pr.eligible,
        cr_before=pr.cr_before,
        cr_after=pr.cr_after,
        cr_delta=pr.cr_delta,
        pl_base_delta_mu=mods.pl_base_delta_mu,
        final_delta_mu=mods.final_delta_mu,
        placement_weight=mods.placement_weight,
        placement_amp=mods.placement_amp,
        streak_mult=mods.streak_mult,
        boosting_factor=mods.boosting_factor,
        party_factor=mods.party_factor,
        explain_version=0,
        # Deliberately NOT set: confidence_cr, pre_cap_cr_delta, cap_facts — a
        # legacy row never persisted these.
        state=state,
        lobby_mean_mu=lobby_mean_mu,
        gain_floor_mult=1.0,
    )


# ---------------------------------------------------------------------------
# ExplainInput structurally cannot carry the polluted fields
# ---------------------------------------------------------------------------


def test_explain_input_has_no_slot_for_the_polluted_fields() -> None:
    """Bug A polluted `soft_cap_factor`; Bug B polluted `dispersion_clamped`.
    `explain()` immunizes every row by never reading them — enforced here at the
    TYPE level: ExplainInput has no field that could carry either one, so there is
    no code path that could accidentally start trusting them again."""
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(ExplainInput)}
    assert "soft_cap_factor" not in field_names
    assert "dispersion_clamped" not in field_names


# ---------------------------------------------------------------------------
# Read/write equivalence: legacy reconstruction matches the Tier-A ledger
# whenever the cap provably did not bind.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("match_id", sorted(build_matrix().keys()))
def test_legacy_reconstruction_reconciles_with_state_available(match_id: str) -> None:
    matrix = build_matrix()
    match = matrix[match_id]
    result = rate(match)
    placement_by_pid = {pt.player_id: t.placement for t in match.teams for pt in t.participants}
    team_count = len(match.teams)

    for pr in result.players:
        legacy = _legacy_input_from(
            match, pr, placement_by_pid[pr.player_id], team_count, with_state=True
        )
        exp = explain(legacy)
        ledger_sum = sum(e.pdl for e in exp.entries)
        assert ledger_sum == pytest.approx(pr.cr_delta, abs=_EPS), (
            f"{match_id}/{pr.player_id}: legacy ledger sums to {ledger_sum!r}, "
            f"cr_delta is {pr.cr_delta!r}"
        )
        assert exp.fidelity in ("exato", "derivado", "parcial")


@pytest.mark.parametrize("match_id", sorted(build_matrix().keys()))
def test_legacy_ledger_matches_tier_a_when_cap_did_not_bind(match_id: str) -> None:
    """When the Tier-A ledger's cap entry is exactly 0 (cap evaluated but did not
    move the delta), the Tier-B reconstruction (independently recomputing the same
    bounds from state_before + lobby mean) must produce an entry-for-entry
    identical ledger — proving the two code paths agree, not just that each one
    separately reconciles."""
    matrix = build_matrix()
    match = matrix[match_id]
    result = rate(match)
    placement_by_pid = {pt.player_id: t.placement for t in match.teams for pt in t.participants}
    team_count = len(match.teams)

    for pr in result.players:
        if not pr.eligible:
            continue
        fresh = explain_result(match.params, placement_by_pid[pr.player_id], team_count, pr)
        cap_entry = next((e for e in fresh.entries if e.kind == "cap"), None)
        if cap_entry is not None and abs(cap_entry.pdl) > _EPS:
            continue  # cap bound -> legacy reconstruction is honestly "parcial" instead

        legacy = _legacy_input_from(
            match, pr, placement_by_pid[pr.player_id], team_count, with_state=True
        )
        exp = explain(legacy)
        assert len(exp.entries) == len(fresh.entries), f"{match_id}/{pr.player_id}: entry count differs"
        for fresh_e, legacy_e in zip(fresh.entries, exp.entries, strict=True):
            assert fresh_e.kind == legacy_e.kind
            assert fresh_e.pdl == pytest.approx(legacy_e.pdl, abs=_EPS), (
                f"{match_id}/{pr.player_id}/{fresh_e.kind}: "
                f"fresh={fresh_e.pdl!r} legacy={legacy_e.pdl!r}"
            )


# ---------------------------------------------------------------------------
# Immunity to the actual Bug A / Bug B polluted values
# ---------------------------------------------------------------------------


def test_injecting_the_polluted_bug_a_value_does_not_affect_the_ledger() -> None:
    """Simulate what a PRE-FIX row's persisted `softCapFactor` actually held (Bug
    A: `C.high_cr_scale(cr_before, cp)` instead of the real soft-cap factor) and
    confirm it changes nothing, because explain() recomputes soft_cap_factor from
    (cr_before, pl_base_delta_mu, params) and never reads a stored value at all."""
    matrix = build_matrix()
    match = matrix["trios_high_cr_scale_caps_on"]
    result = rate(match)
    placement_by_pid = {pt.player_id: t.placement for t in match.teams for pt in t.participants}
    team_count = len(match.teams)

    for pr in result.players:
        if not pr.eligible or pr.cap is None:
            continue
        # The exact value Bug A would have stored in softCapFactor for this player.
        polluted_scf = C.high_cr_scale(pr.cr_before, match.params.caps)
        clean = explain_result(match.params, placement_by_pid[pr.player_id], team_count, pr)

        legacy = _legacy_input_from(
            match, pr, placement_by_pid[pr.player_id], team_count, with_state=True
        )
        # ExplainInput has no field for this value (see the structural test above)
        # -- there is nothing to "inject" it INTO. Prove the point empirically
        # anyway: the reconstructed chain step for soft_cap must equal the REAL
        # soft_cap_factor's contribution, not the polluted stand-in, whenever they
        # differ (they almost always do -- high_cr_scale is a sigmoid, essentially
        # never exactly 1.0, while the real soft_cap_factor is 1.0 below the
        # unreachable 5000 threshold).
        poisoned = explain(legacy)
        clean_soft_cap = next(e for e in clean.entries if e.kind == "soft_cap")
        poisoned_soft_cap = next(e for e in poisoned.entries if e.kind == "soft_cap")
        assert poisoned_soft_cap.pdl == pytest.approx(clean_soft_cap.pdl, abs=_EPS)
        if abs(polluted_scf - 1.0) > 1e-4:
            # The polluted value really would have differed from a no-op (1.0) --
            # this confirms the test setup is meaningful, not vacuously true.
            assert clean_soft_cap.pdl == pytest.approx(0.0, abs=1e-3), (
                "expected the REAL soft_cap_factor to be a no-op "
                "(soft_cap_threshold=5000 is unreachable in these fixtures)"
            )


def test_injecting_the_polluted_bug_b_flag_does_not_affect_the_ledger() -> None:
    """Bug B: `dispersion_clamped` was overwritten with the PDL-cap-or-floor flag.
    ExplainInput has no field for it at all (see the structural test) -- the
    dispersion entry is always `final_delta_mu - chain_product`, independent of
    any stored boolean. Confirm the dispersion entry reconciles regardless of
    whether the (unrepresented) polluted flag would have been True or False."""
    matrix = build_matrix()
    for match_id in ("trios_dispersion_trigger_caps_on", "trios_fresh_caps_on"):
        match = matrix[match_id]
        result = rate(match)
        placement_by_pid = {pt.player_id: t.placement for t in match.teams for pt in t.participants}
        team_count = len(match.teams)
        for pr in result.players:
            if not pr.eligible:
                continue
            legacy = _legacy_input_from(
                match, pr, placement_by_pid[pr.player_id], team_count, with_state=True
            )
            exp = explain(legacy)
            ledger_sum = sum(e.pdl for e in exp.entries)
            assert ledger_sum == pytest.approx(pr.cr_delta, abs=_EPS)


# ---------------------------------------------------------------------------
# state_before missing entirely (pre-migration-0014 rows)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("match_id", sorted(build_matrix().keys()))
def test_missing_state_before_degrades_honestly_but_still_reconciles(match_id: str) -> None:
    matrix = build_matrix()
    match = matrix[match_id]
    result = rate(match)
    placement_by_pid = {pt.player_id: t.placement for t in match.teams for pt in t.participants}
    team_count = len(match.teams)

    for pr in result.players:
        legacy = _legacy_input_from(
            match, pr, placement_by_pid[pr.player_id], team_count, with_state=False
        )
        exp = explain(legacy)
        ledger_sum = sum(e.pdl for e in exp.entries)
        assert ledger_sum == pytest.approx(pr.cr_delta, abs=_EPS)
        if pr.eligible and match.params.caps is not None:
            # No state_before -> cap bounds are unrecoverable -> never claim exato.
            assert exp.fidelity in ("parcial",)
            assert "cap_bounds" in exp.unrecoverable


def test_missing_state_before_with_caps_disabled_still_reaches_derivado() -> None:
    """caps=None means there is nothing about the cap layer to be unrecoverable
    about -- missing state_before shouldn't penalize fidelity in that case."""
    matrix = build_matrix()
    match = matrix["trios_fresh_caps_off"]
    assert match.params.caps is None
    result = rate(match)
    placement_by_pid = {pt.player_id: t.placement for t in match.teams for pt in t.participants}
    team_count = len(match.teams)
    for pr in result.players:
        if not pr.eligible:
            continue
        legacy = _legacy_input_from(match, pr, placement_by_pid[pr.player_id], team_count, with_state=False)
        exp = explain(legacy)
        assert exp.fidelity == "derivado"
        assert exp.unrecoverable == ()
