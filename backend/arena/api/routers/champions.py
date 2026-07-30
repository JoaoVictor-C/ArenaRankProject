"""Contract §4 — ``GET /api/v1/champions`` (REAL global tierlist).

Aggregates the season's ``champion_stats`` into a global per-champion tierlist
(placement-derived: first-place rate, top-half rate, average placement, pick
share) via :meth:`StatsService.champion_tierlist`. Champions are ranked by the
requested ``metric`` and bucketed into S+/S/A/B/C/D by relative position. Names
and avatar colors come from the ddragon map (real champion names). Falls back to
an empty, well-formed tierlist before any champion data exists.

ToS Riot: champion top4/first/avgPlace/pickRate are OK. The build endpoint
surfaces augment/item/teammate stats placement-derived only (top1/top4 +
average placement, from the external global reference aggregate in
``champion_build_ref``); a raw augment/item winrate is never exposed. Arena
has no bans -> ``banRate`` is always 0.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arena.api.routers import _common as c
from arena.db import models as m
from arena.ddragon import get_ddragon
from arena.schemas import (
    BuildEntry,
    BuildTeammate,
    ChampionAugments,
    ChampionBuildResponse,
    ChampionMainsResponse,
    ChampionSynergy,
    ChampionSynergyGroup,
    ChampionSynergyGroupResponse,
    ChampionSynergyResponse,
    ChampionTrendPoint,
    ChampionTrendResponse,
    ChampRow,
    ChampTier,
    ChampTierlistResponse,
    ChampTopPlayer,
    SynergyChampion,
    SynergyTier,
    SynergyTierlistResponse,
    TopBuildResponse,
)
from arena.schemas.champions import BuildTierKey
from arena.schemas.common import Format
from arena.services.build_ref_service import (
    BUILD_MIN_GAMES,
    TOP_MIN_GAMES,
    BuildEntryView,
    get_build_ref_service,
)
from arena.services.stats_service import (
    SYNERGY_MIN_GAMES,
    ChampionBestPlayer,
    ChampionSynergyGroupRow,
    ChampionTierRow,
    ChampionTrendPointView,
    StatsService,
)

ChampTierKey = Literal["S+", "S", "A", "B", "C", "D"]

router = APIRouter(tags=["champions"])

# (key, PT-BR label, color, cumulative position cutoff 0..1). Champions sorted by
# the metric are bucketed by their relative rank so the shape holds for any count.
_TIER_CONFIG: list[tuple[ChampTierKey, str, str, float]] = [
    ("S+", "Soberbo", "#FFD700", 0.08),
    ("S", "Forte", "#C0C0C0", 0.23),
    ("A", "Bom", "#CD7F32", 0.45),
    ("B", "Médio", "#4FC3F7", 0.70),
    ("C", "Fraco", "#81C784", 0.88),
    ("D", "Ruim", "#EF9A9A", 1.0),
]

_VALID_METRICS = {"top4", "first", "avgplace", "pick", "ban"}

# How many comps the synergy tierlist pulls before bucketing into S+..D bands.
_SYNERGY_TIERLIST_LIMIT = 100


async def _current_patch() -> str:
    """Real display patch ("15.14") from the ddragon version ("15.14.1").

    ddragon's ``versions.json`` tracks the live game patch; cache-first, so this
    never blocks the hot path after warm-up. The old hardcoded "14.20" default
    contradicted the "ao vivo" meta line and read as fake data.
    """
    version = await get_ddragon().get_version()
    return ".".join(version.split(".")[:2])


def _sort_key(metric: str) -> Callable[[ChampionTierRow], float]:
    """Rank key for the metric (ascending sort → best first)."""
    if metric == "first":
        return lambda r: -r.first_rate
    if metric == "avgplace":
        return lambda r: r.avg_place  # lower placement is better → ascending
    if metric == "pick":
        return lambda r: -r.pick_rate
    # "top4" (default) and "ban" (Arena has no bans) rank by top-half rate.
    return lambda r: -r.top4_rate


def _tier_for(position: int, total: int) -> tuple[ChampTierKey, str, str]:
    frac = (position + 1) / total if total else 1.0
    for key, label, color, cutoff in _TIER_CONFIG:
        if frac <= cutoff:
            return key, label, color
    key, label, color, _ = _TIER_CONFIG[-1]
    return key, label, color


async def _hydrate_player_names(
    session: AsyncSession, player_ids: Iterable[str]
) -> dict[str, tuple[str, str, int | None]]:
    """Batch ``{player_id: (name, handle, profile_icon_id)}`` for reference mains."""
    ids = list({str(p) for p in player_ids})
    if not ids:
        return {}
    rows = await session.execute(
        select(
            m.Player.id,
            m.Player.summoner_name,
            m.Player.tag_line,
            m.Player.profile_icon_id,
        ).where(m.Player.id.in_(ids))
    )
    out: dict[str, tuple[str, str, int | None]] = {}
    for pid, summoner_name, tag_line, icon_id in rows:
        name, handle = c.split_riot_id(c.compose_riot_id(summoner_name, tag_line))
        out[str(pid)] = (name, handle, icon_id)
    return out


def _top_player_dto(
    bp: ChampionBestPlayer, names: dict[str, tuple[str, str, int | None]]
) -> ChampTopPlayer:
    """Build the UI ``ChampTopPlayer`` from a best-player row + hydrated display info."""
    name, handle, icon_id = names.get(bp.player_id, ("—", "", None))
    return ChampTopPlayer(
        name=name,
        handle=handle,
        avatar=c.avatar_for(name or bp.player_id),
        profile_icon_url=c.profile_icon_url(icon_id),
        games=bp.games,
        winrate=bp.winrate,
        avg_place=bp.avg_place,
    )


@router.get(
    "/champions",
    response_model=ChampTierlistResponse,
    response_model_by_alias=True,
    summary="Tierlist real de campeões (placement-derived; ToS: sem winrate de augment/item)",
)
async def get_champions(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    format: Annotated[Format, Query()] = "3v3",
    metric: Annotated[str, Query(description="top4|first|avgplace|pick|ban")] = "top4",
    region: Annotated[str, Query()] = "br",
    season: Annotated[int, Query(ge=1, description="Número da temporada")] = 3,
) -> ChampTierlistResponse:
    metric = metric if metric in _VALID_METRICS else "top4"

    patch = await _current_patch()
    season_id = await c.resolve_season_id(session, season)
    if season_id is None:
        return ChampTierlistResponse(
            updated_at="", patch=patch, region=region, format=format,
            metric=metric, sample_size=0, tiers=[], table=[],
        )

    stats = StatsService()
    agg = await stats.champion_tierlist(session, season_id=season_id)
    agg.sort(key=_sort_key(metric))

    total = len(agg)
    total_games = sum(a.games for a in agg)

    # Reference main per champion (busiest player) — one query for the whole page,
    # then one batched name/icon hydration. Placement-derived (ToS).
    best = await stats.champion_best_players(
        session, season_id=season_id, champion_ids=[a.champion_id for a in agg], per_champion=1
    )
    best_names = await _hydrate_player_names(
        session, [bp.player_id for bps in best.values() for bp in bps]
    )

    # 7d top-half delta per champion (one batched scan of the daily rollup).
    # Empty/0 before the rollup has history → the UI hides the arrow.
    deltas = await stats.champion_winrate_delta7d(
        session, season_id=season_id, champion_ids=[a.champion_id for a in agg]
    )

    table: list[ChampRow] = []
    tiers_map: dict[ChampTierKey, ChampTier] = {}
    for pos, a in enumerate(agg):
        key, label, color = _tier_for(pos, total)
        name = c.champion_name(a.champion_id) or str(a.champion_id)
        champ_best = best.get(a.champion_id)
        row = ChampRow(
            rank=pos + 1,
            champion_id=a.champion_id,
            champion=c.avatar_for(name),
            champion_icon_url=c.champion_icon_url(a.champion_id),
            name=name,
            # Arena has no lane/role; this is the ddragon champion CLASS
            # (Mago/Tanque/...) for the class-chip filter — empty if unknown.
            role=c.champion_class(a.champion_id),
            games=a.games,
            top4=a.top4_rate,
            first=a.first_rate,
            avg_place=a.avg_place,
            pick_rate=a.pick_rate,
            ban_rate=0.0,  # Arena has no bans
            tier=key,
            winrate_delta=deltas.get(a.champion_id, 0),
            top_player=_top_player_dto(champ_best[0], best_names) if champ_best else None,
        )
        table.append(row)
        tier = tiers_map.get(key)
        if tier is None:
            tier = ChampTier(key=key, label=label, color=color, champions=[])
            tiers_map[key] = tier
        tier.champions.append(row)

    tiers = [tiers_map[cfg[0]] for cfg in _TIER_CONFIG if cfg[0] in tiers_map]

    return ChampTierlistResponse(
        updated_at=datetime.now(UTC).isoformat(),
        patch=patch,
        region=region,
        format=format,
        metric=metric,
        sample_size=total_games,
        tiers=tiers,
        table=table,
    )


def _synergy_champion(champion_id: int) -> SynergyChampion:
    """Display DTO for one champion in a synergy pair (name + icon + gradient)."""
    name = c.champion_name(champion_id) or str(champion_id)
    return SynergyChampion(
        champion_id=champion_id,
        name=name,
        champion_icon_url=c.champion_icon_url(champion_id),
        colors=c.avatar_for(name),
    )


@router.get(
    "/champions/synergy",
    response_model=ChampionSynergyResponse,
    response_model_by_alias=True,
    summary="Sinergia de duplas de campeão (winrate real de subteam; ToS: placement-derived)",
)
async def get_champion_synergy(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    format: Annotated[Format, Query()] = "3v3",
    season: Annotated[int, Query(ge=1)] = 3,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
) -> ChampionSynergyResponse:
    season_id = await c.resolve_season_id(session, season)
    if season_id is None:
        return ChampionSynergyResponse(
            updated_at="",
            season=season,
            format=format,
            sample_size=0,
            min_games=SYNERGY_MIN_GAMES,
            pairs=[],
        )
    rows = await StatsService().champion_synergies(session, season_id=season_id, limit=limit)
    pairs = [
        ChampionSynergy(
            champion_a=_synergy_champion(r.champion_a),
            champion_b=_synergy_champion(r.champion_b),
            games=r.games,
            win_rate=r.win_rate,
            first_rate=r.first_rate,
            avg_place=r.avg_place,
        )
        for r in rows
    ]
    return ChampionSynergyResponse(
        updated_at=datetime.now(UTC).isoformat(),
        season=season,
        format=format,
        sample_size=sum(r.games for r in rows),
        min_games=SYNERGY_MIN_GAMES,
        pairs=pairs,
    )


def _synergy_group(row: ChampionSynergyGroupRow) -> ChampionSynergyGroup:
    """Display DTO for one synergy combo (duo/trio) — each member hydrated."""
    return ChampionSynergyGroup(
        champions=[_synergy_champion(cid) for cid in row.champions],
        games=row.games,
        win_rate=row.win_rate,
        first_rate=row.first_rate,
        avg_place=row.avg_place,
    )


@router.get(
    "/champions/synergy/groups",
    response_model=ChampionSynergyGroupResponse,
    response_model_by_alias=True,
    summary=(
        "Sinergia de subteams (duplas ou trios) por winrate — rail do /winrate; "
        "ToS: placement-derived"
    ),
)
async def get_champion_synergy_groups(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    format: Annotated[Format, Query()] = "3v3",
    season: Annotated[int, Query(ge=1)] = 3,
    size: Annotated[int, Query(ge=2, le=3, description="Tamanho do subteam: 2 dupla, 3 trio")] = 3,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
) -> ChampionSynergyGroupResponse:
    season_id = await c.resolve_season_id(session, season)
    if season_id is None:
        return ChampionSynergyGroupResponse(
            updated_at="",
            season=season,
            format=format,
            size=size,
            sample_size=0,
            min_games=SYNERGY_MIN_GAMES,
            groups=[],
        )
    rows = await StatsService().champion_synergies_n(
        session, season_id=season_id, size=size, limit=limit
    )
    return ChampionSynergyGroupResponse(
        updated_at=datetime.now(UTC).isoformat(),
        season=season,
        format=format,
        size=size,
        sample_size=sum(r.games for r in rows),
        min_games=SYNERGY_MIN_GAMES,
        groups=[_synergy_group(r) for r in rows],
    )


@router.get(
    "/champions/synergy/tierlist",
    response_model=SynergyTierlistResponse,
    response_model_by_alias=True,
    summary=(
        "Tierlist de sinergias (duplas/trios) em bandas S+..D — página /sinergias; "
        "ToS: placement-derived"
    ),
)
async def get_champion_synergy_tierlist(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    format: Annotated[Format, Query()] = "3v3",
    season: Annotated[int, Query(ge=1)] = 3,
    size: Annotated[int, Query(ge=2, le=3, description="Tamanho do subteam: 2 dupla, 3 trio")] = 3,
) -> SynergyTierlistResponse:
    season_id = await c.resolve_season_id(session, season)
    if season_id is None:
        return SynergyTierlistResponse(
            updated_at="",
            season=season,
            format=format,
            size=size,
            sample_size=0,
            min_games=SYNERGY_MIN_GAMES,
            tiers=[],
            table=[],
        )
    rows = await StatsService().champion_synergies_n(
        session, season_id=season_id, size=size, limit=_SYNERGY_TIERLIST_LIMIT
    )
    groups = [_synergy_group(r) for r in rows]
    total = len(groups)
    tiers_map: dict[ChampTierKey, SynergyTier] = {}
    for pos, grp in enumerate(groups):
        key, label, color = _tier_for(pos, total)
        tier = tiers_map.get(key)
        if tier is None:
            tier = SynergyTier(key=key, label=label, color=color, comps=[])
            tiers_map[key] = tier
        tier.comps.append(grp)
    tiers = [tiers_map[cfg[0]] for cfg in _TIER_CONFIG if cfg[0] in tiers_map]
    return SynergyTierlistResponse(
        updated_at=datetime.now(UTC).isoformat(),
        season=season,
        format=format,
        size=size,
        sample_size=sum(r.games for r in rows),
        min_games=SYNERGY_MIN_GAMES,
        tiers=tiers,
        table=groups,
    )


def _build_entry_dto(e: BuildEntryView) -> BuildEntry:
    return BuildEntry(
        id=e.id,
        name=e.name,
        icon_url=e.icon_url,
        tier=cast(BuildTierKey, e.tier),
        games=e.games,
        avg_place=e.avg_place,
        top1=e.top1,
        top4=e.top4,
        pick_rate=e.pick_rate,
    )


def _build_teammate_dto(e: BuildEntryView) -> BuildTeammate:
    """Teammate row: the view's ``id`` is a championId; resolve display here."""
    name = c.champion_name(e.id) or str(e.id)
    return BuildTeammate(
        champion_id=e.id,
        name=name,
        champion_icon_url=c.champion_icon_url(e.id),
        colors=c.avatar_for(name),
        tier=cast(BuildTierKey, e.tier),
        games=e.games,
        avg_place=e.avg_place,
        top1=e.top1,
        top4=e.top4,
        pick_rate=e.pick_rate,
    )


