"""Raio-X do resultado — the pure, additive PDL ledger behind one player's cr_delta.

Pure, deterministic, no I/O (same rule as the rest of ``arena/rating/``). No PT-BR
strings live here — labels/icons/descriptions belong to the API layer
(``arena/schemas/explain.py``), matching the repo convention that the engine stays
language-portable.

**The governing rule: persist facts at write time, derive the ledger at read time,
always, through this one function.** There is no separate write-time ledger to
drift from — ``rate()`` (engine.py) only ever populates :class:`PlayerRatingResult`'s
CR-space facts (``cap``, ``confidence_cr``, ``pre_cap_cr_delta``); this module turns
those facts (fresh, via :func:`explain_result`) OR a reconstruction of them from
persisted JSONB + optional lobby context (legacy rows, via :func:`explain`) into the
same :class:`PdlExplanation` shape.

Two discoveries drive the design (see engine.py's per-player loop and Bug A/B in its
history for the full story):

1. ``placementWeight`` / ``placementAmp`` / ``streakMult`` have been persisted,
   untouched by any bug, since the very first ``AppliedModifiers`` snapshot. They
   are trusted directly — reconstructing them from ``state_before`` is unnecessary.
2. ``soft_cap_factor`` is *recomputed* here (from ``cr_before`` + ``pl_base_delta_mu``
   + params — no player state needed) rather than read from the persisted
   ``softCapFactor`` field, because that field was corrupted by Bug A on every row
   rated before the fix. Recomputing immunizes ALL historical rows in one stroke.
   Likewise, the dispersion contribution is *derived*
   (``final_delta_mu - chain_product``) rather than reading the polluted
   ``dispersionClamped`` flag (Bug B).

The one thing that genuinely cannot always be recovered for a legacy row is the cap
layer's raw pre-cap delta when the cap actually bound — see the module-level
``_reconcile`` docstring for the "Tier B probe" this uses to at least prove, in the
common case, that the cap did *not* bind.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from . import caps as C
from . import modifiers as M
from .caps import CapBound
from .params import RatingParams
from .types import CapExplanation, PlayerRatingResult

LedgerKind = Literal[
    "base",
    "placement",
    "provisional",
    "streak",
    "soft_cap",
    "boosting",
    "party",
    "dispersion",
    "confidence",
    "cap",
    "zero_floor",
    "display_adjust",
]

Fidelity = Literal["exato", "derivado", "parcial"]

_RECONCILE_EPS = 1e-6


@dataclass(frozen=True, slots=True)
class ExplainState:
    """The lobby-context slice needed ONLY to reconstruct the cap layer for a
    legacy (Tier B) row — from ``match_participants.state_before``. Deliberately
    narrower than the full ``PlayerState``: the chain (placement/provisional/streak)
    never needs this, since those multipliers are read straight from the record."""

    mu: float
    sigma: float
    matches_played: int


@dataclass(frozen=True, slots=True)
class ExplainInput:
    """Everything :func:`explain` needs. Optional fields are ``None`` for a legacy
    row that predates the field they'd carry; :func:`explain` degrades ``fidelity``
    honestly rather than guessing."""

    params: RatingParams
    placement: int
    team_count: int
    eligible: bool

    # CR-space authority — the stored columns, taken as ground truth, never
    # recomputed. Every entry in the ledger is built to reconcile to `cr_delta`.
    cr_before: float
    cr_after: float
    cr_delta: float

    # The mu-space chain as recorded. `placement_weight`/`placement_amp`/
    # `streak_mult` are ALWAYS trustworthy (see module docstring, point 1) —
    # there is no "recorded vs. recomputed" branch for them.
    pl_base_delta_mu: float
    final_delta_mu: float
    placement_weight: float
    placement_amp: float
    streak_mult: float
    boosting_factor: float  # integrity-layer input; not a pure function of state
    party_factor: float  # ditto

    # explainVersion >= 1 marks a row rated after this feature shipped.
    explain_version: int = 0
    params_epoch: str | None = None

    # Tier A — present only for explainVersion >= 1 rows, straight from the
    # persisted `modifiers` JSONB. When present, the cap layer reconstructs exactly
    # with zero extra queries.
    confidence_cr: float | None = None
    pre_cap_cr_delta: float | None = None
    cap_facts: CapExplanation | None = None

    # Tier B — legacy cap reconstruction inputs. `lobby_mean_mu` is the mean
    # pre-match mu of the OTHER participants (from a bulk `state_before` aggregate,
    # see `arena/services/pdl_explain_service.py`); `gain_floor_mult` is usually
    # unknown for old rows (assume 1.0 unless an `integrity_events` boosting flag
    # says otherwise — the service layer decides that, not this pure function).
    state: ExplainState | None = None
    lobby_mean_mu: float | None = None
    gain_floor_mult: float = 1.0


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    kind: LedgerKind
    pdl: float
    multiplier: float | None
    running_total: float
    exact: bool


@dataclass(frozen=True, slots=True)
class CapVerdict:
    active: bool
    bound: CapBound
    gain_cap: float | None = None
    loss_cap: float | None = None
    min_gain: float | None = None
    raw_pdl: float | None = None
    adjustment_pdl: float | None = None
    mismatch_override: float | None = None
    high_cr_scale: float | None = None
    composite_win: float | None = None


@dataclass(frozen=True, slots=True)
class PdlExplanation:
    fidelity: Fidelity
    cr_before: float
    cr_after: float
    cr_delta: float
    placement: int
    team_count: int
    entries: list[LedgerEntry]
    cap: CapVerdict
    residual: float
    unrecoverable: tuple[str, ...] = ()


def explain_result(
    params: RatingParams,
    placement: int,
    team_count: int,
    pr: PlayerRatingResult,
) -> PdlExplanation:
    """Build the explanation directly from a fresh engine result — the exact
    (``explainVersion``-equivalent) path, used at write-adjacent read time before
    anything round-trips through JSONB. Equivalent to building an
    :class:`ExplainInput` from ``pr``'s own fields and calling :func:`explain`."""
    m = pr.modifiers
    return explain(
        ExplainInput(
            params=params,
            placement=placement,
            team_count=team_count,
            eligible=pr.eligible,
            cr_before=pr.cr_before,
            cr_after=pr.cr_after,
            cr_delta=pr.cr_delta,
            pl_base_delta_mu=m.pl_base_delta_mu,
            final_delta_mu=m.final_delta_mu,
            placement_weight=m.placement_weight,
            placement_amp=m.placement_amp,
            streak_mult=m.streak_mult,
            boosting_factor=m.boosting_factor,
            party_factor=m.party_factor,
            explain_version=1,
            confidence_cr=pr.confidence_cr,
            pre_cap_cr_delta=pr.pre_cap_cr_delta,
            cap_facts=pr.cap,
        )
    )


