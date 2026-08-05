"""Raio-X do resultado — the full transparent PDL breakdown ("ver cálculo completo").

Served by ``GET /api/v1/match/{matchId}/pdl/{riotId}`` (see
``arena/api/routers/match.py``), fetched on demand when the user expands the
drill-down — kept off the match-detail/history-list payloads so those stay light
(see ``arena/services/pdl_explain_service.py`` for why this is a separate route).

CR/PDL space only — never mu/sigma/lobby-mean (ToS rule, see
``arena/schemas/common.py``'s docstring). All labels are PT-BR; ``kind`` fields are
stable machine keys for the frontend, not display strings.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from arena.schemas.common import ArenaModel

CapRule = Literal["nenhum", "teto_ganho", "teto_perda", "piso_ganho"]
Fidelity = Literal["exato", "derivado", "parcial"]


class PdlLedgerEntry(ArenaModel):
    """One additive line in the PDL ledger. ``pdl`` is the largest-remainder-
    apportioned integer shown to the user; the visible ``pdl`` values across a
    ``PdlExplanation.entries`` list always sum to exactly ``totalPdl`` — see
    ``PdlExplanation`` for the apportionment policy. ``pdl_exact`` carries the
    unrounded truth for anything that wants it (e.g. a tooltip)."""

    kind: str
    label: str
    icon: str
    pdl: int
    pdl_exact: float
    multiplier_pct: float | None = None
    running_total: int
    exact: bool
    note: str | None = None


class PdlCapFactors(ArenaModel):
    """The cap layer's win-side multipliers, as signed percentages. Never carries
    mu/sigma/lobby-mean — see ``arena/rating/types.py::CapExplanation``'s docstring
    for why those must stay engine-internal."""

    mismatch_bonus_pct: float | None = None
    high_cr_reduction_pct: float | None = None
    composite_pct: float | None = None


class PdlCurvePoint(ArenaModel):
    """One placement's BASELINE (composite=1.0, i.e. no mismatch/high-CR
    adjustment) cap bounds for this match's team count — the neutral curve every
    player's own ``PdlCap.gain_cap``/``loss_cap`` is a composite-adjusted version
    of. Answers "why does 1st cap at +40 while 4th only caps its loss at -30" —
    the shape of the curve itself, independent of who played."""

    placement: int
    gain_cap: int
    loss_cap: int
    min_gain: int


class PdlLobbyEntry(ArenaModel):
    """One participant's placement + PDL result IN THIS SAME MATCH — already
    visible on the match-detail page, repeated here so "why is my PDL different
    from theirs" has a direct, side-by-side answer without navigating away.
    CR/PDL only, same as everywhere else in this schema."""

    riot_id: str
    name: str
    placement: int
    cr_delta: int
    is_you: bool


class PdlCap(ArenaModel):
    active: bool
    rule: CapRule
    gain_cap: int | None = None
    loss_cap: int | None = None
    min_gain: int | None = None
    raw_pdl: int | None = None
    applied_pdl: int | None = None
    adjustment_pdl: int | None = None
    factors: PdlCapFactors = Field(default_factory=PdlCapFactors)
    label: str | None = None
    description: str | None = None
    #: The whole placement curve for this team_count (baseline, composite=1.0) —
    #: empty when no cap curve is configured for this team_count/season.
    placement_curve: list[PdlCurvePoint] = Field(default_factory=list)


class PdlExplanation(ArenaModel):
    """The full reconciling ledger for one player's PDL result in one match.

    Integer apportionment policy: ``entries[i].pdl`` values are produced via
    largest-remainder (Hare) apportionment against ``total_pdl`` so the displayed
    lines sum EXACTLY to the displayed total (never off by a rounding unit) —
    ``pdl_exact``/``total_pdl_exact`` carry the unrounded numbers. ``reconciles``
    and ``residual_pdl`` are computed from the unrounded (exact) values, not the
    displayed integers.
    """

    fidelity: Fidelity
    cr_before: int
    cr_after: int
    total_pdl: int
    total_pdl_exact: float
    placement: int
    team_count: int
    entries: list[PdlLedgerEntry] = Field(default_factory=list)
    cap: PdlCap
    reconciles: bool
    residual_pdl: float
    unrecoverable: list[str] = Field(default_factory=list)
    summary: str
    #: Every participant's placement + PDL result in this same match, sorted by
    #: placement — the direct "what did the other teams get" answer. Empty only
    #: if the match's own participant rows couldn't be resolved (should not
    #: happen in practice; this route already 404s if the match itself is missing).
    lobby: list[PdlLobbyEntry] = Field(default_factory=list)
