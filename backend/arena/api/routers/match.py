"""Contract §3 — ``GET /api/v1/match/{matchId}``.

Real match detail from ``matches`` + ``match_participants`` + ``players``.
Participants are grouped into subteams (3v3 = 6 of 3 with placement 1..6; 2v2 =
8 of 2 with 1..8) ordered by placement. CR before/after/delta are projected from
the stored per-participant CR (never mu/sigma); ``modifiers`` come from the
persisted ``AppliedModifiers`` snapshot mapped to PT-BR. ``404 {detail}`` when
the matchId is unknown.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arena.api.routers import _common as c
from arena.schemas import (
    MatchAugmentEntry,
    MatchDetail,
    MatchLoadoutEntry,
    MatchPlayer,
    PdlExplanation,
    SubTeam,
)
from arena.services.build_ref_service import get_build_ref_service

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

    build_ref = get_build_ref_service()
    item_map, augment_catalog = await asyncio.gather(
        build_ref._item_map(),
        build_ref.augment_catalog(),
    )
    augment_map = {e.id: e for e in augment_catalog}

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

    # The whole lobby is already in `rows` above — no extra query needed to feed
    # map_modifiers' legacy-row (Tier B) reconstruction (unlike the paginated
    # history endpoints, which batch this across many DIFFERENT matches; see
    # arena/services/pdl_explain_service.py::lobby_context_from_rows).
    from arena.services.pdl_explain_service import lobby_context_from_rows

    lobby_ctx = lobby_context_from_rows(
        (part.match_id, part.player_id, part.state_before) for part, _ in rows
    )

    by_team: dict[int, list[tuple[Any, Any]]] = defaultdict(list)
    placement_by_team: dict[int, int] = {}
    for part, player in rows:
        by_team[part.team_id].append((part, player))
        placement_by_team[part.team_id] = part.placement

    subteams: list[SubTeam] = []
    for team_id in sorted(by_team, key=lambda t: placement_by_team.get(t, 999)):
        team_rows = by_team[team_id]
        # Subteam-scoped total, for kill_participation — NOT Riot's own
        # challenges.killParticipation, which is computed on the legacy 2-bucket
        # teamId grouping (~9 players/side in a 3v3) and is wrong for Arena's
        # real 2-3 person subteam (verified live: Riot reported 31.25% for a
        # player whose actual subteam-scoped participation was 100%).
        team_kills = sum((part.kills or 0) for part, _ in team_rows)
        players: list[MatchPlayer] = []
        for part, player in team_rows:
            riot_id = c.compose_riot_id(player.summoner_name, player.tag_line)
            name, handle = c.split_riot_id(riot_id)
            lobby_state, lobby_mean_mu = lobby_ctx.get(
                (part.match_id, part.player_id), (None, None)
            )
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
                    modifiers=c.map_modifiers(
                        part.modifiers or {},
                        placement=part.placement,
                        team_count=c.SUBTEAMS_BY_FORMAT.get(fmt, 8),
                        cr_before=part.cr_before,
                        cr_after=part.cr_after,
                        cr_delta=part.cr_delta,
                        eligible=part.eligible,
                        state=lobby_state,
                        lobby_mean_mu=lobby_mean_mu,
                    ),
                    integrity=None,
                    items=_resolve_items(part.items, item_map),
                    augments=_resolve_augments(part.augments, augment_map),
                    level=part.champion_level,
                    kills=part.kills,
                    deaths=part.deaths,
                    assists=part.assists,
                    damage_to_champions=part.damage_to_champions,
                    gold_earned=part.gold_earned,
                    kill_participation=_kill_participation(part, team_kills=team_kills),
                    damage_per_minute=_damage_per_minute(
                        part, duration_seconds=match.duration_seconds
                    ),
                    damage_taken=part.damage_taken,
                    total_heal=part.total_heal,
                    damage_self_mitigated=part.damage_self_mitigated,
                    largest_multi_kill=part.largest_multi_kill,
                    killing_sprees=part.killing_sprees,
                    time_spent_dead=part.time_spent_dead,
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


@router.get(
    "/match/{match_id}/pdl/{riot_id}",
    response_model=PdlExplanation,
    response_model_by_alias=True,
    summary="Raio-X do resultado — cálculo completo do PDL de um jogador na partida",
)
async def get_match_pdl_explanation(
    session: Annotated[AsyncSession, Depends(c.get_db)],
    match_id: Annotated[str, Path(description="ID interno ou riotMatchId da partida")],
    riot_id: Annotated[str, Path(description='Riot ID "Nome#TAG" (URL-encoded)')],
) -> PdlExplanation:
    """The "ver cálculo completo" drill-down (Raio-X do resultado, v1.4).

    Deliberately its own route, fetched on demand — see
    ``arena/services/pdl_explain_service.py``'s module docstring for why this
    isn't folded into ``GET /match/{matchId}``'s payload.
    """
    from arena.services.pdl_explain_service import PdlExplainNotFound, get_pdl_explain_service

    match = await _find_match(session, match_id)
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Partida '{match_id}' não encontrada.",
        )

    service = get_pdl_explain_service()
    try:
        return await service.explain_participant(
            session, match_id=str(match.id), riot_id=riot_id
        )
    except PdlExplainNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Jogador '{riot_id}' não participou da partida '{match_id}'.",
        ) from exc


def _resolve_items(
    ids: list[int] | None, item_map: dict[int, tuple[str, str | None, int, int, str]]
) -> list[MatchLoadoutEntry]:
    """Captured item ids -> display entries. Unmapped ids (unknown to CDragon,
    e.g. a retired item on an old match) are dropped, not shown as a bare id."""
    if not ids:
        return []
    out = []
    for item_id in ids:
        row = item_map.get(item_id)
        if row is None:
            continue
        name, icon_url, _is_boots, gold, description = row
        out.append(
            MatchLoadoutEntry(
                id=item_id,
                name=name,
                icon_url=icon_url,
                gold=gold or None,
                description=description or None,
            )
        )
    return out


def _resolve_augments(ids: list[int] | None, augment_map: dict[int, Any]) -> list[MatchAugmentEntry]:
    """Captured augment ids -> display entries, in pick order (including a
    genuine repeat from an augment-granting effect — that's what was picked)."""
    if not ids:
        return []
    out = []
    for aug_id in ids:
        entry = augment_map.get(aug_id)
        if entry is None:
            continue
        out.append(
            MatchAugmentEntry(
                id=aug_id,
                name=entry.name,
                icon_url=entry.icon_url,
                rarity=entry.rarity,
                description=entry.description or None,
            )
        )
    return out


def _kill_participation(part: Any, *, team_kills: int) -> int | None:
    """0..100 — (kills + assists) over the player's own SUBTEAM's total kills.

    ``None`` when the participant predates combat-telemetry capture (kills is
    NULL) rather than fabricating a 0. Subteam-scoped by design — see the
    module-level note on why Riot's own ``challenges.killParticipation`` (legacy
    2-bucket ``teamId`` grouping) is wrong for Arena and must not be used.
    Rounded to a whole percentage server-side — the frontend's ``nf()`` helper
    is a generic thousands-separator formatter (``Intl.NumberFormat`` defaults
    to up to 3 fraction digits), not a rate formatter, so an unrounded float
    here renders as "68,966% part." instead of "69% part.".
    """
    if part.kills is None or part.assists is None:
        return None
    if team_kills <= 0:
        return 0
    return round(float(part.kills + part.assists) / team_kills * 100)


def _damage_per_minute(part: Any, *, duration_seconds: int | None) -> int | None:
    """Damage to champions over the MATCH's total duration (not the
    participant's own ``timePlayed``) — verified against Riot's own
    ``challenges.damagePerMinute`` on a live payload, matches exactly (before
    rounding). Rounded to a whole number for the same reason as
    :func:`_kill_participation` — an unrounded float renders as
    "2.026,469 dano/min" instead of "2.026 dano/min"."""
    if part.damage_to_champions is None or not duration_seconds:
        return None
    return round(float(part.damage_to_champions) / (duration_seconds / 60))


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