def explain(inp: ExplainInput) -> PdlExplanation:  # noqa: C901 — the fidelity ladder is inherently branchy
    """Derive the full additive PDL ledger for one player. See the module docstring
    for the governing "persist facts, derive at read time" rule.

    Guarantee: for every returned :class:`PdlExplanation`, ``sum(e.pdl for e in
    entries) == cr_delta`` to float precision (``residual`` reports the < 1e-9 noise
    from telescoping floats — it is never a hidden real amount). When something
    genuinely cannot be split (Tier B, cap bound, no persisted facts), the ledger
    still reconciles: it carries ONE honestly-labelled ``display_adjust`` entry
    (``exact=False``) instead of guessing a split.
    """
    p = inp.params

    if not inp.eligible:
        # Frozen participant: cr_delta is 0.0 by construction, nothing moved.
        return PdlExplanation(
            fidelity="exato",
            cr_before=inp.cr_before,
            cr_after=inp.cr_after,
            cr_delta=inp.cr_delta,
            placement=inp.placement,
            team_count=inp.team_count,
            entries=[],
            cap=CapVerdict(active=False, bound="none"),
            residual=inp.cr_delta,  # should be 0.0; surfaced rather than asserted
        )

    scale = p.scale_factor
    d0 = inp.pl_base_delta_mu
    pw, pa, sm = inp.placement_weight, inp.placement_amp, inp.streak_mult
    # Recomputed, not read: immune to Bug A (see module docstring, point 2). Needs
    # only `cr_before` + `pl_base_delta_mu` + params — no player state at all.
    scf = M.soft_cap_factor(inp.cr_before, d0, p)
    bf, df = inp.boosting_factor, inp.party_factor

    d1 = d0 * pw
    d2 = d1 * pa
    d3 = d2 * sm
    d4 = d3 * scf
    d5 = d4 * bf
    d6 = d5 * df

    entries: list[LedgerEntry] = []
    running = 0.0
    chain_steps: list[tuple[LedgerKind, float, float | None]] = [
        ("base", d0, None),
        ("placement", d1 - d0, pw),
        ("provisional", d2 - d1, pa),
        ("streak", d3 - d2, sm),
        ("soft_cap", d4 - d3, scf),
        ("boosting", d5 - d4, bf),
        ("party", d6 - d5, df),
    ]
    for kind, mu_step, mult in chain_steps:
        pdl = mu_step * scale
        running += pdl
        entries.append(LedgerEntry(kind, pdl, mult, running, True))

    # Dispersion: derived, not read (immune to Bug B). `final_delta_mu` is the
    # engine's own persisted post-clamp step, so this difference is exact.
    dispersion_pdl = (inp.final_delta_mu - d6) * scale
    running += dispersion_pdl
    entries.append(LedgerEntry("dispersion", dispersion_pdl, None, running, True))
    post_chain_cr = running  # == final_delta_mu * scale

    unrecoverable: list[str] = []
    fidelity: Fidelity = "exato" if inp.explain_version >= 1 else "derivado"

    cap_active = p.caps is not None
    cap_verdict: CapVerdict
    lump = False  # True => everything past the chain collapses into one plug entry

    if not cap_active:
        cap_verdict = CapVerdict(active=False, bound="none")
        confidence = inp.confidence_cr if inp.confidence_cr is not None else (
            inp.cr_delta - post_chain_cr
        )
        running += confidence
        entries.append(LedgerEntry("confidence", confidence, None, running, True))
    elif inp.cap_facts is not None:
        # Tier A — exact replay of the cap decision on the persisted raw delta.
        cp = p.caps
        assert cp is not None  # cap_active implies this; narrows for mypy
        cf = inp.cap_facts
        raw = inp.pre_cap_cr_delta if inp.pre_cap_cr_delta is not None else (
            post_chain_cr + (inp.confidence_cr or 0.0)
        )
        dec = C.decide_pdl_cap(
            raw,
            inp.placement,
            inp.team_count,
            composite_win=cf.composite_win,
            composite_loss=cf.composite_loss,
            cp=cp,
            gain_floor_mult=cf.gain_floor_mult,
        )
        confidence = inp.confidence_cr if inp.confidence_cr is not None else (raw - post_chain_cr)
        running += confidence
        entries.append(LedgerEntry("confidence", confidence, None, running, True))
        cap_term = dec.value - raw
        running += cap_term
        entries.append(LedgerEntry("cap", cap_term, None, running, True))
        cap_verdict = CapVerdict(
            active=True,
            bound=dec.bound,
            gain_cap=dec.hi,
            loss_cap=dec.lo,
            min_gain=dec.floor,
            raw_pdl=raw,
            adjustment_pdl=cap_term,
            mismatch_override=cf.mismatch_override,
            high_cr_scale=cf.high_cr_scale,
            composite_win=cf.composite_win,
        )
    else:
        # Tier B — legacy row, no persisted cap block. Try the "provably did not
        # bind" probe; a value near the CR-space zero floor is excluded from the
        # probe entirely, since a floored cr_after can mimic ANY cap outcome and
        # would make a "not bound" verdict unsound.
        cp = p.caps
        assert cp is not None
        near_zero_floor = inp.cr_after <= _RECONCILE_EPS
        can_recompute = (
            inp.state is not None and inp.lobby_mean_mu is not None and not near_zero_floor
        )
        if can_recompute:
            assert inp.state is not None and inp.lobby_mean_mu is not None
            ovr = C.mismatch_override(
                inp.state.mu,
                inp.lobby_mean_mu,
                sigma=inp.state.sigma,
                games=inp.state.matches_played,
                cp=cp,
            )
            hcs = C.high_cr_scale(inp.cr_before, cp)
            comp_win = C.composite_win_mult(ovr, hcs, 1.0, cp)
            lo, hi = C.cap_bounds(inp.placement, inp.team_count, comp_win, 1.0, cp)
            floor = C.min_gain(inp.placement, inp.team_count, cp) * max(
                0.0, min(1.0, inp.gain_floor_mult)
            )
            candidates: list[tuple[float, CapBound]] = [(lo, "loss_cap"), (hi, "gain_cap")]
            if floor > 0.0:
                candidates.append((min(floor, hi), "min_gain"))
            hit = next(
                (bound for c, bound in candidates if abs(inp.cr_delta - c) < _RECONCILE_EPS),
                None,
            )
            if hit is None:
                # PROVABLY not bound: apply_pdl_cap only ever returns the raw value
                # untouched or exactly one of {lo, hi, min(floor,hi)}.
                confidence = inp.cr_delta - post_chain_cr
                running += confidence
                entries.append(LedgerEntry("confidence", confidence, None, running, True))
                entries.append(LedgerEntry("cap", 0.0, None, running, True))
                cap_verdict = CapVerdict(
                    active=True,
                    bound="none",
                    gain_cap=hi,
                    loss_cap=lo,
                    min_gain=floor,
                    raw_pdl=inp.cr_delta,
                    adjustment_pdl=0.0,
                    mismatch_override=ovr,
                    high_cr_scale=hcs,
                    composite_win=comp_win,
                )
                fidelity = "derivado"
            else:
                # It landed exactly on a bound: we know WHICH rule, but not the raw
                # pre-cap amount (many raws collapse to the same clamped output) —
                # confidence and the cap adjustment are inseparable. Lump.
                lump = True
                cap_verdict = CapVerdict(
                    active=True,
                    bound=hit,
                    gain_cap=hi,
                    loss_cap=lo,
                    min_gain=floor,
                    raw_pdl=None,
                    adjustment_pdl=None,
                    mismatch_override=ovr,
                    high_cr_scale=hcs,
                    composite_win=comp_win,
                )
                fidelity = "parcial"
        else:
            lump = True
            cap_verdict = CapVerdict(active=True, bound="none")
            fidelity = "parcial"
            if inp.state is None or inp.lobby_mean_mu is None:
                unrecoverable.append("cap_bounds")
            if near_zero_floor:
                unrecoverable.append("zero_floor_ambiguity")

    if lump:
        adjust = inp.cr_delta - post_chain_cr
        running = post_chain_cr + adjust
        entries.append(LedgerEntry("display_adjust", adjust, None, running, False))
        unrecoverable.extend(x for x in ("confidence", "cap_adjustment") if x not in unrecoverable)
    else:
        # Close by construction: whatever is left after every known-exact
        # contribution (including a genuine zero-floor event) becomes the final
        # entry, so `entries` always reconciles to `cr_delta` — never hidden in a
        # bare `residual`. A nonzero gap that ISN'T explained by the zero floor is
        # an unexpected reconciliation failure (should not happen for well-formed
        # input); it is still surfaced honestly rather than silently absorbed.
        gap = inp.cr_delta - running
        if abs(gap) > _RECONCILE_EPS:
            zero_floored = inp.cr_after <= _RECONCILE_EPS and (inp.cr_before + running) < 0.0
            final_kind: LedgerKind = "zero_floor" if zero_floored else "display_adjust"
            running += gap
            entries.append(LedgerEntry(final_kind, gap, None, running, zero_floored))
            if not zero_floored:
                fidelity = "parcial"
                unrecoverable.append("residual_gap")

    residual = inp.cr_delta - running
    return PdlExplanation(
        fidelity=fidelity,
        cr_before=inp.cr_before,
        cr_after=inp.cr_after,
        cr_delta=inp.cr_delta,
        placement=inp.placement,
        team_count=inp.team_count,
        entries=entries,
        cap=cap_verdict,
        residual=residual,
        unrecoverable=tuple(unrecoverable),
    )


__all__ = [
    "ExplainState",
    "ExplainInput",
    "LedgerEntry",
    "CapVerdict",
    "PdlExplanation",
    "LedgerKind",
    "Fidelity",
    "explain",
    "explain_result",
]
