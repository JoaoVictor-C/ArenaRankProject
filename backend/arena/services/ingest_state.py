"""Modo de ingestão por temporada — o interruptor do refill.

Uma temporada está em ``catching_up`` (refill: partidas descobertas vão para
``match_backlog`` e são avaliadas depois, em ordem cronológica estrita) ou em
``live`` (regime normal: avalia na chegada).

Por que o modo existe: o motor de rating é dependente de ORDEM (Plackett-Luce
sequencial, sequências, janela provisória, camada de cap PDL), mas a descoberta
é *reverso*-cronológica — a Riot lista ids do mais novo para o mais antigo — e
roda 10–20 em paralelo. Num refill de 20 dias isso gera um ladder que reflete
ordem de chegada, não de jogo. O modo ``catching_up`` separa DESCOBRIR de
AVALIAR para que a avaliação possa acontecer na ordem certa.

O ``replay_floor`` cobre o caso residual que o modo não cobre: em ``live`` uma
partida antiga ainda chega (um jogador descoberto hoje pode ter jogado há 15
dias). Registrar cada uma dessas e reprocessar na hora seria thrashing — um
jogador novo traz partidas velhas o tempo todo. Em vez disso guardamos o
``played_at`` MAIS ANTIGO visto fora de ordem e deixamos um cron consumir esse
piso quando as filas esvaziarem.

Cacheado em processo por ``ingest_state_ttl_seconds``: o gate roda no caminho de
escrita de TODA partida, e um SELECT por partida seria puro desperdício — o modo
muda talvez duas vezes por temporada.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from arena.core.config import settings
from arena.core.logging import get_logger
from arena.db import models as m

_log = get_logger("arena.services.ingest_state")

#: (mode, monotonic_deadline) por season_id.
_MODE_CACHE: dict[str, tuple[m.IngestMode, float]] = {}


def invalidate_mode_cache(season_id: str | None = None) -> None:
    """Descarta o cache de modo (uma mutação admin tem de valer na hora)."""
    if season_id is None:
        _MODE_CACHE.clear()
    else:
        _MODE_CACHE.pop(season_id, None)


async def get_mode(session: AsyncSession, season_id: str) -> m.IngestMode:
    """Modo da temporada. Ausente => ``live`` (o padrão seguro: avalia na chegada).

    Falha aberta de propósito: se a leitura explodir, devolve ``live``. Um refill
    que perde o gate produz ordem ruim (reparável por replay); um ``live`` que
    vira ``catching_up`` por engano PARA de avaliar partidas, o que é pior.
    """
    cached = _MODE_CACHE.get(season_id)
    now = time.monotonic()
    if cached is not None and cached[1] > now:
        return cached[0]
    try:
        row = (
            await session.execute(
                select(m.SeasonIngestState.mode).where(
                    m.SeasonIngestState.season_id == season_id
                )
            )
        ).scalar_one_or_none()
    except Exception:  # noqa: BLE001
        _log.warning("ingest_state.read_failed", seasonId=season_id, exc_info=True)
        return m.IngestMode.live
    mode = row or m.IngestMode.live
    _MODE_CACHE[season_id] = (mode, now + settings.ingest_state_ttl_seconds)
    return mode


async def set_mode(session: AsyncSession, season_id: str, mode: m.IngestMode) -> None:
    """Grava o modo (upsert). O caller commita."""
    await _upsert(session, season_id, {"mode": mode})
    invalidate_mode_cache(season_id)
    _log.info("ingest_state.mode_set", seasonId=season_id, mode=mode.value)


async def note_out_of_order(
    session: AsyncSession, season_id: str, played_at: datetime
) -> None:
    """Baixa o ``replay_floor`` para ``played_at`` se ele for mais antigo.

    Chamado quando uma partida é avaliada com um ``played_at`` anterior ao que a
    temporada já processou. Só GUARDA o piso — o replay em si é um cron, porque
    reprocessar por partida seria thrashing contínuo (ver docstring do módulo).
    ``LEAST`` roda no banco, então concorrência entre workers não perde o piso
    mais antigo.
    """
    from sqlalchemy import func

    stmt = (
        pg_insert(m.SeasonIngestState)
        .values(season_id=season_id, replay_floor=played_at)
        .on_conflict_do_update(
            index_elements=[m.SeasonIngestState.season_id],
            set_={
                "replay_floor": func.least(
                    func.coalesce(
                        m.SeasonIngestState.__table__.c.replay_floor, played_at
                    ),
                    played_at,
                )
            },
        )
    )
    await session.execute(stmt)


async def clear_replay_floor(session: AsyncSession, season_id: str) -> None:
    """Limpa o piso depois de um replay bem-sucedido. O caller commita."""
    await _upsert(session, season_id, {"replay_floor": None})


async def get_state(session: AsyncSession, season_id: str) -> m.SeasonIngestState | None:
    return (
        await session.execute(
            select(m.SeasonIngestState).where(m.SeasonIngestState.season_id == season_id)
        )
    ).scalar_one_or_none()


async def update_progress(session: AsyncSession, season_id: str, **fields: Any) -> None:
    """Atualiza contadores de progresso/cobertura (telemetria do console)."""
    if fields:
        await _upsert(session, season_id, fields)


async def _upsert(session: AsyncSession, season_id: str, values: dict[str, Any]) -> None:
    stmt = (
        pg_insert(m.SeasonIngestState)
        .values(season_id=season_id, **values)
        .on_conflict_do_update(
            index_elements=[m.SeasonIngestState.season_id], set_=values
        )
    )
    await session.execute(stmt)


__all__ = [
    "get_mode",
    "set_mode",
    "get_state",
    "note_out_of_order",
    "clear_replay_floor",
    "update_progress",
    "invalidate_mode_cache",
]
