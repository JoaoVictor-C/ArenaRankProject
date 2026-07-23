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
    ChampionSynergyResponse,
    ChampRow,
    ChampTier,
    ChampTierlistResponse,
    ChampTopPlayer,
    SynergyChampion,
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
    ChampionTierRow,
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
            role="",  # Arena has no fixed roles; ddragon role tags are not modeled
            games=a.games,
            top4=a.top4_rate,
            first=a.first_rate,
            avg_place=a.avg_place,
            pick_rate=a.pick_rate,
            ban_rate=0.0,  # Arena has no bans
            tier=key,
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
