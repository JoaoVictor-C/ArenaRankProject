"""Contract §4 — ``GET /api/v1/champions`` (REAL global tierlist).

Aggregates the season's ``champion_stats`` into a global per-champion tierlist
(placement-derived: first-place rate, top-half rate, average placement, pick
share) via :meth:`StatsService.champion_tierlist`. Champions are ranked by the
requested ``metric`` and bucketed into S+/S/A/B/C/D by relative position. Names
and avatar colors come from the ddragon map (real champion names). Falls back to
an empty, well-formed tierlist before any champion data exists.

ToS Riot: champion top4/first/avgPlace/pickRate are OK. The build endpoints
surface augment/item stats placement-derived only (top1/top4 + average
placement, from ``champion_build_stats`` — OUR OWN rollup of captured Riot
picks, not a third-party aggregate; see ``stats_service.py`` and
``build_ref_service.py``'s module docstring for the migration history). A raw
augment/item winrate is never exposed. Arena has no bans -> ``banRate`` is
always 0.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arena.api.routers import _common as c
from arena.core.config import settings
from arena.db import models as m
from arena.ddragon import get_ddragon
from arena.schemas import (
    AugmentCatalogEntry,
    AugmentCatalogResponse,
    BuildEntry,
    ChampionAugments,
    ChampionBuildResponse,
    ChampionBuildVariant,
    ChampionBuildVariantsResponse,
    ChampionMainsResponse,
    ChampionMatchupsResponse,
    ChampionRoundPoint,
    ChampionRoundsResponse,
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
    MatchupEntry,
    SynergyChampion,
    SynergyTier,
    SynergyTierlistResponse,
    TopBuildResponse,
)
from arena.schemas.champions import AugmentRarity, BuildTierKey, MatchupKind
from arena.schemas.common import Format
from arena.services.build_ref_service import (
    BUILD_MIN_GAMES,
    TOP_MIN_GAMES,
    get_build_ref_service,
    is_prismatic_item,
)
from arena.services.stats_service import (
    SYNERGY_MIN_GAMES,
    BuildPickRow,
    ChampionBestPlayer,
    ChampionSynergyGroupRow,
    ChampionTierRow,
    ChampionTrendPointView,
    StatsService,
    _wilson_lower_bound,
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

# Display caps for the /winrate right rail and the per-champion build panel.
_CAP_TOP_AUGMENTS = 12
_CAP_TOP_ITEMS = 14
_CAP_AUGMENTS_PER_RARITY = 8
_CAP_ITEMS = 12
_CAP_BOOTS = 4
_CAP_PRISMATIC_ITEMS = 10

_TIER_RANK: dict[str, int] = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}


async def _current_patch() -> str:
    """Real display patch ("26.15") — Riot's public patch-notes number, not
    the raw ddragon CDN version ("16.15.1").

    ddragon's ``versions.json`` (and CommunityDragon's build metadata) never
    followed Riot's rebrand of patch-notes numbering to the calendar year —
    confirmed live 2026-08-01: ddragon reports "16.15.1" while Riot's own
    patch-notes page (leagueoflegends.com/.../patch-notes/) shows "Notas da
    Atualização 26.15", and ddragon's last several entries (16.14.1, 16.13.1,
    ...) line up 1:1 with 26.14, 26.13, ... — a steady "CDN major + 10 =
    display year" offset (both counters tick once per year, so the gap
    holds). This ONLY affects this display label — asset URLs still need the
    raw CDN version (``get_version()`` elsewhere), never this. If Riot ever
    re-syncs the two schemes, the ``+ 10`` below needs updating/removing.
    """
    version = await get_ddragon().get_version()
    major_str, _, rest = version.partition(".")
    minor_str = rest.split(".")[0]
    try:
        return f"{int(major_str) + 10}.{minor_str}"
    except ValueError:
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


def _build_entry_dto(row: BuildPickRow, display: tuple[Any, ...]) -> BuildEntry:
    """One native pick + its CDragon display info (name/icon/... ) -> DTO.

    ``display`` is positional (name, icon, extra, ...) shared by both the
    augment map (3 elements: name/icon/rarity) and the item map (5: name/icon/
    is_boots/gold/description, wider since the match-detail item hover also
    needs gold cost + description) — only the first two are used here.
    """
    name, icon = display[0], display[1]
    return BuildEntry(
        id=row.pick_id,
        name=name,
        icon_url=icon,
        tier=cast(BuildTierKey, row.tier),
        games=row.games,
        avg_place=row.avg_place,
        top1=row.top1,
        top4=row.top4,
        pick_rate=row.pick_rate,
    )


def _resolve_entries(
    rows: list[BuildPickRow], display: dict[int, tuple[Any, ...]]
) -> list[tuple[BuildEntry, int]]:
    """Drop picks whose id isn't in the CDragon display map (rotated out of the
    current patch / unknown — no name, no row: the same credibility rule
    ``build_ref_service`` already applies elsewhere) and carry the map's
    ``extra`` (rarity for augments, boots-flag for items) alongside the DTO."""
    out: list[tuple[BuildEntry, int]] = []
    for row in rows:
        mapped = display.get(row.pick_id)
        if mapped is None:
            continue
        out.append((_build_entry_dto(row, mapped), mapped[2]))
    return out


def _champion_overall_tier(
    all_champs: list[ChampionTierRow], champion_id: int
) -> BuildTierKey | None:
    """This champion's tier on the SAME ranking the ``/champions`` table shows
    (collapsed to 5 letters — ``BuildTierKey`` has no S+) — reusing that ranking
    instead of inventing a second "how good is this champion" scale."""
    if not all_champs:
        return None
    ordered = sorted(all_champs, key=_sort_key("top4"))
    total = len(ordered)
    for position, row in enumerate(ordered):
        if row.champion_id == champion_id:
            key, _label, _color = _tier_for(position, total)
            return "S" if key == "S+" else key
    return None


@router.get(
    "/champions/build/top",
    response_model=TopBuildResponse,
    response_model_by_alias=True,
    summary=(
        "Top global de augments e itens da temporada (agregado cross-campeão "
        "NATIVO; ToS: placement-derived, sem winrate de augment/item)"
    ),
)
async def get_top_build(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    season: Annotated[int, Query(ge=1)] = 3,
) -> TopBuildResponse:
    patch = await _current_patch()
    season_id = await c.resolve_season_id(session, season)
    if season_id is None:
        return TopBuildResponse(
            updated_at="", patch=patch, games=0, champions=0, min_games=TOP_MIN_GAMES
        )

    stats = StatsService()
    build_ref = get_build_ref_service()
    all_champs, item_map, augment_map, aug_rows, item_rows = await asyncio.gather(
        stats.champion_tierlist(session, season_id=season_id, min_games=0),
        build_ref._item_map(),
        build_ref._augment_map(),
        stats.top_build_picks(session, season_id=season_id, kind="augment", min_games=TOP_MIN_GAMES),
        stats.top_build_picks(session, season_id=season_id, kind="item", min_games=TOP_MIN_GAMES),
    )
    augments = [e for e, _ in _resolve_entries(aug_rows, augment_map)]
    items = [e for e, _ in _resolve_entries(item_rows, item_map)]
    augments.sort(key=lambda e: -e.games)
    items.sort(key=lambda e: -e.games)
    return TopBuildResponse(
        updated_at=datetime.now(UTC).isoformat(),
        patch=patch,
        games=sum(r.games for r in all_champs),
        champions=len(all_champs),
        min_games=TOP_MIN_GAMES,
        augments=augments[:_CAP_TOP_AUGMENTS],
        items=items[:_CAP_TOP_ITEMS],
    )


@router.get(
    "/champions/augments/catalog",
    response_model=AugmentCatalogResponse,
    response_model_by_alias=True,
    summary=(
        "Catálogo completo de augments do Arena no patch atual (identidade — "
        "nome/ícone/raridade/descrição oficiais da Riot via CDragon)"
    ),
)
async def get_augment_catalog() -> AugmentCatalogResponse:
    patch = await _current_patch()
    entries = await get_build_ref_service().augment_catalog()
    return AugmentCatalogResponse(
        updated_at=datetime.now(UTC).isoformat(),
        patch=patch,
        augments=[
            AugmentCatalogEntry(
                id=e.id,
                name=e.name,
                icon_url=e.icon_url,
                rarity=cast(AugmentRarity, e.rarity),
                description=e.description,
            )
            for e in entries
        ],
    )


@router.get(
    "/champions/{champion_id}/build",
    response_model=ChampionBuildResponse,
    response_model_by_alias=True,
    summary=(
        "Build de referência categorizada — augments por raridade e itens/botas "
        "(rollup NATIVO da temporada; ToS: placement-derived, sem winrate de "
        "augment/item)"
    ),
)
async def get_champion_build(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    champion_id: int,
    season: Annotated[int, Query(ge=1)] = 3,
) -> ChampionBuildResponse:
    name = c.champion_name(champion_id) or str(champion_id)
    icon = c.champion_icon_url(champion_id)
    patch = await _current_patch()
    season_id = await c.resolve_season_id(session, season)
    empty = ChampionBuildResponse(
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
    if season_id is None:
        return empty

    stats = StatsService()
    build_ref = get_build_ref_service()
    all_champs, item_map, augment_map, aug_rows, item_rows = await asyncio.gather(
        stats.champion_tierlist(session, season_id=season_id, min_games=0),
        build_ref._item_map(),
        build_ref._augment_map(),
        stats.champion_build_picks(
            session, season_id=season_id, champion_id=champion_id, kind="augment",
            min_games=BUILD_MIN_GAMES,
        ),
        stats.champion_build_picks(
            session, season_id=season_id, champion_id=champion_id, kind="item",
            min_games=BUILD_MIN_GAMES,
        ),
    )
    champ_row = next((r for r in all_champs if r.champion_id == champion_id), None)
    if champ_row is None or champ_row.games <= 0:
        # No eligible games for this champion this season yet — honest empty,
        # never fake (same posture the old external-aggregate path had).
        return empty

    # Best tier first within each bucket — capped AFTER the sort, not during
    # collection, or the cap would keep whatever came first in SQL row order
    # instead of the actual best entries.
    augments_by_rarity: dict[int, list[BuildEntry]] = {2: [], 1: [], 0: []}  # prismatic/gold/silver
    for entry, rarity in _resolve_entries(aug_rows, augment_map):
        bucket = augments_by_rarity.get(rarity)
        if bucket is not None:
            bucket.append(entry)
    for bucket in augments_by_rarity.values():
        bucket.sort(key=lambda e: _TIER_RANK.get(e.tier, len(_TIER_RANK)))
    augments_by_rarity = {
        rarity: bucket[:_CAP_AUGMENTS_PER_RARITY] for rarity, bucket in augments_by_rarity.items()
    }

    items: list[BuildEntry] = []
    boots: list[BuildEntry] = []
    prismatic_items: list[BuildEntry] = []
    for entry, is_boots in _resolve_entries(item_rows, item_map):
        if is_boots:
            boots.append(entry)
        elif is_prismatic_item(entry.id):
            prismatic_items.append(entry)
        elif len(items) < _CAP_ITEMS:
            items.append(entry)
    boots.sort(key=lambda e: _TIER_RANK.get(e.tier, len(_TIER_RANK)))
    boots = boots[:_CAP_BOOTS]
    prismatic_items.sort(key=lambda e: _TIER_RANK.get(e.tier, len(_TIER_RANK)))
    prismatic_items = prismatic_items[:_CAP_PRISMATIC_ITEMS]

    tier = _champion_overall_tier(all_champs, champion_id)
    return ChampionBuildResponse(
        champion_id=champion_id,
        name=name,
        champion_icon_url=icon,
        patch=patch,
        updated_at=datetime.now(UTC).isoformat(),
        games=champ_row.games,
        avg_place=champ_row.avg_place,
        tier=tier,
        top1=champ_row.first_rate,
        top4=champ_row.top4_rate,
        min_games=BUILD_MIN_GAMES,
        augments=ChampionAugments(
            prismatic=augments_by_rarity[2],
            gold=augments_by_rarity[1],
            silver=augments_by_rarity[0],
        ),
        items=items,
        boots=boots,
        prismatic_items=prismatic_items,
        # Teammates (best reference partners) aren't derived from champion_build_stats
        # (that's augment/item picks, not champion pairings) — the old external
        # aggregate had them, native doesn't yet. champion_combo_stats (the
        # synergy rollup) carries the right data to add this later; left empty
        # (honest, not fake) rather than half-built for this pass.
        teammates=[],
    )


def _matchup_entry(champion_id: int, *, games: int, top4: int, avg_place: float, base_win_rate: int) -> MatchupEntry:
    name = c.champion_name(champion_id) or str(champion_id)
    win_rate = round(100 * top4 / games) if games > 0 else 0
    return MatchupEntry(
        champion_id=champion_id,
        name=name,
        champion_icon_url=c.champion_icon_url(champion_id),
        colors=c.avatar_for(name),
        games=games,
        win_rate=win_rate,
        delta=win_rate - base_win_rate,
        avg_place=avg_place,
    )


@router.get(
    "/champions/{champion_id}/matchups",
    response_model=ChampionMatchupsResponse,
    response_model_by_alias=True,
    summary=(
        "Melhores/piores parceiros de dupla (kind=duo) ou oponentes entre "
        "subteams (kind=versus) do campeão (rollups NATIVOS champion_combo_stats/"
        "champion_versus_stats; ToS: placement-derived)"
    ),
)
async def get_champion_matchups(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    champion_id: int,
    kind: Annotated[MatchupKind, Query()] = "duo",
    season: Annotated[int, Query(ge=1)] = 3,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> ChampionMatchupsResponse:
    name = c.champion_name(champion_id) or str(champion_id)
    season_id = await c.resolve_season_id(session, season)
    floor = max(SYNERGY_MIN_GAMES, settings.synergy_combo_min_games)
    empty = ChampionMatchupsResponse(
        champion_id=champion_id,
        name=name,
        season=season,
        format="3v3",
        kind=kind,
        sample_size=0,
        min_games=floor,
        base_win_rate=0,
    )
    if season_id is None:
        return empty

    stats = StatsService()
    partners_call = (
        stats.champion_matchups_versus(session, season_id=season_id, champion_id=champion_id, min_games=floor)
        if kind == "versus"
        else stats.champion_matchups_duo(session, season_id=season_id, champion_id=champion_id, min_games=floor)
    )
    all_champs, partners = await asyncio.gather(
        stats.champion_tierlist(session, season_id=season_id, min_games=0),
        partners_call,
    )
    champ_row = next((r for r in all_champs if r.champion_id == champion_id), None)
    if champ_row is None or champ_row.games <= 0 or not partners:
        return empty
    base_win_rate = champ_row.top4_rate

    scored = [
        (p, round(100 * p.top4 / p.games) if p.games > 0 else 0, round(p.placement_sum / p.games, 2))
        for p in partners
        if p.games > 0
    ]
    best_ranked = sorted(scored, key=lambda x: -_wilson_lower_bound(x[0].top4, x[0].games))
    worst_ranked = sorted(scored, key=lambda x: -_wilson_lower_bound(x[0].games - x[0].top4, x[0].games))

    best = [
        _matchup_entry(p.champion_id, games=p.games, top4=p.top4, avg_place=avg_place, base_win_rate=base_win_rate)
        for p, _win_rate, avg_place in best_ranked[:limit]
    ]
    worst = [
        _matchup_entry(p.champion_id, games=p.games, top4=p.top4, avg_place=avg_place, base_win_rate=base_win_rate)
        for p, _win_rate, avg_place in worst_ranked[:limit]
    ]

    return ChampionMatchupsResponse(
        champion_id=champion_id,
        name=name,
        season=season,
        format="3v3",
        kind=kind,
        sample_size=sum(p.games for p, _, _ in scored),
        min_games=floor,
        base_win_rate=base_win_rate,
        best=best,
        worst=worst,
    )


_ROUND_STAGE_LABELS: dict[int, str] = {1: "Prata", 2: "Ouro", 3: "Prismático"}
# augment rarity int (build_ref_service: 0 silver/1 gold/2 prismatic) -> stage index
_RARITY_TO_ROUND: dict[int, int] = {0: 1, 1: 2, 2: 3}


@router.get(
    "/champions/{champion_id}/rounds",
    response_model=ChampionRoundsResponse,
    response_model_by_alias=True,
    summary=(
        "Curva de força por estágio de draft — prata/ouro/prismático "
        "(rollup NATIVO champion_build_stats; ToS: placement-derived). Riot "
        "não expõe timeline para a fila Arena (CHERRY) em nenhum endpoint "
        "público, então não existe força round-a-round real de se medir; "
        "isto usa os três estágios reais do draft de augments como eixo, que "
        "são os spikes de força de fato definidos pelo modo."
    ),
)
async def get_champion_rounds(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    champion_id: int,
    season: Annotated[int, Query(ge=1)] = 3,
) -> ChampionRoundsResponse:
    name = c.champion_name(champion_id) or str(champion_id)
    season_id = await c.resolve_season_id(session, season)
    empty = ChampionRoundsResponse(
        champion_id=champion_id,
        name=name,
        champion_icon_url=c.champion_icon_url(champion_id),
        season=season,
        format="3v3",
        sample_size=0,
        min_games=BUILD_MIN_GAMES,
    )
    if season_id is None:
        return empty

    stats = StatsService()
    augment_map = await get_build_ref_service()._augment_map()
    picks = await stats.champion_build_picks(
        session, season_id=season_id, champion_id=champion_id, kind="augment",
        min_games=BUILD_MIN_GAMES,
    )
    if not picks:
        return empty

    by_stage: dict[int, list[BuildPickRow]] = {1: [], 2: [], 3: []}
    for row in picks:
        entry = augment_map.get(row.pick_id)
        stage = _RARITY_TO_ROUND.get(entry[2]) if entry else None
        if stage is not None:
            by_stage[stage].append(row)

    rounds: list[ChampionRoundPoint] = []
    for stage in (1, 2, 3):
        rows = by_stage[stage]
        if not rows:
            continue
        # The best pick's own top4 rate — how far this stage's draft choice
        # can lift the champion, not a raw per-augment "winrate" claim.
        best = max(rows, key=lambda r: r.top4)
        rounds.append(
            ChampionRoundPoint(
                round=stage,
                label=_ROUND_STAGE_LABELS[stage],
                win_rate=best.top4,
                games=best.games,
            )
        )
    if not rounds:
        return empty

    peak = max(rounds, key=lambda r: r.win_rate)
    return ChampionRoundsResponse(
        champion_id=champion_id,
        name=name,
        champion_icon_url=c.champion_icon_url(champion_id),
        season=season,
        format="3v3",
        sample_size=sum(r.games for r in rounds),
        min_games=BUILD_MIN_GAMES,
        peak_round=peak.round,
        rounds=rounds,
    )


@router.get(
    "/champions/{champion_id}/builds",
    response_model=ChampionBuildVariantsResponse,
    response_model_by_alias=True,
    summary=(
        "Variantes de build do campeão agrupadas pelo augment prismático "
        "(rollup NATIVO champion_build_variant_stats; ToS: placement-derived)"
    ),
)
async def get_champion_build_variants(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    champion_id: int,
    season: Annotated[int, Query(ge=1)] = 3,
) -> ChampionBuildVariantsResponse:
    name = c.champion_name(champion_id) or str(champion_id)
    patch = await _current_patch()
    season_id = await c.resolve_season_id(session, season)
    empty = ChampionBuildVariantsResponse(
        champion_id=champion_id,
        name=name,
        patch="",
        updated_at="",
        games=0,
        min_games=BUILD_MIN_GAMES,
    )
    if season_id is None:
        return empty

    stats = StatsService()
    build_ref = get_build_ref_service()
    variants, item_map, augment_map = await asyncio.gather(
        stats.champion_build_variants(
            session, season_id=season_id, champion_id=champion_id, min_games=BUILD_MIN_GAMES
        ),
        build_ref._item_map(),
        build_ref._augment_map(),
    )
    if not variants:
        return empty

    out: list[ChampionBuildVariant] = []
    for row, item_ids in variants:
        aug_display = augment_map.get(row.pick_id)
        if aug_display is None:
            continue  # augment rotated out of the current patch — drop, don't show a bare id
        aug_name, aug_icon, _rarity = aug_display
        # Each item's own within-variant winrate isn't tracked (only pick
        # frequency) — the variant's own tier/games/placement describe the
        # BUILD, not each item individually; reused here rather than
        # fabricating a per-item number we don't have.
        resolved_items: list[BuildEntry] = []
        for item_id in item_ids:
            item_display = item_map.get(item_id)
            if item_display is None:
                continue  # item rotated out of the current patch — drop, don't show a bare id
            item_name, item_icon, *_extra = item_display
            resolved_items.append(
                BuildEntry(
                    id=item_id, name=item_name, icon_url=item_icon, tier=cast(BuildTierKey, row.tier),
                    games=row.games, avg_place=row.avg_place, top1=row.top1, top4=row.top4,
                    pick_rate=row.pick_rate,
                )
            )
        out.append(
            ChampionBuildVariant(
                id=str(row.pick_id),
                name=aug_name,
                tier=cast(BuildTierKey, row.tier),
                games=row.games,
                pick_rate=row.pick_rate,
                top4=row.top4,
                top1=row.top1,
                avg_place=row.avg_place,
                items=resolved_items,
                required_augments=[
                    BuildEntry(
                        id=row.pick_id, name=aug_name, icon_url=aug_icon, tier=cast(BuildTierKey, row.tier),
                        games=row.games, avg_place=row.avg_place, top1=row.top1, top4=row.top4,
                        pick_rate=row.pick_rate,
                    )
                ],
            )
        )

    return ChampionBuildVariantsResponse(
        champion_id=champion_id,
        name=name,
        patch=patch,
        updated_at=datetime.now(UTC).isoformat(),
        games=sum(row.games for row, _items in variants),
        min_games=BUILD_MIN_GAMES,
        variants=out,
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
