"""PdlExplainService — builds the full Raio-X do resultado ledger for one
participant of one match (the "ver cálculo completo" drill-down, v1.4).

Deliberately its own route/service, not folded into the match-detail/history
payloads: a full ``PdlExplanation`` is ~1KB and those payloads already carry a
whole lobby / a page of history, so eagerly attaching it would bloat the
Redis/Cloudflare cache footprint for a detail most requests never expand.
``arena/api/routers/match.py``'s ``GET /match/{matchId}/pdl/{riotId}`` calls this
on demand instead.

Tier A (``explainVersion >= 1``, matches rated after this feature shipped) needs
ZERO extra queries — the persisted ``match_participants.modifiers`` JSONB is
self-contained. Tier B (legacy rows) needs the lobby's OTHER participants'
``state_before`` to recompute the cap layer's mismatch-override / high-CR-scale
bounds; since this service is scoped to ONE match at a time (not a whole history
page), that is a single small query bounded by lobby size (6-8 rows), not the
bulk multi-match aggregate a history-list endpoint would otherwise need.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from arena.rating import DEFAULT_PARAMS
from arena.rating.caps import CapBound, cap_bounds, min_gain
from arena.rating.explain import (
    ExplainInput,
    ExplainState,
    PdlExplanation as EnginePdlExplanation,
    explain,
)
from arena.rating.params import RatingParams
from arena.rating.types import CapExplanation
from arena.schemas.explain import (
    CapRule,
    PdlCap,
    PdlCapFactors,
    PdlCurvePoint,
    PdlExplanation,
    PdlLedgerEntry,
    PdlLobbyEntry,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class PdlExplainNotFound(Exception):
    """The match, or this player's participation in it, could not be found."""


_KIND_LABELS: dict[str, tuple[str, str]] = {
    "base": ("Resultado do confronto", "swords"),
    "provisional": ("Partidas de posicionamento", "hourglass_top"),
    "soft_cap": ("Proteção de topo", "vertical_align_top"),
    "boosting": ("Penalidade de integridade", "gpp_bad"),
    "party": ("Grupo recorrente", "group"),
    "dispersion": ("Limite de variação", "speed"),
    "confidence": ("Consolidação da sua estimativa", "insights"),
    "zero_floor": ("PDL mínimo (0)", "block"),
    "display_adjust": ("Ajuste de exibição", "help"),
}

_CAP_RULE: dict[CapBound, tuple[CapRule, str]] = {
    "none": ("nenhum", ""),
    "gain_cap": ("teto_ganho", "Teto de ganho da colocação"),
    "loss_cap": ("teto_perda", "Limite de perda"),
    "min_gain": ("piso_ganho", "Piso de ganho da colocação"),
}


def _pct(mult: float | None) -> float | None:
    if mult is None:
        return None
    return round((mult - 1.0) * 100.0, 1)


def _entry_label(kind: str, *, placement: int, team_count: int, multiplier: float | None) -> tuple[str, str]:
    if kind == "placement":
        # NOT "Colocação" — that word is already the compact carousel's title for
        # the BROADER base+placement+provisional bundle (arena/api/routers/
        # _common.py::map_modifiers). Reusing it here for just the placement-curve
        # MULTIPLIER's own marginal contribution means the same word points at two
        # different PDL amounts one click apart (the drill-down's own "Resultado
        # do confronto" line is the other half of what the compact chip bundles) —
        # confusing, and exactly the kind of inconsistency this feature exists to
        # remove. "Peso da colocação" names the mechanism (the curve's weight)
        # without colliding with the summary term.
        return f"Peso da colocação ({placement}º de {team_count})", "leaderboard"
    if kind == "streak":
        up = (multiplier or 1.0) > 1.0
        return (
            ("Sequência de vitórias", "local_fire_department")
            if up
            else ("Amortecedor de derrotas", "shield_moon")
        )
    if kind == "cap":
        return "Ajuste do teto/piso de colocação", "vertical_align_top"
    return _KIND_LABELS.get(kind, (kind, "help"))


