"""Tournaments router — contract §5 (+5a..5e-bis).

Wires the tournaments subsystem endpoints onto the versioned API. Read paths
return an honest empty state / 404 when nothing is provisioned (no DTO-sample
fallback); mutations go through :class:`~arena.tournaments.service.TournamentService`
(FOR UPDATE row locks; the scoring source of truth is ``compute_standings``).

Routes (mounted under ``/api/v1``):

* ``GET  /tournaments``                                  list (empty when none)
* ``GET  /tournament/{id}``                              detail (404 when unknown)
* ``GET  /admin/tournament/{id}``                        detail incl. accessKey (Admin)
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

from typing import Any

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from arena.api.cache import cache_key
from arena.api.deps import get_redis
from arena.api.rbac import record_audit, require_scope
from arena.core.logging import get_logger
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

_log = get_logger("arena.tournaments.router")

router = APIRouter(tags=["tournaments"])

_service = TournamentService()


def get_service() -> TournamentService:
    """DI seam for the tournament service (overridable in tests)."""
    return _service


async def _bust_cache(redis: Any, tournament_id: str | None = None) -> None:
    """Evict the ResponseCacheMiddleware entries a tournament mutation stales.

    ``ResponseCacheMiddleware`` (arena/api/cache.py) caches ``GET /tournaments``
    and ``GET /tournament/{id}`` for ``cache_ttl_tournaments_s`` (5 min default)
    — a create/join/link/result call never goes through that middleware itself
    (POST, or /admin/*), so without this the change is invisible on the cached
    read paths until the TTL expires. Best-effort: a cache miss just means the
    next read recomputes, so a Redis hiccup here must never fail the mutation
    that already committed.
    """
    if redis is None:
        return
    keys = [cache_key("/tournaments", b"")]
    if tournament_id:
        keys.append(cache_key(f"/tournament/{tournament_id}", b""))
    try:
        await redis.delete(*keys)
    except Exception:  # noqa: BLE001 - cache bust is best-effort
        _log.warning("tournaments.cache_bust_failed", keys=keys, exc_info=True)


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
# §5-admin — GET /admin/tournament/{id} (detalhe com accessKey)
# ---------------------------------------------------------------------------
@router.get(
    "/admin/tournament/{tournament_id}",
    response_model=TournamentDetail,
    summary="Detalhe do campeonato (Admin, inclui accessKey)",
    dependencies=[Depends(require_scope("telemetry:read"))],
)
async def get_tournament_admin(
    tournament_id: str,
    session: AsyncSession = Depends(get_session),
    service: TournamentService = Depends(get_service),
) -> TournamentDetail:
    """Same projection as the public detail, but with ``accessKey`` populated.

    The public ``GET /tournament/{id}`` never sets ``as_admin=True``, so an
    operator revisiting a tournament after creation has no other way to see
    its access key again (only the create response includes it).
    """
    return await service.get_detail(session, tournament_id, as_admin=True)


# ---------------------------------------------------------------------------
# §5 — POST /admin/tournaments (provisionar)
# ---------------------------------------------------------------------------
@router.post(
    "/admin/tournaments",
    response_model=TournamentDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Provisionar campeonato (Admin)",
    dependencies=[Depends(require_scope("tournaments:write"))],
)
async def create_tournament(
    request: Request,
    body: TournamentCreate,
    session: AsyncSession = Depends(get_session),
    service: TournamentService = Depends(get_service),
    redis: Any = Depends(get_redis),
) -> TournamentDetail:
    detail = await service.create_tournament(session, body)
    await _bust_cache(redis)
    await record_audit(request, action="tournament.created", target=detail.title)
    return detail


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
    redis: Any = Depends(get_redis),
) -> CreateTeamResponse:
    team_id = await service.create_team(
        session, tournament_id, body.key, body.team_name, body.riot_id
    )
    await _bust_cache(redis, tournament_id)
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
    redis: Any = Depends(get_redis),
) -> JoinTeamResponse:
    team_id = await service.join_team(session, tournament_id, body.key, body.team_id, body.riot_id)
    await _bust_cache(redis, tournament_id)
    return JoinTeamResponse(team_id=team_id)


# ---------------------------------------------------------------------------
# §5d-bis — POST /admin/tournament/{id}/match/{n}/link
# ---------------------------------------------------------------------------
@router.post(
    "/admin/tournament/{tournament_id}/match/{n}/link",
    response_model=TournamentDetail,
    summary="Provisionar link magnético (Admin)",
    dependencies=[Depends(require_scope("tournaments:write"))],
)
async def set_match_link(
    request: Request,
    tournament_id: str,
    n: int,
    body: SetMatchLinkRequest,
    session: AsyncSession = Depends(get_session),
    service: TournamentService = Depends(get_service),
    redis: Any = Depends(get_redis),
) -> TournamentDetail:
    detail = await service.set_match_link(session, tournament_id, n, body.magnetic_link, body.status)
    await _bust_cache(redis, tournament_id)
    await record_audit(
        request, action="tournament.match_link_set", target=f"{tournament_id}#{n}"
    )
    return detail


# ---------------------------------------------------------------------------
# §5e-bis — POST /admin/tournament/{id}/match/{n}/result
# ---------------------------------------------------------------------------
@router.post(
    "/admin/tournament/{tournament_id}/match/{n}/result",
    response_model=TournamentDetail,
    summary="Lançar resultado (Admin)",
    dependencies=[Depends(require_scope("tournaments:write"))],
)
async def submit_result(
    request: Request,
    tournament_id: str,
    n: int,
    body: SubmitResultRequest,
    session: AsyncSession = Depends(get_session),
    service: TournamentService = Depends(get_service),
    redis: Any = Depends(get_redis),
) -> TournamentDetail:
    penalties = {p.team_id: p.value for p in body.penalties} if body.penalties else None
    detail = await service.submit_result(session, tournament_id, n, body.results, penalties)
    await _bust_cache(redis, tournament_id)
    await record_audit(
        request, action="tournament.result_submitted", target=f"{tournament_id}#{n}"
    )
    return detail


__all__ = ["router", "get_service"]
