"""Shared router helpers — the projection layer between our gamified rating
engine / SQLAlchemy models and the ``api_contract_v1`` DTOs.

Everything user-facing here is **CR/Pontos** (never mu/sigma) and PT-BR. The
central jobs of this module:

* ``cr_of`` — display CR via the engine ``to_cr(mu, sigma)`` (gamified, not
  ``round(mu*200)``); ``cr_band`` — a CR-space uncertainty band for the profile
  chart, derived from sigma but never exposing sigma.
* ``tier_from_rank`` — display tier (top1/top10/.../none) from the global rank.
* ``is_provisional`` — provisional flag from the placement-match window.
* ``map_modifiers`` — persisted ``modifiers`` JSONB → ``[{kind,label,value,icon,
  pdlImpact}]`` in PT-BR (colocação/sequência/proteção/penalidade/confiança/teto-
  piso). ``pdlImpact`` is real, sourced from ``arena.rating.explain.explain()``
  (Raio-X do resultado, v1.4) — never a client-side reverse-engineered guess.
* avatar / champion gradient placeholders (ToS: no real champion art).
* DB dependency + season resolution (integer contract season → ``seasons`` row).

These helpers are deliberately pure where possible so they are trivially
verifiable without a live database.
"""

from __future__ import annotations

import colorsys
import hashlib
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from arena.schemas import AvatarColors, Modifier, TierKey

if TYPE_CHECKING:  # avoid importing the DB/redis/rating stack at module import time.
    from sqlalchemy.ext.asyncio import AsyncSession

    from arena.rating import AppliedModifiers
    from arena.rating.explain import ExplainState

# Queue ids per contract: 3v3 = 1750, 2v2 = 1700.
QUEUE_BY_FORMAT: dict[str, int] = {"3v3": 1750, "2v2": 1700}
FORMAT_BY_QUEUE: dict[int, str] = {v: k for k, v in QUEUE_BY_FORMAT.items()}

# Subteam count per format (placement upper bound): 3v3 → 6 of 3, 2v2 → 8 of 2.
SUBTEAMS_BY_FORMAT: dict[str, int] = {"3v3": 6, "2v2": 8}

# Deterministic gradient palette for placeholder avatars/champions (ToS — no art).
# Placeholder avatar gradients are generated per seed in ``avatar_for`` as
# HARMONIOUS analogous HSL pairs (deep base hue + brighter neighbour) — matching
# the design palette. No fixed complementary-pair table (those mix to mud).


# ---------------------------------------------------------------------------
# CR display (gamified) — never expose mu/sigma
# ---------------------------------------------------------------------------


def cr_of(mu: float, sigma: float) -> int:
    """Display CR/Pontos from the gamified engine transform ``to_cr(mu, sigma)``.

    Conservative: increasing in mu, decreasing in sigma. Rounded to an int for
    the wire. This is the ONLY place CR is derived in the read API.
    """
    from arena.rating import DEFAULT_PARAMS, to_cr

    return round(to_cr(mu, sigma, DEFAULT_PARAMS))


def cr_band(mu: float, sigma: float) -> tuple[int, int]:
    """CR-space uncertainty band (lo, hi) for the profile chart.

    ``lo`` is the conservative CR (the displayed value); ``hi`` reflects the
    optimistic CR at one fewer sigma of caution. Sigma itself is never surfaced.
    """
    from arena.rating import DEFAULT_PARAMS, to_cr

    lo = round(to_cr(mu, sigma, DEFAULT_PARAMS))
    hi = round(to_cr(mu, max(sigma - 1.0 * sigma / 3.0, 0.0), DEFAULT_PARAMS))
    return min(lo, hi), max(lo, hi)


# ---------------------------------------------------------------------------
# Tier & provisional
# ---------------------------------------------------------------------------


def tier_from_rank(rank: int) -> TierKey:
    """Display tier derived from the 1-based global rank within the format/scope."""
    if rank <= 0:
        return "none"
    if rank == 1:
        return "top1"
    if rank <= 10:
        return "top10"
    if rank <= 50:
        return "top50"
    if rank <= 100:
        return "top100"
    if rank <= 500:
        return "top500"
    return "none"


