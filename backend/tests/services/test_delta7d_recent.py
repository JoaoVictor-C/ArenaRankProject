"""delta7d sobre ``cr_snapshots_recent`` — T2.3 do workaround_readpath.

Aceites cobertos:

* o statement de produção agora lê ``cr_snapshots_recent`` (o espelho plano
  replicável), não a hypertable;
* **paridade**: o MESMO builder (`StatsService._delta7d_stmt`), executado sobre
  duas tabelas com o shape de ``cr_snapshots`` e de ``cr_snapshots_recent``
  carregadas com a MESMA fixture, devolve resultados idênticos (a troca de
  tabela não muda a semântica do delta7d);
* semântica do delta em si: baseline ~7d, fallback para o snapshot mais
  antigo, jogador com 1 snapshot → delta 0, jogador sem linhas → ausente.

Roda em sqlite in-memory (aiosqlite): o builder é SQL portátil (joins +
agregados), e é exatamente o objeto executado em produção.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from arena.db import models as m
from arena.services.stats_service import StatsService

SEASON = "season-1"
NOW = datetime(2026, 7, 20, 12, 0, 0)
CUTOFF = NOW - timedelta(days=7)


def _snapshot_shaped_table(metadata: sa.MetaData, name: str) -> sa.Table:
    """Mesmas colunas dos modelos de snapshot, em tipos portáveis p/ sqlite."""
    return sa.Table(
        name,
        metadata,
        sa.Column("player_id", sa.String, nullable=False),
        sa.Column("season_id", sa.String, nullable=False),
        sa.Column("snapshot_at", sa.DateTime, nullable=False),
        sa.Column("cr", sa.Float, nullable=False),
        sa.Column("mu", sa.Float, nullable=False),
        sa.Column("sigma", sa.Float, nullable=False),
        sa.Column("matches_played", sa.Integer, nullable=False),
    )


def _row(player: str, at: datetime, cr: float) -> dict[str, Any]:
    return {
        "player_id": player,
        "season_id": SEASON,
        "snapshot_at": at,
        "cr": cr,
        "mu": 25.0,
        "sigma": 8.0,
        "matches_played": 1,
    }


# Fixture: cobre baseline exato no corte, fallback earliest e snapshot único.
FIXTURE = [
    # A: histórico longo — baseline = último snapshot <= corte (900), atual 1000.
    _row("A", NOW - timedelta(days=20), 800.0),
    _row("A", CUTOFF, 900.0),  # exatamente na borda: conta como baseline
    _row("A", NOW - timedelta(days=1), 980.0),
    _row("A", NOW, 1000.0),
    # B: só snapshots novos — baseline degrada p/ o mais antigo (700), atual 760.
    _row("B", NOW - timedelta(days=3), 700.0),
    _row("B", NOW - timedelta(days=1), 760.0),
    # C: snapshot único — delta 0.
    _row("C", NOW - timedelta(days=2), 500.0),
    # E: outra temporada — não pode vazar para a consulta da SEASON.
    {**_row("E", NOW, 999.0), "season_id": "season-2"},
]

EXPECTED = {"A": 100, "B": 60, "C": 0}  # D (sem linhas) ausente


async def _run_stmt_over(table: sa.Table) -> dict[str, int]:
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(table.metadata.create_all)
            await conn.execute(table.insert(), FIXTURE)
            stmt = StatsService._delta7d_stmt(
                table, season_id=SEASON, ids=["A", "B", "C", "D"], cutoff=CUTOFF
            )
            rows = (await conn.execute(stmt)).all()
    finally:
        await engine.dispose()
    return {
        str(r.player_id): round(float(r.current_cr) - float(r.baseline_cr))
        for r in rows
        if r.current_cr is not None and r.baseline_cr is not None
    }


async def test_semantics_on_fixture() -> None:
    metadata = sa.MetaData()
    table = _snapshot_shaped_table(metadata, "cr_snapshots_recent")
    assert await _run_stmt_over(table) == EXPECTED


async def test_parity_old_table_vs_new_table() -> None:
    md_old, md_new = sa.MetaData(), sa.MetaData()
    old = _snapshot_shaped_table(md_old, "cr_snapshots")
    new = _snapshot_shaped_table(md_new, "cr_snapshots_recent")
    assert await _run_stmt_over(old) == await _run_stmt_over(new) == EXPECTED


async def test_service_reads_the_flat_mirror() -> None:
    """delta7d_by_player emite SQL contra cr_snapshots_recent (não a hypertable)."""
    captured: list[Any] = []

    class CapturingSession:
        async def execute(self, stmt: Any) -> Any:
            captured.append(stmt)

            class _Empty:
                @staticmethod
                def all() -> list[Any]:
                    return []

            return _Empty()

    out = await StatsService().delta7d_by_player(
        CapturingSession(),  # type: ignore[arg-type]
        season_id=SEASON,
        player_ids=["A"],
    )
    assert out == {}
    sql = str(captured[0])
    assert "cr_snapshots_recent" in sql
    assert "FROM cr_snapshots " not in sql and "cr_snapshots\n" not in sql


def test_models_share_the_snapshot_shape() -> None:
    """Se alguém adicionar coluna num lado e esquecer o outro, isto quebra."""
    hyper = {c.name: type(c.type).__name__ for c in m.CrSnapshot.__table__.columns}
    flat = {c.name: type(c.type).__name__ for c in m.CrSnapshotRecent.__table__.columns}
    assert hyper == flat
