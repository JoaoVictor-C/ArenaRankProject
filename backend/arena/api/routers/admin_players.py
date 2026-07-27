"""GET /admin/players/search, PATCH /admin/players/{id}/moderation.

Unlike the public ``GET /players/search`` (arena/api/routers/search.py, a
leaderboard typeahead scoped to the active season), this is a moderation
tool: it matches on PUUID too, and LEFT JOINs `player_seasons` so a banned or
otherwise inactive account with no current-season row still shows up (the
public route requires one). CR/status are read straight off stored columns
— no rank/tier here (that's the leaderboard's job, and a correlated rank
subquery over an arbitrary, not-CR-ordered match set would be both fragile
and not worth it for a moderation lookup).

`banned`/`shadowbanned`/`restricted` are real boolean columns on `Player`
(Trinity #5) — no schema change needed for the moderation PATCH beyond what
already exists.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from arena.api.rbac import record_audit, require_scope
from arena.core.logging import get_logger
from arena.schemas.admin import PlayerModerationRequest, PlayerModerationResult, PlayerSearchRow

_log = get_logger("arena.api.admin_players")

router = APIRouter(prefix="/admin/players", tags=["admin"])

_MIN_QUERY_LEN = 2


def _db_unavailable(action: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Camada de dados indisponível para {action}.",
    )


@router.get(
    "/search",
    response_model=list[PlayerSearchRow],
    response_model_by_alias=True,
    summary="Buscar jogadores por PUUID, nome ou Nome#TAG (moderação)",
    dependencies=[Depends(require_scope("telemetry:read"))],
)
async def search_players(
    q: str = Query(default="", description='PUUID, nome ou "Nome#TAG"'),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[PlayerSearchRow]:
    query = q.strip()
    if len(query) < _MIN_QUERY_LEN:
        return []

    try:
        from sqlalchemy import or_, select

        from arena.api.routers._common import avatar_for, compose_riot_id
        from arena.db import models as md
        from arena.db.session import get_sessionmaker

        pl = md.Player
        ps = md.PlayerSeason

        name_part, sep, tag_part = query.partition("#")
        name_like = f"%{name_part.strip()}%"
        conditions = [or_(pl.puuid.ilike(f"{query}%"), pl.summoner_name.ilike(name_like))]
        if sep and tag_part.strip():
            conditions.append(pl.tag_line.ilike(f"{tag_part.strip()}%"))

        async with get_sessionmaker()() as session:
            # Most recent player_seasons row per player (any season, not just
            # active) so a player who only ever had a past season still shows
            # a CR rather than nothing. Ordered by the season's starts_at, not
            # season_id — UUIDs carry no chronological order.
            se = md.Season
            latest_ps = (
                select(ps.player_id, ps.cr)
                .join(se, se.id == ps.season_id)
                .distinct(ps.player_id)
                .order_by(ps.player_id, se.starts_at.desc())
                .subquery()
            )
            stmt = (
                select(
                    pl.id,
                    pl.puuid,
                    pl.summoner_name,
                    pl.tag_line,
                    pl.region,
                    pl.banned,
                    pl.shadowbanned,
                    pl.restricted,
                    pl.moderation_flags,
                    latest_ps.c.cr,
                )
                .outerjoin(latest_ps, latest_ps.c.player_id == pl.id)
                .where(or_(*conditions))
                .limit(limit)
            )
            rows = (await session.execute(stmt)).all()
    except Exception as exc:  # pragma: no cover - DB unreachable / not migrated
        _log.warning("admin.players.search_failed", exc_info=True)
        raise _db_unavailable("buscar jogadores") from exc

    out: list[PlayerSearchRow] = []
    for pid, puuid, name, tag, region, banned, shadowbanned, restricted, flags, cr in rows:
        out.append(
            PlayerSearchRow(
                id=str(pid),
                riot_id=compose_riot_id(name, tag),
                puuid=puuid,
                region=region,
                cr=round(cr) if cr is not None else None,
                active=cr is not None,
                banned=banned,
                shadowbanned=shadowbanned,
                restricted=restricted,
                flag_count=len(flags or []),
                avatar=avatar_for(str(pid)),
            )
        )
    return out


@router.patch(
    "/{player_id}/moderation",
    response_model=PlayerModerationResult,
    response_model_by_alias=True,
    summary="Atualizar status de moderação de um jogador",
    dependencies=[Depends(require_scope("players:moderate"))],
)
async def update_player_moderation(
    request: Request,
    body: PlayerModerationRequest,
    player_id: str = Path(..., description="UUID do jogador"),
) -> PlayerModerationResult:
    """Set any of banned/shadowbanned/restricted and/or append one flag note.

    Mirrors PATCH /admin/players/{id}/select's pattern (admin.py) — lazy
    sessionmaker, 404, mutate, commit, PT-BR message — and doubles as an
    audit hook (player.moderation_updated).
    """
    try:
        from sqlalchemy import select

        from arena.db import models as md
        from arena.db.session import get_sessionmaker

        async with get_sessionmaker()() as session:
            player = (
                await session.execute(select(md.Player).where(md.Player.id == player_id).limit(1))
            ).scalar_one_or_none()
            if player is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Jogador não encontrado."
                )

            if body.banned is not None:
                player.banned = body.banned
            if body.shadowbanned is not None:
                player.shadowbanned = body.shadowbanned
            if body.restricted is not None:
                player.restricted = body.restricted

            if body.flag_type:
                actor = getattr(request.state, "actor", "unknown")
                entry: dict[str, Any] = {
                    "type": body.flag_type,
                    "note": body.note,
                    "actor": actor,
                    "at": datetime.now(UTC).isoformat(),
                }
                flags = list(player.moderation_flags or [])
                flags.append(entry)
                player.moderation_flags = flags

            await session.commit()
            banned, shadowbanned, restricted = player.banned, player.shadowbanned, player.restricted
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - DB unreachable / not migrated
        _log.warning("admin.players.moderation_failed", playerId=player_id, exc_info=True)
        raise _db_unavailable("atualizar moderação") from exc

    _log.info(
        "admin.player.moderation_updated",
        playerId=player_id,
        banned=banned,
        shadowbanned=shadowbanned,
        restricted=restricted,
    )
    await record_audit(
        request,
        action="player.moderation_updated",
        target=player_id,
        banned=banned,
        shadowbanned=shadowbanned,
        restricted=restricted,
        flagType=body.flag_type,
    )
    return PlayerModerationResult(
        player_id=player_id,
        banned=banned,
        shadowbanned=shadowbanned,
        restricted=restricted,
        message="Status de moderação atualizado.",
    )


__all__ = ["router"]