def is_provisional(placement_matches_remaining: int) -> bool:
    """Provisional while inside the placement-match window (engine semantics)."""
    return placement_matches_remaining > 0


# ---------------------------------------------------------------------------
# Modifiers: AppliedModifiers (engine) → contract Modifier list (PT-BR)
# ---------------------------------------------------------------------------

# Engine multipliers are centered on 1.0; the contract wants a signed "value"
# expressing the modifier's contribution. We render multipliers as a signed
# percentage of the base delta (e.g. 1.18 → +18, 0.25 → -75) and additive deltas
# as their CR-scaled amount. Labels/icons are PT-BR + Material Symbol names.


def _pct(mult: float) -> float:
    """Multiplier (centered on 1.0) → signed percentage contribution."""
    return round((mult - 1.0) * 100.0, 1)


# PT-BR machine kinds + labels for the cap layer, keyed by the engine's English
# CapBound literal (kept internal to arena/rating/) — matches CapRule in
# arena/schemas/explain.py. Shared by the exact chip (fresh/derivado rows, where
# the cap's own PDL contribution is known) and the lumped "ajuste" chip (parcial
# rows, where we at least know WHICH rule bound even though its exact share of
# the total isn't recoverable — see map_modifiers' display_adjust branch below).
_CAP_CHIP: dict[str, tuple[str, str, str]] = {
    "gain_cap": ("teto_ganho", "Teto de ganho da colocação", "vertical_align_top"),
    "loss_cap": ("teto_perda", "Limite de perda", "vertical_align_bottom"),
    "min_gain": ("piso_ganho", "Piso de ganho da colocação", "expand_less"),
}


