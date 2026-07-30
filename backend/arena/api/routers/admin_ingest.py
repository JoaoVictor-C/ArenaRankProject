"""/admin/ingest — controle e observação do refill de temporada.

Um refill é a operação de repovoar a base para a janela da temporada: com
``players`` vazio nada semeia a descoberta (a Riot não tem endpoint de "todas as
partidas da região"), e a descoberta chega em ordem essencialmente arbitrária, o
que produziria um ladder que reflete ordem de chegada e não de jogo. Estas rotas
iniciam esse processo e mostram o andamento.

Leitura sob ``telemetry:read`` (todo papel tem); mutações sob ``season:write`` —
um refill dispara uma rajada grande de chamadas à Riot e muda como a temporada
inteira é avaliada, então é da mesma família de privilégio que mexer na
temporada. Toda mutação é auditada.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from arena.api.deps import get_redis
from arena.api.rbac import record_audit, require_scope
from arena.core.logging import get_logger
from arena.schemas.admin import IngestStatus

_log = get_logger("arena.api.admin_ingest")

router = APIRouter(prefix="/admin/ingest", tags=["admin"])


def _unavailable(what: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Camada de dados indisponível para {what}.",
    )


async def _season_id() -> str:
    from arena.workers.scheduler import _current_season_id

    season_id = await _current_season_id()
    if season_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nenhuma temporada configurada.",
        )
    return season_id


@router.get(
    "",
    response_model=IngestStatus,
    response_model_by_alias=True,
    summary="Estado do refill da temporada (modo, fronteira, cobertura, replay)",
    dependencies=[Depends(require_scope("telemetry:read"))],
)
async def get_ingest_status() -> IngestStatus:
    try:
        from sqlalchemy import func, select

        from arena.db import models as m
        from arena.db.session import get_sessionmaker
        from arena.services import ingest_state
    except Exception as exc:  # pragma: no cover - import-order tolerance
        raise _unavailable("o estado de ingestão") from exc

    season_id = await _season_id()
    try:
        async with get_sessionmaker()() as session:
            state = await ingest_state.get_state(session, season_id)
            staged = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(m.MatchBacklog)
                        .where(m.MatchBacklog.season_id == season_id)
                    )
                ).scalar_one()
            )
            oldest = (
                await session.execute(
                    select(func.min(m.MatchBacklog.played_at)).where(
                        m.MatchBacklog.season_id == season_id
                    )
                )
            ).scalar_one_or_none()
    except Exception as exc:
        raise _unavailable("o estado de ingestão") from exc

    mode = state.mode.value if state else "live"
    return IngestStatus(
        season_id=season_id,
        mode=mode,
        staged=staged,
        oldest_staged_at=oldest.isoformat() if oldest else None,
        frontier_pending=state.frontier_pending if state else 0,
        frontier_done=state.frontier_done if state else 0,
        saturated_at=state.saturated_at.isoformat() if state and state.saturated_at else None,
        coverage_pct=state.coverage_pct if state else None,
        coverage_at=state.coverage_at.isoformat() if state and state.coverage_at else None,
        replay_floor=state.replay_floor.isoformat() if state and state.replay_floor else None,
    )


@router.post(
    "/bootstrap",
    response_model=IngestStatus,
    response_model_by_alias=True,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Iniciar refill: semeia a descoberta e para de avaliar na chegada",
    dependencies=[Depends(require_scope("season:write"))],
)
async def start_bootstrap_route(
    request: Request,
    redis: Annotated[Any, Depends(get_redis)],
) -> IngestStatus:
    """Coloca a temporada em ``catching_up`` e injeta as sementes configuradas.

    A partir daqui as partidas descobertas são ESTACIONADAS em vez de avaliadas;
    o drenador as avalia depois em ordem cronológica estrita. A temporada volta
    sozinha para ``live`` quando a fronteira satura e o backlog esvazia.
    """
    try:
        from arena.workers.bootstrap import start_bootstrap
    except Exception as exc:  # pragma: no cover
        raise _unavailable("o bootstrap") from exc

    season_id = await _season_id()
    result = await start_bootstrap(redis, season_id)
    if result.get("status") != "ok":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Nenhuma semente configurada ou resolvível "
                "(defina BOOTSTRAP_SEED_RIOT_IDS)."
                if result.get("reason") in {"no seeds configured", "no seed resolved"}
                else "Falha ao iniciar o refill."
            ),
        )
    await record_audit(
        request,
        action="ingest.bootstrap_started",
        target=season_id,
        seeds=result.get("seeds"),
        queued=result.get("queued"),
    )
    return await get_ingest_status()


@router.post(
    "/stop",
    response_model=IngestStatus,
    response_model_by_alias=True,
    summary="Encerrar refill: volta a avaliar na chegada (backlog segue drenando)",
    dependencies=[Depends(require_scope("season:write"))],
)
async def stop_bootstrap_route(request: Request) -> IngestStatus:
    try:
        from arena.workers.bootstrap import stop_bootstrap
    except Exception as exc:  # pragma: no cover
        raise _unavailable("o bootstrap") from exc

    season_id = await _season_id()
    await stop_bootstrap(season_id)
    await record_audit(request, action="ingest.bootstrap_stopped", target=season_id)
    return await get_ingest_status()


__all__ = ["router"]