@router.get(
    "/champions/build/top",
    response_model=TopBuildResponse,
    response_model_by_alias=True,
    summary=(
        "Top global de augments e itens do patch (agregado cross-campeão; ToS: "
        "placement-derived, sem winrate de augment/item)"
    ),
)
async def get_top_build(
    session: Annotated[AsyncSession, Depends(c.get_db)],
) -> TopBuildResponse:
    view = await get_build_ref_service().top_build(session)
    return TopBuildResponse(
        updated_at=view.updated_at,
        patch=view.patch,
        games=view.games,
        champions=view.champions,
        min_games=TOP_MIN_GAMES,
        augments=[_build_entry_dto(e) for e in view.augments],
        items=[_build_entry_dto(e) for e in view.items],
    )


@router.get(
    "/champions/{champion_id}/build",
    response_model=ChampionBuildResponse,
    response_model_by_alias=True,
    summary=(
        "Build de referência categorizada — augments por raridade, itens/botas e "
        "parceiros (agregado global do patch; ToS: placement-derived, sem winrate "
        "de augment/item)"
    ),
)
async def get_champion_build(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    champion_id: int,
) -> ChampionBuildResponse:
    name = c.champion_name(champion_id) or str(champion_id)
    icon = c.champion_icon_url(champion_id)
    view = await get_build_ref_service().champion_build(session, champion_id=champion_id)
    if view is None:
        # No snapshot for this champion yet — honest empty (games=0), never fake.
        return ChampionBuildResponse(
            champion_id=champion_id,
            name=name,
            champion_icon_url=icon,
            patch="",
            updated_at="",
            games=0,
            avg_place=0.0,
            tier=None,
            top1=0,
            top4=0,
            min_games=BUILD_MIN_GAMES,
        )
    return ChampionBuildResponse(
        champion_id=champion_id,
        name=name,
        champion_icon_url=icon,
        patch=view.patch,
        updated_at=view.updated_at,
        games=view.games,
        avg_place=view.avg_place,
        tier=cast(BuildTierKey, view.tier) if view.tier is not None else None,
        top1=view.top1,
        top4=view.top4,
        min_games=BUILD_MIN_GAMES,
        augments=ChampionAugments(
            prismatic=[_build_entry_dto(e) for e in view.augments_prismatic],
            gold=[_build_entry_dto(e) for e in view.augments_gold],
            silver=[_build_entry_dto(e) for e in view.augments_silver],
        ),
        items=[_build_entry_dto(e) for e in view.items],
        boots=[_build_entry_dto(e) for e in view.boots],
        teammates=[_build_teammate_dto(e) for e in view.teammates],
    )


