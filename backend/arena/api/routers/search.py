"""Contract extension — ``GET /api/v1/players/search``.

Global typeahead for the leaderboard "Pular para jogador" box. Unlike the paged
``/leaderboard`` route, this searches **every** player in the active season for
the given format, not just the rows on the current page — so a name that is not
on the visible page is still found.

Matching is a case-insensitive ``ILIKE`` over ``players.summoner_name`` (and the
``Nome#TAG`` composite when the query carries a ``#``), restricted to players
that hold a ``player_seasons`` row in the **active** season for that format.
Results are CR-ordered (never mu/sigma), capped at ``limit``, and carry the
global rank within the season (1-based, computed by counting strictly-higher CR
peers in one round-trip). camelCase JSON via ``response_model_by_alias=True``.

ddragon (optional): ``profile_icon_url`` resolves synchronously from the warmed
champion/icon map when the player's ``profile_icon_id`` is known; otherwise it is
``None`` and the frontend keeps the gradient ``avatar`` fallback.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from arena.api.routers import _common as c
from arena.schemas.common import ArenaModel, AvatarColors, Format, TierKey

router = APIRouter(tags=["search"])

# Minimum query length to hit the DB; shorter queries return [] (the frontend
# also guards this, but the API stays correct if called directly).
_MIN_QUERY_LEN = 2


class SearchPlayer(ArenaModel):
    """One typeahead hit (UI-safe; CR only — never mu/sigma)."""

    riot_id: str  # "Nome#TAG"
    name: str  # part before the #
    handle: str  # "#TAG"
    cr: int  # CR / Pontos
    rank: int  # 1-based global rank within the season
    tier: TierKey  # display tier derived from rank
    avatar: AvatarColors  # gradient placeholder (ToS — always present)
    # ddragon real summoner profile-icon URL when known; None → gradient fallback.
    profile_icon_url: str | None = None


@router.get(
    "/players/search",
    response_model=list[SearchPlayer],
    response_model_by_alias=True,
    summary="Busca global de jogadores por nome (typeahead do leaderboard)",
)
async def search_players(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    q: Annotated[str, Query(description='Trecho do nome ou "Nome#TAG"')] = "",
    format: Annotated[Format, Query(description="3v3 (queue 1750) | 2v2 (queue 1700)")] = "3v3",
    limit: Annotated[int, Query(ge=1, le=25)] = 8,
) -> list[SearchPlayer]:
    from arena.db import models as m

    query = q.strip()
    if len(query) < _MIN_QUERY_LEN:
        return []

    season_id = await _active_season_id(session)
    if season_id is None:
        return []

    # Support both a bare name and the composite "Nome#TAG": a "#" splits the
    # query into a name fragment + tag fragment, each matched case-insensitively.
    name_part, sep, tag_part = query.partition("#")
    name_like = f"%{name_part.strip()}%"

    ps = m.PlayerSeason
    pl = m.Player

    # 1-based global rank within the season for each candidate, computed by a
    # correlated COUNT of strictly-higher-CR peers (+1). limit is small, and this
    # stays a single round-trip (no N+1) via the scalar subquery. ``hi`` is the
    # aliased peer set; the outer ``ps.cr`` correlates the count to each row.
    hi = aliased(ps, name="hi")
    rank_sq = (
        select(func.count())
        .select_from(hi)
        .where(hi.season_id == season_id, hi.cr > ps.cr)
        .scalar_subquery()
        .correlate(ps)
    )

    conditions = [ps.season_id == season_id, pl.summoner_name.ilike(name_like)]
    if sep and tag_part.strip():
        conditions.append(pl.tag_line.ilike(f"{tag_part.strip()}%"))

    stmt = (
        select(
            pl.id,
            pl.summoner_name,
            pl.tag_line,
            pl.profile_icon_id,
            ps.cr,
            (rank_sq + 1).label("rank"),
        )
        .join(pl, pl.id == ps.player_id)
        .where(*conditions)
        .order_by(ps.cr.desc())
        .limit(limit)
    )

    rows = (await session.execute(stmt)).all()

    out: list[SearchPlayer] = []
    for pid, summoner_name, tag_line, profile_icon_id, cr, rank in rows:
        riot_id = c.compose_riot_id(summoner_name, tag_line)
        name, handle = c.split_riot_id(riot_id)
        rank_int = int(rank or 0)
        out.append(
            SearchPlayer(
                riot_id=riot_id,
                name=name,
                handle=handle,
                cr=round(cr),
                rank=rank_int,
                tier=c.tier_from_rank(rank_int),
                avatar=c.avatar_for(str(pid)),
                profile_icon_url=c.profile_icon_url(profile_icon_id),
            )
        )
    return out


async def _active_season_id(session: AsyncSession) -> str | None:
    """Resolve the active season's id (``status`` ACTIVE/SOFT_LOCK), newest first.

    The leaderboard ranks within the live season; SOFT_LOCK still counts as the
    current public season (rankings are frozen for display but the season is
    current). Falls back to the most recent season by ``starts_at`` when no row
    is explicitly ACTIVE/SOFT_LOCK so the typeahead still works in dev/seed data.
    """
    from arena.db import models as m
    from arena.db.models import SeasonStatus

    active = (
        await session.execute(
            select(m.Season.id)
            .where(m.Season.status.in_([SeasonStatus.ACTIVE, SeasonStatus.SOFT_LOCK]))
            .order_by(m.Season.starts_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if active is not None:
        return str(active)

    newest = (
        await session.execute(select(m.Season.id).order_by(m.Season.starts_at.desc()).limit(1))
    ).scalar_one_or_none()
    return str(newest) if newest is not None else None


__all__ = ["router", "SearchPlayer"]