def _apportion(values: list[float], target: int) -> list[int]:
    """Largest-remainder (Hare) apportionment: round each value individually,
    then nudge the entries with the largest rounding error (in the direction
    needed) by +-1 until the integers sum EXACTLY to ``target``. Guarantees
    ``sum(result) == target`` for any finite, non-empty input, including
    negatives. ``values=[]`` returns ``[]`` unconditionally — there is nowhere to
    place a nonzero target with zero entries; callers only ever pass an empty
    list alongside a zero target (an explanation with no ledger entries only
    happens for the frozen/ineligible case, where ``cr_delta`` is always 0.0)."""
    if not values:
        return []
    base = [round(v) for v in values]
    diff = target - sum(base)
    if diff == 0:
        return base
    remainders = sorted(
        range(len(values)), key=lambda i: values[i] - base[i], reverse=diff > 0
    )
    n = len(remainders)
    for k in range(abs(diff)):
        idx = remainders[k % n]
        base[idx] += 1 if diff > 0 else -1
    return base


def explain_input_from_jsonb(
    d: dict[str, Any],
    *,
    placement: int,
    team_count: int,
    cr_before: float,
    cr_after: float,
    cr_delta: float,
    eligible: bool,
    params: RatingParams,
    state: ExplainState | None,
    lobby_mean_mu: float | None,
) -> ExplainInput:
    def g(*keys: str, default: float = 1.0) -> float:
        for k in keys:
            if k in d:
                return float(d[k])
        return default

    def cg(block: dict[str, Any], key: str, default: float) -> float:
        # dict.get(key, default) only falls back when the key is ABSENT -- a
        # persisted `null` (see _finite_or_none in rating_service.py, for the
        # +-inf "no curve configured for this team_count" cap_bounds() sentinel)
        # has to be caught explicitly, or float(None) raises.
        v = block.get(key)
        return default if v is None else float(v)

    explain_version = int(d.get("explainVersion") or 0)
    cap_facts: CapExplanation | None = None
    cap_block = d.get("cap")
    if isinstance(cap_block, dict):
        # Only mismatch_override / high_cr_scale / composite_win / composite_loss
        # / gain_floor_mult are actually READ by explain()'s Tier-A branch (it
        # recomputes lo/hi/floor fresh via decide_pdl_cap) -- the remaining
        # CapExplanation fields are unused placeholders here, never read.
        cap_facts = CapExplanation(
            active=bool(cap_block.get("active", True)),
            bound=cap_block.get("bound", "none"),
            raw_cr_delta=0.0,
            capped_cr_delta=0.0,
            lo=cg(cap_block, "lo", float("-inf")),
            hi=cg(cap_block, "hi", float("inf")),
            min_gain=float(cap_block.get("minGain", 0.0)),
            mismatch_override=float(cap_block.get("mismatchOverride", 1.0)),
            high_cr_scale=float(cap_block.get("highCrScale", 1.0)),
            composite_win=float(cap_block.get("compositeWin", 1.0)),
            composite_loss=float(cap_block.get("compositeLoss", 1.0)),
            gain_floor_mult=float(cap_block.get("gainFloorMult", 1.0)),
            team_count=int(cap_block.get("teamCount") or team_count),
            lobby_mean_mu=0.0,
        )

    return ExplainInput(
        params=params,
        placement=placement,
        team_count=team_count,
        eligible=eligible,
        cr_before=cr_before,
        cr_after=cr_after,
        cr_delta=cr_delta,
        pl_base_delta_mu=g("plBaseDeltaMu", default=0.0),
        final_delta_mu=g("finalDeltaMu", default=0.0),
        placement_weight=g("placementWeight"),
        placement_amp=g("placementAmp"),
        streak_mult=g("streakMult"),
        boosting_factor=g("boostingFactor"),
        party_factor=g("partyFactor"),
        explain_version=explain_version,
        params_epoch=d.get("paramsEpoch"),
        confidence_cr=(float(d["confidencePdl"]) if "confidencePdl" in d else None),
        pre_cap_cr_delta=(float(d["preCapCrDelta"]) if "preCapCrDelta" in d else None),
        cap_facts=cap_facts,
        state=state,
        lobby_mean_mu=lobby_mean_mu,
        gain_floor_mult=1.0,
    )