def map_modifiers(
    applied: "AppliedModifiers | dict[str, Any]",
    *,
    placement: int,
    team_count: int,
    cr_before: float,
    cr_after: float,
    cr_delta: float,
    eligible: bool = True,
    state: "ExplainState | None" = None,
    lobby_mean_mu: float | None = None,
) -> list[Modifier]:
    """Map a persisted modifiers snapshot to the contract's PDL breakdown.

    Raio-X do resultado (v1.4): every emitted ``Modifier`` now carries a REAL
    ``pdl_impact`` sourced from :func:`arena.rating.explain.explain`'s reconciling
    ledger — never a client-side reverse-engineered guess (see
    ``frontend/src/routes/profileRatingSignalModel.ts``'s docstring for the bug
    this fixes). Kinds/labels/trigger conditions match the pre-v1.4 taxonomy for
    backward compatibility with the existing carousel UI (accepts either the
    dataclass, fresh from the engine, or its JSONB dict form as persisted on
    ``match_participants.modifiers``); the exhaustive, granular per-step
    breakdown lives behind the "ver cálculo completo" drill-down
    (``GET /match/{matchId}/pdl/{riotId}``,
    ``arena/services/pdl_explain_service.py``). Never carries mu/sigma.

    ``state``/``lobby_mean_mu`` are the OPTIONAL legacy-row (Tier B) lobby
    reconstruction — see :func:`arena.services.pdl_explain_service.
    lobby_context_from_rows` for the bulk (one-query-per-page) way callers get
    these without N+1. Omitting them (the default) degrades every legacy row to
    the honest but opaque "ajuste de exibição" lump; supplying them lets
    ``explain()`` prove, in the common case, that the cap didn't bind and
    attribute the remainder precisely (e.g. "Consolidação da sua estimativa")
    instead — this is what makes the compact card match the drill-down.
    """
    from arena.rating import DEFAULT_PARAMS
    from arena.rating.explain import explain
    from arena.services.pdl_explain_service import explain_input_from_jsonb

    d = applied if isinstance(applied, dict) else _applied_to_dict(applied)
    inp = explain_input_from_jsonb(
        d,
        placement=placement,
        team_count=team_count,
        cr_before=cr_before,
        cr_after=cr_after,
        cr_delta=cr_delta,
        eligible=eligible,
        params=DEFAULT_PARAMS,
        state=state,
        lobby_mean_mu=lobby_mean_mu,
    )
    if not eligible:
        return []
    exp = explain(inp)
    by_kind = {e.kind: e.pdl for e in exp.entries}
    out: list[Modifier] = []

    # Colocação — base PL result + placement weight + provisional amplification,
    # bundled into one chip (matches the existing "Você ganhou N PDL por terminar
    # em Xº" copy, which has always treated colocação as inclusive of the base).
    placement_mult = inp.placement_weight * inp.placement_amp
    if abs(placement_mult - 1.0) > 1e-9 or abs(by_kind.get("base", 0.0)) > 1e-9:
        amp_note = " (provisória)" if inp.placement_amp != 1.0 else ""
        out.append(
            Modifier(
                kind="colocacao",
                label=f"Colocação{amp_note}",
                value=_pct(placement_mult),
                icon="leaderboard",
                pdl_impact=(
                    by_kind.get("base", 0.0)
                    + by_kind.get("placement", 0.0)
                    + by_kind.get("provisional", 0.0)
                ),
            )
        )

    # Sequência — win-streak bonus / loss-streak dampener.
    if abs(inp.streak_mult - 1.0) > 1e-9:
        streak_up = inp.streak_mult > 1.0
        out.append(
            Modifier(
                kind="sequencia",
                label="Sequência de vitórias" if streak_up else "Amortecedor de derrotas",
                value=_pct(inp.streak_mult),
                icon="local_fire_department" if streak_up else "shield_moon",
                pdl_impact=by_kind.get("streak", 0.0),
            )
        )

    # Proteção — soft-cap diminishing returns near the top. Recomputed fresh by
    # explain() (immune to the historical soft_cap_factor pollution bug); in
    # practice this essentially never fires — soft_cap_threshold=5000 sits above
    # reachable production CR.
    soft_cap_pdl = by_kind.get("soft_cap", 0.0)
    if abs(soft_cap_pdl) > 1e-6:
        out.append(
            Modifier(
                kind="protecao",
                label="Proteção de topo",
                value=0.0,
                icon="vertical_align_top",
                pdl_impact=soft_cap_pdl,
            )
        )

    # Penalidade — boosting penalty (integrity).
    if inp.boosting_factor < 1.0 - 1e-9:
        out.append(
            Modifier(
                kind="penalidade",
                label="Penalidade de boosting",
                value=_pct(inp.boosting_factor),
                icon="gpp_bad",
                pdl_impact=by_kind.get("boosting", 0.0),
            )
        )
    # Grupo — premade dampener (solo wins are worth more).
    if inp.party_factor < 1.0 - 1e-9:
        out.append(
            Modifier(
                kind="grupo",
                label="Penalidade de grupo",
                value=_pct(inp.party_factor),
                icon="group",
                pdl_impact=by_kind.get("party", 0.0),
            )
        )
    # Dispersão — the mu-space dispersion cap (previously conflated with the
    # PDL cap/floor by a bug; now correctly ONLY this). value carries the real
    # PDL amount (there is no natural "percentage" for a clamp event).
    dispersion_pdl = by_kind.get("dispersion", 0.0)
    if abs(dispersion_pdl) > 1e-6:
        out.append(
            Modifier(
                kind="penalidade",
                label="Variação limitada",
                value=round(dispersion_pdl, 1),
                icon="speed",
                pdl_impact=dispersion_pdl,
            )
        )

    # Confiança — new (v1.4): the -3*Delta(sigma) term, a real additive PDL
    # contribution that sat entirely outside the old modifier chain and every
    # prior card. Usually positive (sigma converges most matches).
    confidence_pdl = by_kind.get("confidence", 0.0)
    if abs(confidence_pdl) > 0.05:
        out.append(
            Modifier(
                kind="confianca",
                label="Consolidação da sua estimativa",
                value=0.0,
                icon="insights",
                pdl_impact=confidence_pdl,
            )
        )

    # Teto/piso — new (v1.4): only when the cap layer actually moved the
    # result AND we have full fidelity for the split (a legacy row where the
    # cap bound is intentionally left out here — that nuance belongs in the
    # drill-down, not a compact chip that can't explain itself).
    if exp.cap.bound != "none" and "cap" in by_kind and exp.fidelity != "parcial":
        cap_pdl = by_kind["cap"]
        kind, label, icon = _CAP_CHIP.get(
            exp.cap.bound, ("teto_ganho", "Ajuste do teto/piso de colocação", "vertical_align_top")
        )
        out.append(
            Modifier(
                kind=kind,
                label=label,
                value=0.0,
                icon=icon,
                pdl_impact=cap_pdl,
            )
        )

    # Ajuste de exibição / piso zero — legacy rows (`explain()`'s "lump" or
    # "residual_gap" branches) fold whatever can't be split (confiança + teto/piso
    # combined, or a genuine zero-floor event) into ONE of these two kinds instead
    # of a per-factor chip. Without this branch the chips above stop short of
    # `cr_delta` for essentially every pre-v1.4 match (confiança alone is nearly
    # always nonzero), which is exactly the "doesn't add up" bug this feature
    # exists to fix — so this compact card mirrors the drill-down ledger's own
    # "display_adjust"/"zero_floor" entry rather than silently dropping it.
    #
    # When the caller supplied a lobby context (state/lobby_mean_mu) that let
    # explain() land on a SPECIFIC bound even though it couldn't split the exact
    # PDL share (see explain()'s "it landed exactly on a bound" lump branch),
    # exp.cap.bound still names which rule that was — label the chip with that
    # mechanism instead of the content-free "Ajuste de exibição" (the whole
    # complaint this refinement addresses: a legacy row dominated by, say, the
    # gain floor showed a chip that told the player nothing about why).
    adjust_pdl = by_kind.get("display_adjust", 0.0)
    if abs(adjust_pdl) > 1e-6:
        if exp.cap.bound in _CAP_CHIP:
            _, cap_label, cap_icon = _CAP_CHIP[exp.cap.bound]
            label, icon = f"{cap_label} (parcial)", cap_icon
        else:
            label, icon = "Ajuste de exibição", "help"
        out.append(
            Modifier(
                kind="ajuste",
                label=label,
                value=0.0,
                icon=icon,
                pdl_impact=adjust_pdl,
            )
        )
    zero_floor_pdl = by_kind.get("zero_floor", 0.0)
    if abs(zero_floor_pdl) > 1e-6:
        out.append(
            Modifier(
                kind="piso_zero",
                label="PDL mínimo (0)",
                value=0.0,
                icon="block",
                pdl_impact=zero_floor_pdl,
            )
        )

    return out


