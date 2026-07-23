"""Contract §2 — ``GET /api/v1/player/{riotId}``.

Real profile from ``players`` + ``player_seasons`` + ``match_participants``,
projected to CR/Pontos (never mu/sigma). ``rank`` and ``tier`` come from the
leaderboard scope; ``provisional`` from the placement window; per-match
``modifiers`` from the persisted ``AppliedModifiers`` snapshot mapped to PT-BR.
Subsystems not yet modeled (h2h labels, season archive) are representative
samples per the contract. ``404 {detail}`` (PT-BR) when the riotId is unknown.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from redis.asyncio import Redis
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from arena.api.deps import get_redis
from arena.api.routers import _common as c
from arena.schemas import (
    ChampFacet,
    ChampStat,
    CrHistoryPoint,
    FormDot,
    H2HPlayerRef,
    H2HRow,
    MatchesSummary,
    PlayerMatch,
    PlayerMatchesResponse,
    PlayerMatchRich,
    PlayerProfile,
    SeasonArchive,
)

router = APIRouter(tags=["player"])


async def _resolve_player(session: AsyncSession, riot_id: str) -> Any:
    """Resolve ``Nome#TAG`` → ``Player`` row (case-insensitive no nome) ou 404."""
    from arena.db import models as m

    name_part, tag_part = c.split_riot_id(riot_id)
    tag_value = tag_part.lstrip("#")
    player = (
        await session.execute(
            select(m.Player).where(
                m.Player.summoner_name.ilike(name_part),
                m.Player.tag_line == tag_value,
            )
        )
    ).scalar_one_or_none()
    if player is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Jogador '{riot_id}' não encontrado.",
        )
    return player