@router.get(
    "/champions/{champion_id}/mains",
    response_model=ChampionMainsResponse,
    response_model_by_alias=True,
    summary="Jogadores de referência de um campeão (mains, por partidas; ToS: placement-derived)",
)
async def get_champion_mains(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    champion_id: int,
    season: Annotated[int, Query(ge=1)] = 3,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> ChampionMainsResponse:
    name = c.champion_name(champion_id) or str(champion_id)
    icon = c.champion_icon_url(champion_id)
    season_id = await c.resolve_season_id(session, season)
    if season_id is None:
        return ChampionMainsResponse(
            champion_id=champion_id, name=name, champion_icon_url=icon, players=[]
        )
    best = await StatsService().champion_best_players(
        session, season_id=season_id, champion_ids=[champion_id], per_champion=limit
    )
    rows = best.get(champion_id, [])
    names = await _hydrate_player_names(session, [bp.player_id for bp in rows])
    return ChampionMainsResponse(
        champion_id=champion_id,
        name=name,
        champion_icon_url=icon,
        players=[_top_player_dto(bp, names) for bp in rows],
    )


def _trend_point_dto(v: ChampionTrendPointView) -> ChampionTrendPoint:
    return ChampionTrendPoint(
        date=v.date, top4=v.top4, first=v.first, pick_rate=v.pick_rate, games=v.games
    )


@router.get(
    "/champions/{champion_id}/trend",
    response_model=ChampionTrendResponse,
    response_model_by_alias=True,
    summary=(
        "Série diária de winrate/pick/top4 do campeão (rollup champion_daily_stats; "
        "ToS: placement-derived)"
    ),
)
async def get_champion_trend(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    champion_id: int,
    season: Annotated[int, Query(ge=1)] = 3,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> ChampionTrendResponse:
    name = c.champion_name(champion_id) or str(champion_id)
    icon = c.champion_icon_url(champion_id)
    season_id = await c.resolve_season_id(session, season)
    if season_id is None:
        return ChampionTrendResponse(
            champion_id=champion_id, name=name, champion_icon_url=icon, days=days, series=[]
        )
    points = await StatsService().champion_trend(
        session, season_id=season_id, champion_id=champion_id, days=days
    )
    return ChampionTrendResponse(
        champion_id=champion_id,
        name=name,
        champion_icon_url=icon,
        days=days,
        series=[_trend_point_dto(p) for p in points],
    )
