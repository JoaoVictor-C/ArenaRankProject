"""Telemetria de workers atravessando o banco compartilhado.

Num deploy dividido (API pública no EC2, workers no notebook) as duas caixas têm
Redis SEPARADOS. Filas arq, heartbeats de worker e o token-bucket da Riot vivem
SÓ na caixa de workers, então a API do EC2 não enxerga nada disso. E o problema
não era ficar sem dado — era o dado errado: medido lado a lado, o mesmo endpoint
devolve do EC2 ``queueDepth: 0`` contra 166 reais, todos os workers como
``active: false`` e a chave da Riot como não configurada. Um operador olhando
isso conclui que a ingestão morreu.

A saída é publicar pelo único canal que as duas caixas já compartilham: o RDS.
Não precisa de VPN, IP fixo nem porta de entrada no notebook (que fica atrás de
NAT e às vezes desligado) — o notebook EMPURRA, o EC2 nunca precisa alcançá-lo.

O que importa aqui é :func:`read_snapshot` devolver a IDADE junto com o dado.
Com o notebook offline o EC2 continua lendo o último snapshot; sem ``as_of`` isso
seria a mesma mentira de antes, só que congelada. Com ele, a UI mostra "visto há
14 min" — e "não sei" é uma resposta melhor que um zero convincente.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from arena.core.config import settings
from arena.core.logging import get_logger
from arena.db import models as m

_log = get_logger("arena.services.telemetry_snapshot")

#: Chaves do payload publicado. Uma constante para o publicador e o leitor não
#: divergirem em silêncio (o payload é JSONB, ninguém valida o formato).
LIVE_KEY = "live"
RIOT_KEY = "riot"


@dataclass(slots=True)
class SnapshotRead:
    """Um snapshot lido do banco, com a idade que permite julgá-lo."""

    payload: dict[str, Any]
    as_of: datetime
    age_seconds: int
    #: Velho demais para ser apresentado como estado atual. A UI mostra
    #: "indisponível" + a idade, em vez do número obsoleto.
    stale: bool


async def publish(
    session: AsyncSession,
    payload: dict[str, Any],
    *,
    source: str | None = None,
    as_of: datetime | None = None,
) -> None:
    """Grava o snapshot desta caixa (upsert por ``source``). O caller commita.

    Substitui em vez de acumular: só o frame mais recente tem valor, e uma
    tabela de histórico cresceria para sempre sem ninguém a ler.
    """
    src = source or settings.worker_telemetry_publish_source
    ts = as_of or datetime.now(UTC)
    stmt = (
        pg_insert(m.WorkerTelemetry)
        .values(source=src, as_of=ts, payload=payload)
        .on_conflict_do_update(
            index_elements=[m.WorkerTelemetry.source],
            set_={"as_of": ts, "payload": payload},
        )
    )
    await session.execute(stmt)


async def read_snapshot(
    session: AsyncSession, *, source: str | None = None
) -> SnapshotRead | None:
    """Último snapshot publicado, ou ``None`` se nunca houve nenhum.

    ``None`` é um estado distinto de "obsoleto" e a UI trata os dois de forma
    diferente: nunca-publicado significa configuração incompleta (a caixa de
    workers não está a publicar), obsoleto significa que ela parou de responder.
    """
    src = source or settings.worker_telemetry_publish_source
    row = (
        await session.execute(
            select(m.WorkerTelemetry.as_of, m.WorkerTelemetry.payload).where(
                m.WorkerTelemetry.source == src
            )
        )
    ).first()
    if row is None:
        return None
    as_of = row.as_of if row.as_of.tzinfo else row.as_of.replace(tzinfo=UTC)
    age = max(0, int((datetime.now(UTC) - as_of).total_seconds()))
    return SnapshotRead(
        payload=row.payload or {},
        as_of=as_of,
        age_seconds=age,
        stale=age > settings.worker_telemetry_stale_after_seconds,
    )


def reads_from_db() -> bool:
    """True quando este processo deve ler telemetria do banco, não do Redis.

    Explícito por configuração, nunca inferido: deduzir pela ausência de dados
    no Redis confundiria "esta caixa não enxerga os workers" com "os workers
    estão todos parados" — que é exatamente o erro que este módulo existe para
    corrigir.
    """
    return settings.worker_telemetry_source.strip().lower() == "db"


__all__ = ["publish", "read_snapshot", "reads_from_db", "SnapshotRead", "LIVE_KEY", "RIOT_KEY"]