def lobby_context_from_rows(
    rows: Iterable[tuple[Any, Any, dict[str, Any] | None]],
) -> dict[tuple[Any, Any], tuple[ExplainState, float]]:
    """Pure batch version of the per-match lobby reconstruction that
    :meth:`PdlExplainService.explain_participant` does for a single match —
    ``(match_id, player_id) -> (self ExplainState, lobby_mean_mu excluding self)``.

    ``rows`` is every participant of every match under consideration:
    ``(match_id, player_id, state_before)``. A match is only included when
    EVERY one of its participants has ``state_before`` (mirrors ``explain()``'s
    Tier-B "all_have_state" trust requirement — one missing row degrades ALL of
    that match's participants to "parcial", same as before this helper existed).

    Lets a caller with a whole PAGE of (possibly many different) matches do ONE
    bulk query instead of paying ``explain_participant``'s per-match query once
    per row — see ``arena/api/routers/_common.py::map_modifiers``'s ``state``/
    ``lobby_mean_mu`` params, which this feeds.
    """
    by_match: dict[Any, list[tuple[Any, dict[str, Any] | None]]] = defaultdict(list)
    for match_id, player_id, state_before in rows:
        by_match[match_id].append((player_id, state_before))

    out: dict[tuple[Any, Any], tuple[ExplainState, float]] = {}
    for match_id, entries in by_match.items():
        if len(entries) < 2 or any(sb is None for _, sb in entries):
            continue
        mus = [float(sb["mu"]) for _, sb in entries if sb is not None]
        total_mu = sum(mus)
        n = len(entries)
        for (player_id, sb), mu in zip(entries, mus, strict=True):
            assert sb is not None  # narrowed by the `any(sb is None ...)` guard above
            out[(match_id, player_id)] = (
                ExplainState(
                    mu=mu,
                    sigma=float(sb["sigma"]),
                    matches_played=int(sb["matches_played"]),
                ),
                (total_mu - mu) / (n - 1),
            )
    return out


def _placement_curve(team_count: int, params: RatingParams) -> list[PdlCurvePoint]:
    """The BASELINE (composite=1.0 — no mismatch/high-CR adjustment) cap curve
    for every placement at this team count. Pure context, independent of who
    played: answers "why does 1st cap its gain at +40 while 4th's loss only caps
    at -30" as a property of the curve shape itself, not this specific match.
    Empty when no cap curve is configured for this team_count/season."""
    cp = params.caps
    if cp is None:
        return []
    base = cp.base_cap_by_placement.get(team_count)
    if base is None:
        return []
    out: list[PdlCurvePoint] = []
    for placement in range(1, len(base) + 1):
        lo, hi = cap_bounds(placement, team_count, 1.0, 1.0, cp)
        floor = min_gain(placement, team_count, cp)
        out.append(
            PdlCurvePoint(
                placement=placement,
                gain_cap=round(hi),
                loss_cap=round(lo),
                min_gain=round(floor),
            )
        )
    return out


