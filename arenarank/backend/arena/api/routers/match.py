"""Contract §3 — ``GET /api/v1/match/{matchId}``.

Real match detail from ``matches`` + ``match_participants`` + ``players``.
Participants are grouped into subteams (3v3 = 6 of 3 with placement 1..6; 2v2 =
8 of 2 with 1..8) ordered by placement. CR before/after/delta are projected from
the stored per-participant CR (never mu/sigma); ``modifiers`` come from the
persisted ``AppliedModifiers`` snapshot mapped to PT-BR. ``404 {detail}`` when
the matchId is unknown.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arena.api.routers import _common as c
from arena.schemas import MatchDetail, MatchPlayer, SubTeam

router = APIRouter(tags=["match"])


@router.get(
    "/match/{match_id}",
    response_model=MatchDetail,
    response_model_by_alias=True,
    summary="Detalhe de partida (subteams, CR, modificadores)",
)
async def get_match(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    match_id: Annotated[str, Path(description="ID interno ou riotMatchId da partida")],
) -> MatchDetail:
    from arena.db import models as m

    match = await _find_match(session, match_id)
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Partida '{match_id}' não encontrada.",
        )

    fmt = c.FORMAT_BY_QUEUE.get(match.queue_id, "3v3")
    queue_label = "Arena 3v3" if fmt == "3v3" else "Arena 2v2"

    # Participants joined to players for display names.
    rows = (
        await session.execute(
            select(m.MatchParticipant, m.Player)
            .join(m.Player, m.Player.id == m.MatchParticipant.player_id)
            .where(m.MatchParticipant.match_id == match.id)
        )
    ).all()

    by_team: dict[int, list[tuple[Any, Any]]] = defaultdict(list)
    placement_by_team: dict[int, int] = {}
    for part, player in rows:
        by_team[part.team_id].append((part, player))
        placement_by_team[part.team_id] = part.placement

    subteams: list[SubTeam] = []
    for team_id in sorted(by_team, key=lambda t: placement_by_team.get(t, 999)):
        players: list[MatchPlayer] = []
        for part, player in by_team[team_id]:
            riot_id = c.compose_riot_id(player.summoner_name, player.tag_line)
            name, handle = c.split_riot_id(riot_id)
            players.append(
                MatchPlayer(
                    riot_id=riot_id,
                    name=name,
                    handle=handle,
                    avatar=c.avatar_for(str(player.id)),
                    profile_icon_url=c.profile_icon_url(player.profile_icon_id),
                    champion=c.avatar_for(f"{player.id}:{part.champion_id}"),
                    # Real ddragon champion name + icon URL (warmed map; sync-fast).
                    champion_name=c.champion_name(part.champion_id),
                    champion_icon_url=c.champion_icon_url(part.champion_id),
                    cr_before=round(part.cr_before),
                    cr_after=round(part.cr_after),
                    cr_delta=round(part.cr_delta),
                    modifiers=c.map_modifiers(part.modifiers or {}),
                    integrity=None,
                )
            )
        subteams.append(SubTeam(placement=placement_by_team.get(team_id, 0), players=players))

    return MatchDetail(
        match_id=match.riot_match_id or str(match.id),
        format=fmt,
        queue_label=queue_label,
        played_at=match.played_at.isoformat() if match.played_at else "",
        duration_sec=match.duration_seconds or 0,
        patch=_patch_of(match),
        processed_at=match.processed_at.isoformat() if match.processed_at else "",
        subteams=subteams,
    )


async def _find_match(session: AsyncSession, match_id: str) -> Any:
    """Resolve a match by internal UUID or by ``riot_match_id``."""
    import uuid

    from arena.db import models as m

    stmt = select(m.Match)
    try:
        as_uuid = uuid.UUID(match_id)
        stmt = stmt.where(m.Match.id == as_uuid)
    except ValueError:
        stmt = stmt.where(m.Match.riot_match_id == match_id)
    return (await session.execute(stmt.limit(1))).scalar_one_or_none()


def _patch_of(match: Any) -> str:
    flags = match.integrity_flags
    if isinstance(flags, dict):
        patch = flags.get("patch")
        if isinstance(patch, str):
            return patch
    return "desconhecido"
