"""Tournaments router — contract §5 (+5a..5e-bis).

Wires the tournaments subsystem endpoints onto the versioned API. Read paths fall
back to the DTO sample when the table is empty; mutations go through
:class:`~arena.tournaments.service.TournamentService` (FOR UPDATE row locks; the
scoring source of truth is ``compute_standings``).

Routes (mounted under ``/api/v1``):

* ``GET  /tournaments``                                  list (sample fallback)
* ``GET  /tournament/{id}``                              detail (sample fallback)
* ``POST /admin/tournaments``                            provision → 201 detail
* ``POST /tournament/{id}/access``                       validate key (403)
* ``POST /tournament/{id}/team``                         create team → 201 (403/409)
* ``POST /tournament/{id}/join``                         join team (403/409)
* ``POST /admin/tournament/{id}/match/{n}/link``         set link/status (422)
* ``POST /admin/tournament/{id}/match/{n}/result``       submit result → recompute (422)

User-facing error strings are PT-BR; JSON keys camelCase (DTO layer). Admin
responses include ``accessKey``; player/read responses never do.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from arena.api.security import require_admin
from arena.db.session import get_session
from arena.schemas.tournaments import (
    AccessRequest,
    AccessResponse,
    CreateTeamRequest,
    CreateTeamResponse,
    JoinTeamRequest,
    JoinTeamResponse,
    SetMatchLinkRequest,
    SubmitResultRequest,
    TournamentCreate,
    TournamentDetail,
    TournamentListItem,
)
from arena.tournaments.service import TournamentService

router = APIRouter(tags=["tournaments"])

_service = TournamentService()


def get_service() -> TournamentService:
    """DI seam for the tournament service (overridable in tests)."""
    return _service


# ---------------------------------------------------------------------------
# §5a — GET /tournaments
# ---------------------------------------------------------------------------
@router.get(
    "/tournaments",
    response_model=list[TournamentListItem],
    summary="Listar campeonatos",
)
async def list_tournaments(
    session: AsyncSession = Depends(get_session),
    service: TournamentService = Depends(get_service),
) -> list[TournamentListItem]:
    return await service.list_tournaments(session)


# ---------------------------------------------------------------------------
# §5b — GET /tournament/{id}
# ---------------------------------------------------------------------------
@router.get(
    "/tournament/{tournament_id}",
    response_model=TournamentDetail,
    summary="Detalhe do campeonato",
)
async def get_tournament(
    tournament_id: str,
    session: AsyncSession = Depends(get_session),
    service: TournamentService = Depends(get_service),
) -> TournamentDetail:
    return await service.get_detail(session, tournament_id)


# ---------------------------------------------------------------------------
# §5 — POST /admin/tournaments (provisionar)
# ---------------------------------------------------------------------------
@router.post(
    "/admin/tournaments",
    response_model=TournamentDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Provisionar campeonato (Admin)",
    dependencies=[Depends(require_admin)],
)
async def create_tournament(
    body: TournamentCreate,
    session: AsyncSession = Depends(get_session),
    service: TournamentService = Depends(get_service),
) -> TournamentDetail:
    return await service.create_tournament(session, body)


# ---------------------------------------------------------------------------
# §5a-bis — POST /tournament/{id}/access
# ---------------------------------------------------------------------------
@router.post(
    "/tournament/{tournament_id}/access",
    response_model=AccessResponse,
    summary="Validar chave de acesso",
)
async def validate_access(
    tournament_id: str,
    body: AccessRequest,
    session: AsyncSession = Depends(get_session),
    service: TournamentService = Depends(get_service),
) -> AccessResponse:
    return await service.validate_access(session, tournament_id, body.key)


# ---------------------------------------------------------------------------
# §5b-bis — POST /tournament/{id}/team
# ---------------------------------------------------------------------------
@router.post(
    "/tournament/{tournament_id}/team",
    response_model=CreateTeamResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Criar equipe",
)
async def create_team(
    tournament_id: str,
    body: CreateTeamRequest,
    session: AsyncSession = Depends(get_session),
    service: TournamentService = Depends(get_service),
) -> CreateTeamResponse:
    team_id = await service.create_team(
        session, tournament_id, body.key, body.team_name, body.riot_id
    )
    return CreateTeamResponse(team_id=team_id)


# ---------------------------------------------------------------------------
# §5c-bis — POST /tournament/{id}/join
# ---------------------------------------------------------------------------
@router.post(
    "/tournament/{tournament_id}/join",
    response_model=JoinTeamResponse,
    summary="Entrar em equipe existente",
)
async def join_team(
    tournament_id: str,
    body: JoinTeamRequest,
    session: AsyncSession = Depends(get_session),
    service: TournamentService = Depends(get_service),
) -> JoinTeamResponse:
    team_id = await service.join_team(session, tournament_id, body.key, body.team_id, body.riot_id)
    return JoinTeamResponse(team_id=team_id)


# ---------------------------------------------------------------------------
# §5d-bis — POST /admin/tournament/{id}/match/{n}/link
# ---------------------------------------------------------------------------
@router.post(
    "/admin/tournament/{tournament_id}/match/{n}/link",
    response_model=TournamentDetail,
    summary="Provisionar link magnético (Admin)",
    dependencies=[Depends(require_admin)],
)
async def set_match_link(
    tournament_id: str,
    n: int,
    body: SetMatchLinkRequest,
    session: AsyncSession = Depends(get_session),
    service: TournamentService = Depends(get_service),
) -> TournamentDetail:
    return await service.set_match_link(session, tournament_id, n, body.magnetic_link, body.status)


# ---------------------------------------------------------------------------
# §5e-bis — POST /admin/tournament/{id}/match/{n}/result
# ---------------------------------------------------------------------------
@router.post(
    "/admin/tournament/{tournament_id}/match/{n}/result",
    response_model=TournamentDetail,
    summary="Lançar resultado (Admin)",
    dependencies=[Depends(require_admin)],
)
async def submit_result(
    tournament_id: str,
    n: int,
    body: SubmitResultRequest,
    session: AsyncSession = Depends(get_session),
    service: TournamentService = Depends(get_service),
) -> TournamentDetail:
    penalties = {p.team_id: p.value for p in body.penalties} if body.penalties else None
    return await service.submit_result(session, tournament_id, n, body.results, penalties)


__all__ = ["router", "get_service"]