def _cap_dto(
    exp: EnginePdlExplanation, cap_entry_exact: float | None, placement_curve: list[PdlCurvePoint]
) -> PdlCap:
    cap = exp.cap
    rule, rule_label = _CAP_RULE[cap.bound]
    description: str | None = None
    if cap.bound == "gain_cap" and cap.raw_pdl is not None and cap.gain_cap is not None:
        description = (
            f"Seu ganho bruto de {round(cap.raw_pdl):+d} PDL foi limitado ao teto de "
            f"{round(cap.gain_cap):+d} PDL desta colocação."
        )
    elif cap.bound == "loss_cap" and cap.raw_pdl is not None and cap.loss_cap is not None:
        description = (
            f"Sua perda bruta de {round(cap.raw_pdl):+d} PDL foi limitada ao teto de "
            f"{round(cap.loss_cap):+d} PDL desta colocação."
        )
    elif cap.bound == "min_gain" and cap.min_gain is not None:
        description = f"Esta colocação garante no mínimo {round(cap.min_gain):+d} PDL."
    elif cap.bound != "none" and exp.fidelity == "parcial":
        description = (
            "Esta partida foi registrada antes do detalhamento completo; o valor "
            "bruto antes do teto não foi guardado."
        )

    return PdlCap(
        active=cap.active,
        rule=rule,
        gain_cap=(round(cap.gain_cap) if cap.gain_cap is not None else None),
        loss_cap=(round(cap.loss_cap) if cap.loss_cap is not None else None),
        min_gain=(round(cap.min_gain) if cap.min_gain is not None else None),
        raw_pdl=(round(cap.raw_pdl) if cap.raw_pdl is not None else None),
        applied_pdl=(round(cap_entry_exact) if cap_entry_exact is not None else None),
        adjustment_pdl=(round(cap.adjustment_pdl) if cap.adjustment_pdl is not None else None),
        factors=PdlCapFactors(
            mismatch_bonus_pct=_pct(cap.mismatch_override),
            high_cr_reduction_pct=_pct(cap.high_cr_scale),
            composite_pct=_pct(cap.composite_win),
        ),
        label=(rule_label or None),
        description=description,
        placement_curve=placement_curve,
    )


def _to_dto(
    exp: EnginePdlExplanation,
    *,
    lobby: list[PdlLobbyEntry] | None = None,
    placement_curve: list[PdlCurvePoint] | None = None,
) -> PdlExplanation:
    lobby = lobby or []
    placement_curve = placement_curve or []
    exact_values = [e.pdl for e in exp.entries]
    total_int = round(exp.cr_delta)
    apportioned = _apportion(exact_values, total_int)

    entries: list[PdlLedgerEntry] = []
    running = 0
    for e, pdl_int in zip(exp.entries, apportioned, strict=True):
        running += pdl_int
        label, icon = _entry_label(
            e.kind, placement=exp.placement, team_count=exp.team_count, multiplier=e.multiplier
        )
        entries.append(
            PdlLedgerEntry(
                kind=e.kind,
                label=label,
                icon=icon,
                pdl=pdl_int,
                pdl_exact=round(e.pdl, 3),
                multiplier_pct=_pct(e.multiplier),
                running_total=running,
                exact=e.exact,
                note=(
                    "Esta partida foi registrada antes do detalhamento completo; "
                    "os valores acima aparecem consolidados."
                    if not e.exact
                    else None
                ),
            )
        )

    cap_entry = next((e for e in exp.entries if e.kind == "cap"), None)
    non_zero = [e for e in entries if e.pdl != 0 or e.kind in ("base", "display_adjust")]
    summary = " · ".join(f"{e.label} {e.pdl:+d}" for e in non_zero[:4])
    if len(non_zero) > 4:
        summary += f" · = {total_int:+d}"

    return PdlExplanation(
        fidelity=exp.fidelity,
        cr_before=round(exp.cr_before),
        cr_after=round(exp.cr_after),
        total_pdl=total_int,
        total_pdl_exact=round(exp.cr_delta, 3),
        placement=exp.placement,
        team_count=exp.team_count,
        entries=entries,
        cap=_cap_dto(exp, cap_entry.pdl if cap_entry is not None else None, placement_curve),
        reconciles=abs(exp.residual) < 1e-6,
        residual_pdl=round(exp.residual, 6),
        unrecoverable=list(exp.unrecoverable),
        summary=summary or f"= {total_int:+d} PDL",
        lobby=lobby,
    )


