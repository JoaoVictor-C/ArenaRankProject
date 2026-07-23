"""Shared router helpers — the projection layer between our gamified rating
engine / SQLAlchemy models and the ``api_contract_v1`` DTOs.

Everything user-facing here is **CR/Pontos** (never mu/sigma) and PT-BR. The
central jobs of this module:

* ``cr_of`` — display CR via the engine ``to_cr(mu, sigma)`` (gamified, not
  ``round(mu*200)``); ``cr_band`` — a CR-space uncertainty band for the profile
  chart, derived from sigma but never exposing sigma.
* ``tier_from_rank`` — display tier (top1/top10/.../none) from the global rank.
* ``is_provisional`` — provisional flag from the placement-match window.
* ``map_modifiers`` — ``AppliedModifiers`` (engine snapshot, persisted as JSONB)
  → ``[{kind,label,value,icon}]`` in PT-BR (colocação/sequência/proteção/penalidade).
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


def map_modifiers(applied: "AppliedModifiers | dict[str, Any]") -> list[Modifier]:
    """Map an ``AppliedModifiers`` snapshot to the contract's modifier breakdown.

    Accepts either the dataclass (fresh from the engine) or its JSONB dict form
    (as persisted on ``match_participants.modifiers``). Only renders the modifiers
    that actually fired (≠ neutral), in a stable, UI-meaningful order:
    colocação → sequência → proteção (soft-cap) → penalidade (boosting/dispersão).
    Never carries mu/sigma.
    """
    a = _as_applied(applied)
    out: list[Modifier] = []

    # Colocação — placement weight × provisional amplification combined.
    placement_mult = a.placement_weight * a.placement_amp
    if abs(placement_mult - 1.0) > 1e-9:
        amp_note = " (provisória)" if a.placement_amp != 1.0 else ""
        out.append(
            Modifier(
                kind="colocacao",
                label=f"Colocação{amp_note}",
                value=_pct(placement_mult),
                icon="leaderboard",
            )
        )

    # Sequência — win-streak bonus / loss-streak dampener.
    if abs(a.streak_mult - 1.0) > 1e-9:
        streak_up = a.streak_mult > 1.0
        out.append(
            Modifier(
                kind="sequencia",
                label="Sequência de vitórias" if streak_up else "Amortecedor de derrotas",
                value=_pct(a.streak_mult),
                icon="local_fire_department" if streak_up else "shield_moon",
            )
        )

    # Proteção — soft-cap diminishing returns near the top (always ≤ 1.0).
    if a.soft_cap_factor < 1.0 - 1e-9:
        out.append(
            Modifier(
                kind="protecao",
                label="Proteção de topo",
                value=_pct(a.soft_cap_factor),
                icon="vertical_align_top",
            )
        )

    # Penalidade — boosting penalty (integrity) and/or dispersion clamp.
    if a.boosting_factor < 1.0 - 1e-9:
        out.append(
            Modifier(
                kind="penalidade",
                label="Penalidade de boosting",
                value=_pct(a.boosting_factor),
                icon="gpp_bad",
            )
        )
    # Grupo — premade dampener (solo wins are worth more); always ≤ 1.0.
    if a.party_factor < 1.0 - 1e-9:
        out.append(
            Modifier(
                kind="grupo",
                label="Penalidade de grupo",
                value=_pct(a.party_factor),
                icon="group",
            )
        )
    if a.dispersion_clamped:
        out.append(
            Modifier(
                kind="penalidade",
                label="Variação limitada",
                value=0.0,
                icon="speed",
            )
        )

    return out


def _as_applied(applied: "AppliedModifiers | dict[str, Any]") -> "AppliedModifiers":
    from arena.rating import AppliedModifiers

    if isinstance(applied, AppliedModifiers):
        return applied

    # JSONB dict — tolerate camelCase or snake_case keys, default neutral.
    def g(*keys: str, default: float = 1.0) -> float:
        for k in keys:
            if k in applied:
                return float(applied[k])
        return default

    return AppliedModifiers(
        pl_base_delta_mu=g("pl_base_delta_mu", "plBaseDeltaMu", default=0.0),
        placement_weight=g("placement_weight", "placementWeight"),
        placement_amp=g("placement_amp", "placementAmp"),
        streak_mult=g("streak_mult", "streakMult"),
        soft_cap_factor=g("soft_cap_factor", "softCapFactor"),
        boosting_factor=g("boosting_factor", "boostingFactor"),
        party_factor=g("party_factor", "partyFactor"),
        dispersion_clamped=bool(
            applied.get("dispersion_clamped", applied.get("dispersionClamped", False))
        ),
        final_delta_mu=g("final_delta_mu", "finalDeltaMu", default=0.0),
    )


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


def champion_icon_url(champion_id: int) -> str | None:
    """Real ddragon champion-square icon URL, or ``None`` (→ gradient fallback)."""
    from arena.ddragon import get_ddragon

    return get_ddragon().champion_icon_url_sync(champion_id)


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
    "champion_icon_url",
    "profile_icon_url",
    "split_riot_id",
    "compose_riot_id",
    "get_db",
    "resolve_season_id",
]
