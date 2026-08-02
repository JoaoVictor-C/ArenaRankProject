"""Telemetria atravessando o banco — o que impede o console de mentir.

Num deploy dividido (API pública no EC2, workers no notebook) as duas caixas têm
Redis SEPARADOS: filas arq, heartbeats de worker e o token-bucket da Riot só
existem na caixa de workers. Lendo o próprio Redis, a API do EC2 não ficava sem
resposta — ficava com a resposta ERRADA. Medido lado a lado antes desta mudança:

    /admin/overview      queueDepth  166  ->  0
    /admin/workers/live  active      true ->  false (todos)
    /admin/riot/usage    keyConfigured true -> false

Zeros convincentes fazem o operador diagnosticar uma queda inexistente. Os
aceites aqui travam as três propriedades que consertam isso:

* um snapshot fresco é servido como dado real, marcado ``snapshot`` e com idade;
* um snapshot velho vira ``unavailable`` — a UI mostra "sem sinal há N", não o
  número obsoleto;
* nunca-publicado é DISTINTO de obsoleto (configuração incompleta vs caixa que
  parou), e nenhum dos dois pode virar 0.

``reads_from_db`` é puro e roda sempre; o resto é DB-gated.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.pool import NullPool

from arena.core.config import settings
from arena.services import telemetry_snapshot as ts

# ---------------------------------------------------------------------------
# Puro
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [("db", True), ("DB", True), (" db ", True), ("redis", False), ("", False), ("x", False)],
)
def test_reads_from_db_is_explicit(
    value: str, expected: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A escolha é por configuração, NUNCA inferida da ausência de dados.

    Inferir confundiria "esta caixa não enxerga os workers" com "os workers
    estão parados" — que é exatamente o bug que este módulo existe para matar.
    """
    monkeypatch.setattr(settings, "worker_telemetry_source", value)
    assert ts.reads_from_db() is expected


def test_default_is_redis() -> None:
    """O padrão serve a caixa que DIVIDE o Redis com os workers (local, prod
    numa caixa só). Só o EC2 sobrescreve."""
    assert settings.worker_telemetry_source == "redis"


def test_stale_threshold_exceeds_publish_interval() -> None:
    """O publish roda de minuto em minuto; o limiar precisa de folga para um
    tick perdido não acender alarme (a caixa de workers é um notebook)."""
    assert settings.worker_telemetry_stale_after_seconds >= 120


# ---------------------------------------------------------------------------
# DB-gated
# ---------------------------------------------------------------------------

_db = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="telemetry snapshot tests need a migrated Postgres (set DATABASE_URL)",
)


@asynccontextmanager
async def _session() -> AsyncIterator[Any]:
    """Engine própria (o sessionmaker cacheado amarra o event loop)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    src = f"test-{uuid.uuid4().hex[:8]}"
    async with factory() as session:
        try:
            yield session, src
        finally:
            await session.rollback()
            await session.execute(
                text("DELETE FROM worker_telemetry WHERE source = :s"), {"s": src}
            )
            await session.commit()
            await engine.dispose()


@_db
async def test_publish_then_read_round_trips() -> None:
    async with _session() as (session, src):
        payload = {ts.LIVE_KEY: {"pipeline": {"standardQueue": 166}}, ts.RIOT_KEY: {"x": 1}}
        await ts.publish(session, payload, source=src)
        await session.commit()

        snap = await ts.read_snapshot(session, source=src)
        assert snap is not None
        assert snap.payload == payload
        assert snap.stale is False
        assert snap.age_seconds < 5


@_db
async def test_publish_replaces_rather_than_accumulates() -> None:
    """Só o frame mais recente vale; histórico cresceria sem ninguém a ler."""
    async with _session() as (session, src):
        await ts.publish(session, {"n": 1}, source=src)
        await ts.publish(session, {"n": 2}, source=src)
        await session.commit()

        rows = (
            await session.execute(
                text("SELECT count(*) FROM worker_telemetry WHERE source=:s"), {"s": src}
            )
        ).scalar_one()
        assert rows == 1
        snap = await ts.read_snapshot(session, source=src)
        assert snap is not None and snap.payload == {"n": 2}


@_db
async def test_old_snapshot_is_flagged_stale() -> None:
    """Passado o limiar, o dado deixa de valer como estado ATUAL.

    Sem isto, uma caixa de workers desligada congelaria o último frame e a UI
    mostraria para sempre a mesma fila — a mesma mentira de antes, só que parada.
    """
    async with _session() as (session, src):
        old = datetime.now(UTC) - timedelta(
            seconds=settings.worker_telemetry_stale_after_seconds + 60
        )
        await ts.publish(session, {"n": 1}, source=src, as_of=old)
        await session.commit()

        snap = await ts.read_snapshot(session, source=src)
        assert snap is not None
        assert snap.stale is True
        assert snap.age_seconds > settings.worker_telemetry_stale_after_seconds


@_db
async def test_never_published_is_none_not_empty() -> None:
    """``None`` != obsoleto. Um significa "a caixa nunca publicou" (configuração
    incompleta), o outro "parou de publicar" — e a UI diz coisas diferentes."""
    async with _session() as (session, src):
        assert await ts.read_snapshot(session, source=src) is None


@_db
async def test_age_is_measured_from_capture_not_read() -> None:
    """A idade é o que permite a UI dizer "visto há N min" com honestidade."""
    async with _session() as (session, src):
        captured = datetime.now(UTC) - timedelta(seconds=45)
        await ts.publish(session, {"n": 1}, source=src, as_of=captured)
        await session.commit()

        snap = await ts.read_snapshot(session, source=src)
        assert snap is not None
        assert 40 <= snap.age_seconds <= 60
        assert snap.stale is False  # 45s ainda está dentro do limiar