def _applied_to_dict(a: "AppliedModifiers") -> dict[str, Any]:
    """Minimal JSONB-shaped dict from a bare (fresh, un-persisted)
    ``AppliedModifiers`` — used only by :func:`map_modifiers`'s dataclass input
    path. Deliberately omits ``softCapFactor``/``dispersionClamped``: ``explain()``
    never reads them (see its module docstring)."""
    return {
        "plBaseDeltaMu": a.pl_base_delta_mu,
        "placementWeight": a.placement_weight,
        "placementAmp": a.placement_amp,
        "streakMult": a.streak_mult,
        "boostingFactor": a.boosting_factor,
        "partyFactor": a.party_factor,
        "finalDeltaMu": a.final_delta_mu,
    }


# ---------------------------------------------------------------------------
# Placeholder gradients (ToS — no real avatar/champion art)
# ---------------------------------------------------------------------------


def _hsl_hex(hue: float, sat: float, light: float) -> str:
    """HSL (hue 0..360, sat/light 0..1) -> ``#RRGGBB``."""
    r, g, b = colorsys.hls_to_rgb((hue % 360) / 360.0, light, sat)
    return f"#{round(r * 255):02X}{round(g * 255):02X}{round(b * 255):02X}"


def avatar_for(seed: str, offset: int = 0) -> AvatarColors:
    """Deterministic placeholder gradient — a HARMONIOUS analogous HSL pair (deep
    base hue + brighter neighbour) so it reads as one colour family rather than a
    clashing pair of complementaries (used only when no real icon is available)."""
    h = int(hashlib.sha256(f"{seed}:{offset}".encode()).hexdigest(), 16)
    hue = h % 360
    hue2 = (hue + 22 + (h >> 9) % 26) % 360
    return AvatarColors(c1=_hsl_hex(hue, 0.55, 0.34), c2=_hsl_hex(hue2, 0.78, 0.62))


