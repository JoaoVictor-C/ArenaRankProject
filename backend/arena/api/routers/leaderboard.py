"""Contract §1 — ``GET /api/v1/leaderboard``.

Ranked page within a ``(season, format, scope)`` scope. CR-ordered (never
mu/sigma): the hot Top-N comes from :class:`LeaderboardService` (Redis
read-through, Postgres fallback); display fields are hydrated from
``player_seasons`` + ``players``. ``rank`` is 1-based within the scope; ``tier``
is derived from that rank. camelCase JSON via ``response_model_by_alias=True``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arena.api.deps import get_redis
from arena.api.routers import _common as c
from arena.schemas import LeaderboardChampion, LeaderboardResponse, LeaderboardRow
from arena.schemas.common import Format

router = APIRouter(tags=["leaderboard"])


def _champion_stat(d: dict[str, Any]) -> LeaderboardChampion:
    """Build a podium-hover champion card from one ``champion_stats`` aggregate row.

    Percentages are placement-derived (winrate = 1st-half wins / games; ``top_half``
    = top-half finishes / games); ``avg_place`` is the mean colocação (1 casa).
    """
    cid = int(d["id"])
    games = int(d.get("games", 0))
    wins = int(d.get("wins", 0))
    top_half = int(d.get("top_half", 0))
    place_sum = int(d.get("place_sum", 0))
    name = c.champion_name(cid) or f"Campeão {cid}"
    return LeaderboardChampion(
        champion_id=cid,
        name=name,
        icon_url=c.champion_icon_url(cid),
        games=games,
        winrate=round(100 * wins / games) if games else 0,
        top_half=round(100 * top_half / games) if games else 0,
        avg_place=round(place_sum / games, 1) if games else 0.0,
    )


@router.get(
    "/leaderboard",
    response_model=LeaderboardResponse,
    response_model_by_alias=True,
    summary="Leaderboard ranqueado por CR no escopo",
)
async def get_leaderboard(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    redis: Annotated[Redis | None, Depends(get_redis)],
    format: Annotated[Format, Query(description="3v3 (queue 1750) | 2v2 (queue 1700)")] = "3v3",
    scope: Annotated[str, Query(description="global | br | friends")] = "global",
    season: Annotated[int, Query(ge=1, description="Número da temporada (1..N)")] = 3,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LeaderboardResponse:
    from arena.services import LeaderboardService

    season_id = await c.resolve_season_id(session, season)
    if season_id is None:
        # No seasons yet → empty, well-formed page (frontend renders empty state).
        return LeaderboardResponse(updated_at="", total=0, season=season, format=format, rows=[])

    # Redis read-through (ZSET Top-N); a dependency degrada para None se o
    # Redis estiver fora — o service então cai direto no Postgres.
    service = LeaderboardService(redis=redis)
    page = await service.get_page(
        session, season_id=season_id, fmt=format, offset=offset, limit=limit
    )

    # Hydrate display fields for the page's players in one round-trip.
    player_ids = [row.player_id for row in page.rows]
    hydrated = await _hydrate(session, season_id, player_ids)

    from arena.services import StatsService

    stats = StatsService()
    # Champion identity tags: each player's rank by average placement on their
    # MAIN champion (one windowed query over the page's mains). Feeds the
    # "TOP n {champ}" / "OTP {champ}" chips.
    mains = {
        pid: h["otp"].champion_id for pid, h in hydrated.items() if h.get("otp") is not None
    }
    champ_ranks = await stats.champion_placement_rank_by_player(
        session, season_id=season_id, mains=mains
    )

    rows: list[LeaderboardRow] = []
    for entry in page.rows:
        h = hydrated.get(entry.player_id)
        riot_id = (
            c.compose_riot_id(h["name"], h["tag"]) if h else f"Desconhecido#{entry.player_id[:4]}"
        )
        name, handle = c.split_riot_id(riot_id)
        wins, losses = (h["wins"], h["losses"]) if h else (0, 0)
        games = wins + losses
        delta7d = h["delta7d"] if h else 0
        # ≤2 champion-first badges (champrank/otp → hot). Champion inputs are
        # pre-batched in ``_hydrate`` + ``champ_ranks`` above (no per-row I/O).
        otp = h["otp"] if h else None
        cr_rank = champ_ranks.get(entry.player_id)
        tags = stats.build_player_tags(
            delta7d=delta7d,
            otp=otp,
            otp_champion_name=c.champion_name(otp.champion_id) if otp else None,
            otp_icon_url=c.champion_icon_url(otp.champion_id) if otp else None,
            champ_rank=cr_rank,
            champ_rank_name=c.champion_name(cr_rank.champion_id) if cr_rank else None,
            champ_rank_icon_url=c.champion_icon_url(cr_rank.champion_id) if cr_rank else None,
        )
        # Real mains (up to 4) from champion_stats → ddragon icon URLs + podium
        # hover stats; the parallel gradient ``champions`` placeholders stay as a
        # fallback. ``champions_stats`` parallels ``champions`` by index.
        champ_details: list[dict[str, Any]] = h["champion_details"] if h else []
        champ_count = min(4, len(champ_details)) if champ_details else min(3, games)
        champions_stats = [_champion_stat(d) for d in champ_details[:4]]
        champion_icon_urls = [
            cs.icon_url for cs in champions_stats if cs.icon_url is not None
        ]
        rows.append(
            LeaderboardRow(
                rank=entry.rank,
                riot_id=riot_id,
                name=name,
                handle=handle,
                avatar=c.avatar_for(entry.player_id),
                profile_icon_url=c.profile_icon_url(h["profile_icon_id"]) if h else None,
                cr=entry.cr,
                delta7d=delta7d,
                wins=wins,
                losses=losses,
                winrate=round(100 * wins / games) if games else 0,
                top4=h["top4"] if h else 0,
                top1=h["top1"] if h else 0,
                top1_streak=h["top1_streak"] if h else 0,
                tier=c.tier_from_rank(entry.rank),
                tags=tags,
                in_game=None,
                champions=[c.avatar_for(entry.player_id, i + 100) for i in range(champ_count)],
                champion_icon_urls=champion_icon_urls,
                champions_stats=champions_stats,
            )
        )

    # T3.1: na réplica, updatedAt reflete o último apply da replicação (idade
    # real dos dados), não o instante da resposta.
    updated_at = page.updated_at
    from arena.core.config import settings as _settings

    if _settings.replica_lag_check:
        from arena.services.replication_status import replica_sync_status

        sync = await replica_sync_status(session)
        if sync.last_sync_at is not None:
            updated_at = sync.last_sync_at.isoformat()

    return LeaderboardResponse(
        updated_at=updated_at,
        total=page.total,
        season=season,
        format=format,
        rows=rows,
    )


async def _hydrate(
    session: AsyncSession, season_id: str, player_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """Load display fields (name/tag + win/loss/top4/delta7d + ddragon ids) per player.

    Wins/losses/top4 are the **real** placement-derived aggregates computed in a
    single grouped query by :meth:`StatsService.win_loss_by_player` (mode-aware:
    DUOS 8-team -> win<=4, TRIOS 6-team -> win<=3). Players with no eligible games
    degrade to zeroed counters rather than failing.

    ``delta7d`` is the CR change over the last ~7 days from the ``cr_snapshots``
    hypertable, batched in one grouped query (:meth:`StatsService.delta7d_by_player`).
    Tag inputs (``region``, ``matches_played``, ``provisional``, ``otp``) are also
    pre-loaded here so the row build does zero per-row I/O: ``region``/
    ``matches_played``/``placement_matches_remaining`` come from the page's
    player/season scan, and ``otp`` from one grouped ``champion_stats`` pass.

    ddragon (v1.1): also loads each player's ``profile_icon_id`` (for the summoner
    icon URL) and their top mains (``champion_ids``, busiest first from
    ``champion_stats``) for real champion icon URLs — both in batched queries (no
    N+1). The router resolves the actual ddragon URLs synchronously from the
    warmed champion map.
    """
    if not player_ids:
        return {}
    from arena.db import models as m
    from arena.services import StatsService

    rows = await session.execute(
        select(
            m.Player.id,
            m.Player.summoner_name,
            m.Player.tag_line,
            m.Player.profile_icon_id,
            m.Player.region,
            m.PlayerSeason.matches_played,
            m.PlayerSeason.placement_matches_remaining,
        )
        .join(m.PlayerSeason, m.PlayerSeason.player_id == m.Player.id)
        .where(
            m.PlayerSeason.season_id == season_id,
            m.Player.id.in_(player_ids),
        )
    )

    stats = StatsService()
    # Real W/L for the whole page in one grouped aggregate (no N+1).
    wl = await stats.win_loss_by_player(session, season_id=season_id, player_ids=player_ids)
    # CR change over ~7d from cr_snapshots, batched (one grouped query).
    delta7d = await stats.delta7d_by_player(session, season_id=season_id, player_ids=player_ids)
    # OTP signal (most-played champion share) for the page, one grouped query.
    otp = await stats.otp_by_player(session, season_id=season_id, player_ids=player_ids)
    # Current consecutive top-1 streak (placement==1) → the "on fire" table row.
    top1_streak = await stats.top1_streak_by_player(
        session, season_id=season_id, player_ids=player_ids
    )

    # Top mains per player (busiest first) for ddragon champion icons + podium
    # hover stats — one batch query over the pre-aggregated champion_stats table.
    champ_details_by_player = await _top_champions(session, season_id, player_ids)

    out: dict[str, dict[str, Any]] = {}
    for pid, name, tag, profile_icon_id, region, matches_played, placement_rem in rows.all():
        key = str(pid)
        rec = wl.get(key)
        out[key] = {
            "name": name,
            "tag": tag,
            "region": region,
            "profile_icon_id": profile_icon_id,
            "champion_details": champ_details_by_player.get(key, []),
            "wins": rec.wins if rec else 0,
            "losses": rec.losses if rec else 0,
            "top4": rec.top4 if rec else 0,
            "top1": rec.first_rate if rec else 0,
            "delta7d": delta7d.get(key, 0),
            "matches_played": int(matches_played or 0),
            "provisional": c.is_provisional(placement_rem or 0),
            "otp": otp.get(key),
            "top1_streak": top1_streak.get(key, 0),
        }
    return out


async def _top_champions(
    session: AsyncSession, season_id: str, player_ids: list[str], per_player: int = 4
) -> dict[str, list[dict[str, Any]]]:
    """Map ``player_id -> [{id, games, wins, top_half, place_sum}, ...]`` (busiest first).

    Single scan of ``champion_stats`` for the page (no N+1); ordered by games so
    the first entries are the player's real mains. The router turns each into a
    ddragon icon URL plus the placement-derived mini-stats behind the podium
    hover card (winrate / top-half % / colocação média).
    """
    from arena.db import models as m

    rows = await session.execute(
        select(
            m.ChampionStat.player_id,
            m.ChampionStat.champion_id,
            m.ChampionStat.matches_played,
            m.ChampionStat.wins,
            m.ChampionStat.top_half,
            m.ChampionStat.total_placement_sum,
        )
        .where(
            m.ChampionStat.season_id == season_id,
            m.ChampionStat.player_id.in_(player_ids),
        )
        .order_by(
            m.ChampionStat.player_id,
            m.ChampionStat.matches_played.desc(),
        )
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for pid, champion_id, games, wins, top_half, place_sum in rows.all():
        key = str(pid)
        bucket = out.setdefault(key, [])
        if len(bucket) < per_player:
            bucket.append(
                {
                    "id": int(champion_id),
                    "games": int(games or 0),
                    "wins": int(wins or 0),
                    "top_half": int(top_half or 0),
                    "place_sum": int(place_sum or 0),
                }
            )
    return out
