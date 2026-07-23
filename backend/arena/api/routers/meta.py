"""Contract §7 — ``GET /api/v1/meta/last-update``.

Update cadence surfaced to the UI: a global full-ranking cycle (~1h) plus a
per-tier cadence — Top-1000 refreshes every 5 min, everyone else hourly (the
Trinity read-path lane split). ``rank`` is the optional rank of the
logged-in/searched player; ``etaSec`` is a half-cycle approximation until the
real scheduler ETA is wired.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arena.api.routers import _common as c
from arena.core.config import settings
from arena.db import models as m
from arena.schemas import (
    ActivityDay,
    ActivityResponse,
    LastUpdate,
    LastUpdateGlobal,
    LastUpdateTier,
    RecordsResponse,
    SeasonRecord,
)
from arena.services import StatsService

router = APIRouter(tags=["meta"])

_GLOBAL_CYCLE_SEC = 3600  # full-ranking cycle (1h)
_TOP_CADENCE_SEC = 300  # Top-1000 lane (5 min)
_STD_CADENCE_SEC = 3600  # standard lane (1h)
_TOP_TIER_LIMIT = 1000


@router.get(
    "/meta/last-update",
    response_model=LastUpdate,
    response_model_by_alias=True,
    summary="Cadência de atualização (global + por tier)",
)
async def get_last_update(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    rank: Annotated[int | None, Query(description="Rank do jogador (opcional)")] = None,
) -> LastUpdate:
    effective_rank = rank if rank and rank > 0 else 9999
    if effective_rank <= _TOP_TIER_LIMIT:
        cadence_sec = _TOP_CADENCE_SEC
        label = "Top 1000"
    else:
        cadence_sec = _STD_CADENCE_SEC
        label = "Padrão"

    # T3.1: na réplica (REPLICA_LAG_CHECK=true) o "última atualização" vira o
    # instante REAL do último apply da replicação — o badge "atualizado há X
    # min" da UI fica honesto. Fora da réplica degrada para now().
    now = datetime.now(UTC).isoformat()
    if settings.replica_lag_check:
        from arena.services.replication_status import replica_sync_status

        sync = await replica_sync_status(session)
        if sync.last_sync_at is not None:
            now = sync.last_sync_at.isoformat()
    return LastUpdate(
        global_=LastUpdateGlobal(
            last_ts=now,
            cycle_sec=_GLOBAL_CYCLE_SEC,
            eta_sec=_GLOBAL_CYCLE_SEC // 2,
        ),
        tier=LastUpdateTier(
            rank=effective_rank,
            label=label,
            cadence_sec=cadence_sec,
            eta_sec=math.ceil(cadence_sec / 2),
        ),
    )


@router.get(
    "/meta/activity",
    response_model=ActivityResponse,
    response_model_by_alias=True,
    summary="Partidas ranqueadas processadas por dia (últimos dias)",
)
async def get_activity(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    season: Annotated[int, Query(ge=1)] = 3,
    days: Annotated[int, Query(ge=1, le=30)] = 10,
) -> ActivityResponse:
    season_id = await c.resolve_season_id(session, season)
    if season_id is None:
        return ActivityResponse(days=[], max=0)
    rows = await StatsService().season_activity(session, season_id=season_id, days=days)
    return ActivityResponse(
        days=[ActivityDay(label=label, count=count) for label, count in rows],
        max=max((count for _, count in rows), default=0),
    )


@router.get(
    "/meta/records",
    response_model=RecordsResponse,
    response_model_by_alias=True,
    summary="Recordes da temporada (destaques reais, placement-derived)",
)
async def get_records(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    season: Annotated[int, Query(ge=1)] = 3,
) -> RecordsResponse:
    season_id = await c.resolve_season_id(session, season)
    if season_id is None:
        return RecordsResponse(records=[])
    raw = await StatsService().season_records(session, season_id=season_id)

    # Hydrate record-holder display names/avatars in one round-trip.
    ids = [r.player_id for r in raw]
    name_map: dict[str, tuple[str, str, int | None]] = {}
    if ids:
        rows = await session.execute(
            select(
                m.Player.id,
                m.Player.summoner_name,
                m.Player.tag_line,
                m.Player.profile_icon_id,
            ).where(m.Player.id.in_(ids))
        )
        for pid, summoner_name, tag_line, profile_icon_id in rows:
            riot_id = c.compose_riot_id(summoner_name, tag_line)
            name, handle = c.split_riot_id(riot_id)
            name_map[str(pid)] = (name, handle, profile_icon_id)

    records = []
    for r in raw:
        name, handle, icon_id = name_map.get(r.player_id, ("—", "", None))
        records.append(
            SeasonRecord(
                key=r.key,
                label=r.label,
                value=r.value,
                name=name,
                handle=handle,
                avatar=c.avatar_for(name or r.player_id),
                profile_icon_url=c.profile_icon_url(icon_id),
                accent=r.accent,
            )
        )
    return RecordsResponse(records=records)