# ---------------------------------------------------------------------------
# Data Dragon (ddragon) — real champion names + champion/summoner icon URLs.
#
# Riot's OFFICIAL, ToS-compliant static CDN. The champion map is warmed once at
# app startup (``app._lifespan``) into the singleton's in-process cache, so these
# resolve synchronously with no network/Redis on the hot path. All are None-safe:
# a cold cache or unknown id degrades to the gradient ``avatar`` fallback (URL
# ``None``) and the numeric id as the name — handlers never crash.
# ---------------------------------------------------------------------------


def champion_name(champion_id: int) -> str:
    """Localized (pt_BR) champion display name from the warmed ddragon map.

    Falls back to the numeric id as a string when the map is cold or the id is
    unknown, so the UI always has a stable, non-empty label.
    """
    from arena.ddragon import get_ddragon

    name = get_ddragon().champion_name_sync(champion_id)
    return name or str(champion_id)


def champion_class(champion_id: int) -> str:
    """PT-BR champion class (Mago/Tanque/Lutador/Suporte/Atirador/Assassino).

    Arena has no fixed roles; this is the ddragon class taxonomy (``tags[0]``)
    used only by the class-chip filter. Empty string when the id is unknown.
    """
    from arena.ddragon import get_ddragon

    return get_ddragon().champion_class_sync(champion_id)


def champion_icon_url(champion_id: int) -> str | None:
    """Real ddragon champion-square icon URL, or ``None`` (→ gradient fallback)."""
    from arena.ddragon import get_ddragon

    return get_ddragon().champion_icon_url_sync(champion_id)


def champion_splash_url(champion_id: int) -> str | None:
    """Real ddragon champion splash-art URL, or ``None`` (→ no cover art)."""
    from arena.ddragon import get_ddragon

    return get_ddragon().champion_splash_url_sync(champion_id)


def profile_icon_url(icon_id: int | None) -> str | None:
    """Real ddragon summoner profile-icon URL, or ``None`` (→ gradient fallback)."""
    from arena.ddragon import get_ddragon

    return get_ddragon().profile_icon_url_sync(icon_id)


def split_riot_id(riot_id: str) -> tuple[str, str]:
    """``"Nome#TAG"`` → ``("Nome", "#TAG")``. Tolerates a missing tag."""
    name, sep, tag = riot_id.partition("#")
    return name, (f"#{tag}" if sep else "#???")


def compose_riot_id(name: str | None, tag: str | None) -> str:
    """Build ``"Nome#TAG"`` from the player's stored name/tag columns."""
    return f"{name or 'Desconhecido'}#{tag or '???'}"


# ---------------------------------------------------------------------------
# DB dependency + season resolution
# ---------------------------------------------------------------------------


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped AsyncSession.

    Re-exported from :mod:`arena.db.session` so routers depend on the router
    package, not the DB module directly (keeps the import surface tidy).
    """
    from arena.db.session import get_session

    async for session in get_session():
        yield session


async def resolve_season_id(session: AsyncSession, season: int) -> str | None:
    """Map the contract's integer ``season`` to a ``seasons.id`` (UUID str).

    The contract numbers seasons 1..N; we resolve the Nth season by chronological
    ``starts_at`` order. Returns ``None`` when no such season exists (the caller
    decides whether that is an empty page or a 404).
    """
    from sqlalchemy import select

    from arena.db import models as m

    rows = await session.execute(select(m.Season.id).order_by(m.Season.starts_at.asc()))
    ids = [str(r[0]) for r in rows.all()]
    if not ids:
        return None
    idx = season - 1
    if 0 <= idx < len(ids):
        return ids[idx]
    # Out-of-range season number → newest season (graceful default).
    return ids[-1]


__all__ = [
    "QUEUE_BY_FORMAT",
    "FORMAT_BY_QUEUE",
    "SUBTEAMS_BY_FORMAT",
    "cr_of",
    "cr_band",
    "tier_from_rank",
    "is_provisional",
    "map_modifiers",
    "avatar_for",
    "champion_name",
    "champion_class",
    "champion_icon_url",
    "champion_splash_url",
    "profile_icon_url",
    "split_riot_id",
    "compose_riot_id",
    "get_db",
    "resolve_season_id",
]