class PdlExplainService:
    """Builds one participant's full :class:`PdlExplanation` on demand."""

    async def explain_participant(
        self, session: "AsyncSession", *, match_id: str, riot_id: str
    ) -> PdlExplanation:
        from sqlalchemy import select

        from arena.api.routers._common import compose_riot_id, split_riot_id
        from arena.db import models as m

        name_part, tag_part = split_riot_id(riot_id)
        tag_value = tag_part.lstrip("#")

        row = (
            await session.execute(
                select(m.MatchParticipant)
                .join(m.Player, m.Player.id == m.MatchParticipant.player_id)
                .where(
                    m.MatchParticipant.match_id == match_id,
                    m.Player.summoner_name.ilike(name_part),
                    m.Player.tag_line == tag_value,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            raise PdlExplainNotFound(f"{match_id}/{riot_id}")

        d: dict[str, Any] = row.modifiers or {}
        explain_version = int(d.get("explainVersion") or 0)
        team_count = int(d.get("teamCount") or 0)

        # ONE bulk query for the whole lobby (bounded to 6-8 rows — this route is
        # a single-match, on-demand drill-down, not the hot history-list path
        # lobby_context_from_rows exists to spare from N+1). Covers two needs at
        # once: the legacy-row (Tier B) cap reconstruction below, AND the
        # cross-team "what did everyone else get" comparison this always builds
        # now regardless of tier — see PdlExplanation.lobby's docstring.
        lobby_rows = (
            await session.execute(
                select(
                    m.MatchParticipant.player_id,
                    m.MatchParticipant.state_before,
                    m.MatchParticipant.team_id,
                    m.MatchParticipant.placement,
                    m.MatchParticipant.cr_delta,
                    m.Player.summoner_name,
                    m.Player.tag_line,
                )
                .join(m.Player, m.Player.id == m.MatchParticipant.player_id)
                .where(m.MatchParticipant.match_id == match_id)
            )
        ).all()

        if team_count <= 0:
            team_count = len({r.team_id for r in lobby_rows}) or 1

        state: ExplainState | None = None
        lobby_mean_mu: float | None = None
        # Tier A (explainVersion>=1) is fully self-contained; only a legacy, still
        # -eligible row needs the reconstruction (the query above already paid
        # for itself either way).
        if row.eligible and explain_version < 1:
            self_sb = row.state_before
            others_mu: list[float] = []
            all_have_state = self_sb is not None
            for r in lobby_rows:
                if str(r.player_id) == str(row.player_id):
                    continue
                if r.state_before is None:
                    all_have_state = False
                    continue
                others_mu.append(float(r.state_before["mu"]))
            if all_have_state and others_mu and self_sb is not None:
                lobby_mean_mu = sum(others_mu) / len(others_mu)
                state = ExplainState(
                    mu=float(self_sb["mu"]),
                    sigma=float(self_sb["sigma"]),
                    matches_played=int(self_sb["matches_played"]),
                )

        lobby = sorted(
            (
                PdlLobbyEntry(
                    riot_id=compose_riot_id(r.summoner_name, r.tag_line),
                    name=r.summoner_name or "Desconhecido",
                    placement=int(r.placement),
                    cr_delta=round(r.cr_delta),
                    is_you=str(r.player_id) == str(row.player_id),
                )
                for r in lobby_rows
            ),
            key=lambda e: e.placement,
        )

        inp = explain_input_from_jsonb(
            d,
            placement=row.placement,
            team_count=team_count,
            cr_before=row.cr_before,
            cr_after=row.cr_after,
            cr_delta=row.cr_delta,
            eligible=row.eligible,
            params=DEFAULT_PARAMS,
            state=state,
            lobby_mean_mu=lobby_mean_mu,
        )
        engine_exp = explain(inp)
        return _to_dto(
            engine_exp,
            lobby=lobby,
            placement_curve=_placement_curve(team_count, DEFAULT_PARAMS),
        )


def get_pdl_explain_service() -> PdlExplainService:
    return PdlExplainService()


__all__ = [
    "PdlExplainService",
    "PdlExplainNotFound",
    "get_pdl_explain_service",
    "lobby_context_from_rows",
    "explain_input_from_jsonb",
]