# NOTE: registrado ANTES de ``/player/{riot_id:path}`` — o conversor ``:path`` é
# guloso e engoliria ``/player/X/matches`` se o catch-all viesse primeiro.
@router.get(
    "/player/{riot_id:path}/matches",
    response_model=PlayerMatchesResponse,
    response_model_by_alias=True,
    summary="Histórico paginado de partidas (filtros + agregados do conjunto)",
)
async def get_player_matches(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    riot_id: Annotated[str, Path(description='Riot ID "Nome#TAG" (URL-encoded)')],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    result: Annotated[
        Literal["first", "top", "bottom"] | None,
        Query(description="Filtro: first=1º lugar · top=metade de cima · bottom=metade de baixo"),
    ] = None,
    champion: Annotated[int | None, Query(ge=1, description="championId para filtrar")] = None,
) -> PlayerMatchesResponse:
    """Contract §2-bis — histórico dedicado com paginação real.

    ``summary`` agrega o conjunto FILTRADO inteiro (não só a página), então os
    números do rail de analytics não mudam ao paginar. O corte de metade-de-cima
    é mode-aware (DUOS/8 → ≤4, TRIOS/6 → ≤3) — a MESMA regra de
    ``StatsService.win_loss_by_player``, para o histórico bater com o perfil.
    """
    from arena.db import models as m

    player = await _resolve_player(session, riot_id)
    pid = str(player.id)
    mp = m.MatchParticipant.__table__
    mt = m.Match.__table__

    # Corte top-metade por modo da partida (DUOS/8 equipes → ≤4; TRIOS/6 → ≤3).
    win_threshold = case((mt.c.mode == m.RatingMode.DUOS, 4), else_=3)

    conds: list[Any] = [mp.c.player_id == player.id]
    if champion is not None:
        conds.append(mp.c.champion_id == champion)
    if result == "first":
        conds.append(mp.c.placement == 1)
    elif result == "top":
        conds.append(mp.c.placement <= win_threshold)
    elif result == "bottom":
        conds.append(mp.c.placement > win_threshold)

    joined = mp.join(mt, mp.c.match_id == mt.c.id)

    # 1) Agregados do conjunto filtrado inteiro — UMA query (contagem, taxas,
    #    média, soma de ΔCR e distribuição de colocação 1..8).
    place_cols = [
        func.coalesce(func.sum(case((mp.c.placement == k, 1), else_=0)), 0).label(f"p{k}")
        for k in range(1, 9)
    ]
    agg = (
        await session.execute(
            select(
                func.count().label("games"),
                func.coalesce(func.sum(case((mp.c.placement == 1, 1), else_=0)), 0).label(
                    "firsts"
                ),
                func.coalesce(
                    func.sum(case((mp.c.placement <= win_threshold, 1), else_=0)), 0
                ).label("tops"),
                func.coalesce(func.avg(mp.c.placement), 0.0).label("avg_place"),
                func.coalesce(func.sum(mp.c.cr_delta), 0.0).label("cr_sum"),
                *place_cols,
            )
            .select_from(joined)
            .where(*conds)
        )
    ).one()
    games = int(agg.games or 0)

    summary = MatchesSummary(
        games=games,
        first_rate=round(100 * int(agg.firsts) / games) if games else 0,
        top4=round(100 * int(agg.tops) / games) if games else 0,
        avg_place=round(float(agg.avg_place or 0.0), 2) if games else 0.0,
        cr_sum=round(float(agg.cr_sum or 0.0)),
        placements=[int(getattr(agg, f"p{k}") or 0) for k in range(1, 9)],
    )

    # 2) Faceta de campeões sobre o histórico COMPLETO (estável sob filtro —
    #    o dropdown não some quando um filtro zera um campeão).
    facet_rows = (
        await session.execute(
            select(mp.c.champion_id, func.count().label("games"))
            .where(mp.c.player_id == player.id)
            .group_by(mp.c.champion_id)
            .order_by(func.count().desc())
            .limit(30)
        )
    ).all()
    champions_facet = [
        ChampFacet(
            champion_id=int(row.champion_id),
            name=c.champion_name(row.champion_id),
            champion=c.avatar_for(f"{pid}:{row.champion_id}"),
            champion_icon_url=c.champion_icon_url(row.champion_id),
            games=int(row.games),
        )
        for row in facet_rows
    ]

    # 3) Página — cronológica DESC (Trinity (player_id, played_at DESC) idx).
    rows = (
        await session.execute(
            select(
                mp.c.match_id,
                mp.c.played_at,
                mp.c.champion_id,
                mp.c.placement,
                mp.c.cr_before,
                mp.c.cr_after,
                mp.c.cr_delta,
                mp.c.is_premade,
                mp.c.modifiers,
                mt.c.queue_id,
                mt.c.mode,
                mt.c.duration_seconds,
            )
            .select_from(joined)
            .where(*conds)
            .order_by(mp.c.played_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()

    matches: list[PlayerMatchRich] = []
    for row in rows:
        fmt = c.FORMAT_BY_QUEUE.get(row.queue_id) or (
            "2v2" if row.mode == m.RatingMode.DUOS else "3v3"
        )
        matches.append(
            PlayerMatchRich(
                match_id=str(row.match_id),
                ts=row.played_at.isoformat(),
                champion=c.avatar_for(f"{pid}:{row.champion_id}"),
                champion_name=c.champion_name(row.champion_id),
                champion_icon_url=c.champion_icon_url(row.champion_id),
                place=int(row.placement),
                cr_delta=round(row.cr_delta),
                modifiers=c.map_modifiers(row.modifiers or {}),
                cr_before=round(row.cr_before),
                cr_after=round(row.cr_after),
                format=fmt,
                team_count=c.SUBTEAMS_BY_FORMAT.get(fmt, 8),
                duration_sec=int(row.duration_seconds or 0),
                premade=bool(row.is_premade),
            )
        )

    return PlayerMatchesResponse(
        total=games,
        offset=offset,
        limit=limit,
        summary=summary,
        champions_facet=champions_facet,
        matches=matches,
    )


@router.get(
    "/player/{riot_id:path}",
    response_model=PlayerProfile,
    response_model_by_alias=True,
    summary="Perfil do jogador (CR/Pontos, histórico, campeões)",
)
async def get_player(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    redis: Annotated[Redis | None, Depends(get_redis)],
    riot_id: Annotated[str, Path(description='Riot ID "Nome#TAG" (URL-encoded)')],
) -> PlayerProfile:
    from arena.db import models as m
    from arena.services import LeaderboardService, StatsService

    name_part, tag_part = c.split_riot_id(riot_id)
    tag_value = tag_part.lstrip("#")
    player = await _resolve_player(session, riot_id)

    # Most recent season state for this player.
    ps = (
        await session.execute(
            select(m.PlayerSeason)
            .join(m.Season, m.Season.id == m.PlayerSeason.season_id)
            .where(m.PlayerSeason.player_id == player.id)
            .order_by(m.Season.starts_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if ps is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Jogador '{riot_id}' não possui rating nesta temporada.",
        )

    pid = str(player.id)
    season_id = str(ps.season_id)
    cr = c.cr_of(ps.mu, ps.sigma)

    # ZREVRANK no ZSET quando quente; a dependency degrada p/ None sem Redis.
    lb = LeaderboardService(redis=redis)
    rank = await lb.get_player_rank(session, season_id=season_id, fmt="3v3", player_id=pid) or 0

    stats = StatsService()
    champ_views = await stats.champion_stats(session, player_id=pid, season_id=season_id, limit=12)

    # Recent participations (chronological — Trinity (player_id, played_at DESC) idx).
    parts = (
        (
            await session.execute(
                select(m.MatchParticipant)
                .where(m.MatchParticipant.player_id == player.id)
                .order_by(m.MatchParticipant.played_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )

    form = [FormDot(place=p.placement) for p in parts[:6]]
    # Real champion names + icon URLs from ddragon (warmed map; sync-fast). The
    # gradient ``champion`` avatar stays as a fallback when an icon is unresolved.
    matches = [
        PlayerMatch(
            match_id=str(p.match_id),
            ts=p.played_at.isoformat(),
            champion=c.avatar_for(f"{pid}:{p.champion_id}"),
            champion_name=c.champion_name(p.champion_id),
            champion_icon_url=c.champion_icon_url(p.champion_id),
            place=p.placement,
            cr_delta=round(p.cr_delta),
            modifiers=c.map_modifiers(p.modifiers or {}),
        )
        for p in parts
    ]

    champions = [
        ChampStat(
            champion=c.avatar_for(f"{pid}:{v.champion_id}"),
            name=c.champion_name(v.champion_id),
            champion_icon_url=c.champion_icon_url(v.champion_id),
            games=v.games,
            first_rate=v.first_rate,
            top4=v.top_half_rate,
            avg_place=v.avg_place,
            cr_impact=v.cr_impact,
            spark=v.spark,
        )
        for v in champ_views
    ]

    # Real season-wide W/L (mode-aware, placement-derived) in one grouped query —
    # the SAME helper the leaderboard uses, so the profile's top-4 is consistent.
    # ``wl.top4`` is already the season % (round(100 * top4_count / games), <=100);
    # do NOT divide again. The raw count (``wl.top4_count``) is always <= games, so
    # "N de M partidas" is sane (the old bug divided the % by games -> >100%).
    wl_map = await stats.win_loss_by_player(session, season_id=season_id, player_ids=[pid])
    wl = wl_map.get(pid)
    if wl is not None:
        wins, losses = wl.wins, wl.losses
        winrate = wl.winrate
        top4 = wl.top4
    else:
        wins = losses = winrate = top4 = 0
    avg_place = round(sum(p.placement for p in parts) / len(parts), 2) if parts else 0.0
    cr_history = _cr_history(parts, cr, ps.mu, ps.sigma)

    # delta7d (CR change over ~7d from cr_snapshots) + relevance-ordered tags.
    # All batched helpers, called with a single-id list (consistent with the
    # leaderboard path, no N+1 even though it's one player).
    delta7d = (await stats.delta7d_by_player(session, season_id=season_id, player_ids=[pid])).get(
        pid, 0
    )
    otp = (await stats.otp_by_player(session, season_id=season_id, player_ids=[pid])).get(pid)
    provisional = c.is_provisional(ps.placement_matches_remaining)
    champ_rank = None
    if otp is not None:
        champ_rank = (
            await stats.champion_placement_rank_by_player(
                session, season_id=season_id, mains={pid: otp.champion_id}
            )
        ).get(pid)
    tags = stats.build_player_tags(
        delta7d=delta7d,
        otp=otp,
        otp_champion_name=c.champion_name(otp.champion_id) if otp else None,
        otp_icon_url=c.champion_icon_url(otp.champion_id) if otp else None,
        champ_rank=champ_rank,
        champ_rank_name=c.champion_name(champ_rank.champion_id) if champ_rank else None,
        champ_rank_icon_url=c.champion_icon_url(champ_rank.champion_id) if champ_rank else None,
    )

    return PlayerProfile(
        riot_id=c.compose_riot_id(player.summoner_name, player.tag_line),
        name=player.summoner_name or name_part,
        handle=f"#{player.tag_line or tag_value}",
        region=player.region or "BR",
        avatar=c.avatar_for(pid),
        profile_icon_url=c.profile_icon_url(player.profile_icon_id),
        cr=cr,
        rank=rank,
        tier=c.tier_from_rank(rank),
        provisional=provisional,
        delta7d=delta7d,
        wins=wins,
        losses=losses,
        winrate=winrate,
        top4=top4,
        avg_place=avg_place,
        form=form,
        cr_history=cr_history,
        tags=tags,
        matches=matches,
        champions=champions,
        h2h=_h2h_sample(pid),
        seasons=_seasons_sample(cr),
    )


def _cr_history(parts: Sequence[Any], cr: int, mu: float, sigma: float) -> list[CrHistoryPoint]:
    """CR trajectory from recent participations (most-recent last), with a
    CR-space uncertainty band. Sigma is consumed for the band but never emitted."""
    lo_off, hi_off = c.cr_band(mu, sigma)
    spread = max(hi_off - lo_off, 0)
    chrono = list(reversed(parts))[-10:]
    points: list[CrHistoryPoint] = []
    for p in chrono:
        point_cr = round(p.cr_after)
        points.append(
            CrHistoryPoint(
                ts=p.played_at.isoformat(),
                cr=point_cr,
                lo=point_cr - spread,
                hi=point_cr + spread,
            )
        )
    if not points:
        points.append(CrHistoryPoint(ts="", cr=cr, lo=cr - spread, hi=cr + spread))
    return points


def _h2h_sample(pid: str) -> list[H2HRow]:
    # TODO: back by real table (head-to-head labels). Numbers derive from real
    # shared-match aggregates via StatsService.head_to_head when peers are known.
    return [
        H2HRow(
            player=H2HPlayerRef(name="Rival", handle="#BR1", avatar=c.avatar_for(pid, 301)),
            games=0,
            winrate=0,
            synergy="rival",
        ),
        H2HRow(
            player=H2HPlayerRef(name="Parceiro", handle="#BR2", avatar=c.avatar_for(pid, 302)),
            games=0,
            winrate=0,
            synergy="duo",
        ),
    ]


def _seasons_sample(cr: int) -> list[SeasonArchive]:
    # TODO: back by real table (season archive). Tier from each season's rank.
    return [
        SeasonArchive(season=2, peak_cr=cr + 120, final_rank=150, tier="top500"),
        SeasonArchive(season=1, peak_cr=max(cr - 200, 0), final_rank=400, tier="none"),
    ]
