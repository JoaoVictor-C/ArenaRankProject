"""``champion_daily_stats`` — o rollup que serve a tierlist, o trend e o delta 7d.

Este rollup existe porque ``/champions`` reagregava ``match_participants`` a cada
request e empilhava memória até o OOM killer derrubar o container da api na
réplica t3.micro (incidente 28/07; a mitigação viva é um 503 no Caddy). Os
aceites cobertos:

* **paridade** — ``champion_tierlist`` (lê o rollup) e ``_champion_tierlist_live``
  (o scan cru que causou o incidente) devolvem linhas IDÊNTICAS sobre a mesma
  fixture. É a única prova real de que a materialização está correta e a
  condição para o 503 poder sair;
* ``rebuild_champion_daily`` é idempotente (delete-then-insert sobre a janela) e
  um dia CRESCE corretamente quando uma partida atrasada chega;
* o predicado ``eligible`` do rebuild bate com o do scan cru — se um lado
  divergir, a tierlist materializada conta partidas que o rating não contou;
* ``champion_trend`` degrada para série vazia sem histórico;
* ``_delta_pp`` devolve 0 quando qualquer das janelas está vazia.

DB-gated (Postgres real, mesma convenção de
``test_worker_rating_service_integration``): ``rebuild_champion_daily`` usa
``timezone('UTC', played_at)`` — bucketing UTC-explícito, deliberado, para bater
com o backfill da migração — e isso é SQL de Postgres. Emular ``timezone`` em
sqlite testaria uma query diferente da que roda em produção, então não vale.
Os testes de ``_delta_pp`` são puros e rodam sempre.

Cada teste cria a PRÓPRIA temporada descartável (UUID novo) e limpa tudo no fim,
então não depende do conteúdo ambiente do banco nem o suja.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.pool import NullPool

from arena.services.stats_service import StatsService, _delta_pp

# ---------------------------------------------------------------------------
# _delta_pp — puro, sem banco
# ---------------------------------------------------------------------------


def test_delta_pp_zero_when_either_window_is_empty() -> None:
    # Campeão que acabou de aparecer: sem janela anterior, sem seta.
    assert _delta_pp(5, 10, 0, 0) == 0
    # Campeão que sumiu: sem janela recente.
    assert _delta_pp(0, 0, 5, 10) == 0
    assert _delta_pp(0, 0, 0, 0) == 0


def test_delta_pp_signs_and_magnitude() -> None:
    assert _delta_pp(6, 10, 5, 10) == 10  # 60% vs 50%
    assert _delta_pp(4, 10, 5, 10) == -10  # 40% vs 50%
    assert _delta_pp(5, 10, 5, 10) == 0


def test_delta_pp_rounds_like_the_tierlist() -> None:
    """Arredonda cada taxa antes de subtrair, igual ao ``top4_rate`` da tierlist,
    para o delta reconciliar com o número exibido ao lado dele."""
    # 1/3 = 33.33% -> 33 ; 1/6 = 16.67% -> 17 ; 33 - 17 = 16
    assert _delta_pp(1, 3, 1, 6) == 16


# ---------------------------------------------------------------------------
# Daqui para baixo: Postgres real
# ---------------------------------------------------------------------------

_db = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="rollup tests need a migrated Postgres (set DATABASE_URL)",
)

DAY0 = datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)


#: Campeões usados pela fixture. Um JOGADOR distinto por campeão: como cada
#: campeão aparece no máximo uma vez por partida, isso satisfaz o UNIQUE
#: (match_id, player_id) de ``match_participants`` sem inventar lobbies inteiros.
_CHAMPS = (10, 20, 30, 40, 50)


class _Fixture:
    """Uma temporada descartável com partidas/participants controlados."""

    def __init__(self) -> None:
        self.season_id = uuid.uuid4()
        self.players: dict[int, uuid.UUID] = {c: uuid.uuid4() for c in _CHAMPS}
        self.match_ids: list[uuid.UUID] = []

    async def add_match(self, session: Any, day_offset: int, season: uuid.UUID | None = None) -> uuid.UUID:
        from sqlalchemy import text

        mid = uuid.uuid4()
        self.match_ids.append(mid)
        await session.execute(
            text(
                "INSERT INTO matches (id, riot_match_id, queue_id, mode, season_id, "
                "played_at, processed, integrity_flags, duration_seconds) "
                "VALUES (:id, :rid, 1750, 'TRIOS', :season, :played_at, true, '[]'::jsonb, 600)"
            ),
            {
                "id": mid,
                "rid": f"T_{mid.hex[:12]}",
                "season": season or self.season_id,
                "played_at": DAY0 - timedelta(days=day_offset),
            },
        )
        return mid

    async def add_part(
        self,
        session: Any,
        match_id: uuid.UUID,
        champion_id: int,
        placement: int,
        *,
        day_offset: int,
        eligible: bool = True,
    ) -> None:
        from sqlalchemy import text

        await session.execute(
            text(
                "INSERT INTO match_participants (id, match_id, player_id, played_at, "
                "champion_id, team_id, placement, eligible, cr_before, cr_after, "
                "cr_delta, is_premade, modifiers) "
                "VALUES (:id, :m, :p, :played_at, :champ, 1, :place, :elig, "
                "1000, 1000, 0, false, '{}'::jsonb)"
            ),
            {
                "id": uuid.uuid4(),
                "m": match_id,
                "p": self.players[champion_id],
                "played_at": DAY0 - timedelta(days=day_offset),
                "champ": champion_id,
                "place": placement,
                "elig": eligible,
            },
        )

    async def cleanup(self, session: Any) -> None:
        from sqlalchemy import text

        await session.execute(
            text("DELETE FROM champion_daily_stats WHERE season_id = :s"), {"s": self.season_id}
        )
        for mid in self.match_ids:
            await session.execute(
                text("DELETE FROM match_participants WHERE match_id = :m"), {"m": mid}
            )
            await session.execute(text("DELETE FROM matches WHERE id = :m"), {"m": mid})
        for pid in self.players.values():
            await session.execute(text("DELETE FROM players WHERE id = :p"), {"p": pid})
        await session.execute(
            text("DELETE FROM seasons WHERE id = :s"), {"s": self.season_id}
        )
        await session.commit()


@asynccontextmanager
async def _seeded() -> AsyncIterator[tuple[Any, _Fixture]]:
    """Temporada descartável + fixture carregada; sempre limpa no fim.

    Cobre de propósito: participants INELEGÍVEIS (não podem contar), um campeão
    abaixo do piso ``min_games`` e campeões espalhados por DIAS distintos — o
    rollup agrupa por dia e o scan cru não, então se a soma dos dias não
    reconstituir o total a paridade quebra.

    Engine PRÓPRIA por teste, deliberadamente: o sessionmaker cacheado de
    ``arena/db/session.py`` guarda uma engine amarrada ao event loop que a criou,
    e o pytest-asyncio dá um loop novo a cada teste — reusá-lo aqui explode com
    "Event loop is closed" no segundo teste do arquivo.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    fx = _Fixture()
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        try:
            # status ENDED de propósito: uma temporada de teste NUNCA pode ser
            # confundida com a corrente (o read path e os crons resolvem "a
            # corrente" por starts_at desc, e starts_at fica no passado).
            await session.execute(
                text(
                    "INSERT INTO seasons (id, name, queue_id, status, starts_at, ends_at, config) "
                    "VALUES (:id, :name, 1750, 'ENDED', :s, :e, '{}'::jsonb)"
                ),
                {
                    "id": fx.season_id,
                    "name": f"rollup-test-{fx.season_id.hex[:8]}",
                    "s": DAY0 - timedelta(days=30),
                    "e": DAY0 + timedelta(days=30),
                },
            )
            for pid in fx.players.values():
                await session.execute(
                    text("INSERT INTO players (id, puuid) VALUES (:id, :puuid)"),
                    {"id": pid, "puuid": f"rollup-test-{pid.hex}"},
                )

            m0 = await fx.add_match(session, 0)
            m1 = await fx.add_match(session, 0)
            m2 = await fx.add_match(session, 1)
            m3 = await fx.add_match(session, 2)
            m4 = await fx.add_match(session, 2)

            # champ 10: 5 jogos em 3 dias — 3 top4, 2 primeiros.
            await fx.add_part(session, m0, 10, 1, day_offset=0)
            await fx.add_part(session, m1, 10, 3, day_offset=0)
            await fx.add_part(session, m2, 10, 1, day_offset=1)
            await fx.add_part(session, m3, 10, 6, day_offset=2)
            await fx.add_part(session, m4, 10, 5, day_offset=2)
            # champ 20: 4 jogos, nenhum primeiro.
            await fx.add_part(session, m0, 20, 2, day_offset=0)
            await fx.add_part(session, m1, 20, 4, day_offset=0)
            await fx.add_part(session, m2, 20, 5, day_offset=1)
            await fx.add_part(session, m3, 20, 4, day_offset=2)
            # champ 30: 3 jogos, exatamente no piso.
            await fx.add_part(session, m0, 30, 1, day_offset=0)
            await fx.add_part(session, m2, 30, 2, day_offset=1)
            await fx.add_part(session, m4, 30, 6, day_offset=2)
            # champ 40: 2 jogos — ABAIXO do piso, fora dos dois lados.
            await fx.add_part(session, m0, 40, 1, day_offset=0)
            await fx.add_part(session, m1, 40, 1, day_offset=0)
            # champ 50: 4 participações TODAS inelegíveis — fora dos dois lados.
            await fx.add_part(session, m0, 50, 1, day_offset=0, eligible=False)
            await fx.add_part(session, m1, 50, 1, day_offset=0, eligible=False)
            await fx.add_part(session, m2, 50, 2, day_offset=1, eligible=False)
            await fx.add_part(session, m3, 50, 3, day_offset=2, eligible=False)
            await session.commit()

            yield session, fx
        finally:
            await session.rollback()
            await fx.cleanup(session)
            await engine.dispose()


async def _rebuild(session: Any, fx: _Fixture) -> int:
    rows = await StatsService().rebuild_champion_daily(
        session, season_id=str(fx.season_id), since=date(2000, 1, 1)
    )
    await session.commit()
    return rows


# ---------------------------------------------------------------------------
# Paridade — o aceite decisivo
# ---------------------------------------------------------------------------


@_db
async def test_rollup_tierlist_matches_live_scan_exactly() -> None:
    """A tierlist materializada tem de ser IDÊNTICA ao scan cru, campo a campo.

    Se esta falhar, o rollup não é uma otimização — é um número errado servido
    mais rápido, e o 503 do Caddy não pode sair.
    """
    async with _seeded() as (session, fx):
        svc = StatsService()
        sid = str(fx.season_id)

        live = await svc._champion_tierlist_live(session, season_id=sid)
        await _rebuild(session, fx)
        rolled = await svc.champion_tierlist(session, season_id=sid)

        by_live = {r.champion_id: r for r in live}
        by_rolled = {r.champion_id: r for r in rolled}

        assert by_live.keys() == by_rolled.keys()
        # Piso (40: 2 jogos) e elegibilidade (50) excluem os dois em AMBOS.
        assert set(by_live) == {10, 20, 30}
        for cid in by_live:
            assert by_live[cid] == by_rolled[cid], (
                f"divergência no campeão {cid}: live={by_live[cid]} rollup={by_rolled[cid]}"
            )


@_db
async def test_rollup_tierlist_is_season_scoped() -> None:
    """Uma partida de OUTRA temporada não pode entrar no total desta."""
    async with _seeded() as (session, fx):
        from sqlalchemy import text

        # Temporada vizinha com 3 jogos do champ 10 — não pode vazar.
        other = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO seasons (id, name, queue_id, status, starts_at, ends_at, config) "
                "VALUES (:id, :n, 1750, 'ENDED', :s, :e, '{}'::jsonb)"
            ),
            {
                "id": other,
                "n": f"rollup-other-{other.hex[:8]}",
                "s": DAY0 - timedelta(days=60),
                "e": DAY0 - timedelta(days=31),
            },
        )
        # Uma partida por participação: match_participants é UNIQUE
        # (match_id, player_id) e a fixture usa um jogador por campeão.
        others = []
        for place in (8, 7, 6):
            om = await fx.add_match(session, 0, season=other)
            others.append(om)
            await fx.add_part(session, om, 10, place, day_offset=0)
        await session.commit()

        try:
            await _rebuild(session, fx)
            rows = await StatsService().champion_tierlist(session, season_id=str(fx.season_id))
            champ10 = next(r for r in rows if r.champion_id == 10)
            assert champ10.games == 5  # os 3 da outra temporada ficam de fora
        finally:
            await session.execute(
                text("DELETE FROM champion_daily_stats WHERE season_id = :s"), {"s": other}
            )
            for om in others:
                await session.execute(
                    text("DELETE FROM match_participants WHERE match_id = :m"), {"m": om}
                )
                await session.execute(text("DELETE FROM matches WHERE id = :m"), {"m": om})
            await session.execute(text("DELETE FROM seasons WHERE id = :s"), {"s": other})
            await session.commit()


@_db
async def test_empty_rollup_yields_empty_tierlist_not_a_live_fallback() -> None:
    """Sem rollup a tierlist é vazia — NUNCA cai de volta no scan que causou o OOM."""
    async with _seeded() as (session, fx):
        # Nada de rebuild: o rollup está vazio embora haja partidas de sobra.
        assert await StatsService().champion_tierlist(session, season_id=str(fx.season_id)) == []


# ---------------------------------------------------------------------------
# rebuild_champion_daily
# ---------------------------------------------------------------------------


@_db
async def test_rebuild_is_idempotent() -> None:
    """Rodar duas vezes seguidas converge no mesmo conteúdo (delete-then-insert)."""
    from sqlalchemy import text

    async with _seeded() as (session, fx):
        q = text(
            "SELECT snapshot_date, champion_id, games, top4, first_place, placement_sum "
            "FROM champion_daily_stats WHERE season_id = :s "
            "ORDER BY snapshot_date, champion_id"
        )
        first = await _rebuild(session, fx)
        snap1 = (await session.execute(q, {"s": fx.season_id})).all()

        second = await _rebuild(session, fx)
        snap2 = (await session.execute(q, {"s": fx.season_id})).all()

        assert first == second
        assert snap1 == snap2
        assert snap1, "a fixture deve produzir linhas"


@_db
async def test_late_match_grows_its_day_on_the_next_rebuild() -> None:
    """Uma partida descoberta atrasada aumenta o total do SEU dia, sem duplicar.

    É o motivo de o rebuild ser delete-then-insert sobre uma janela em vez de um
    insert incremental: o sweep pode entregar uma partida horas depois.
    """
    from sqlalchemy import text

    async with _seeded() as (session, fx):
        await _rebuild(session, fx)
        q = text(
            "SELECT games FROM champion_daily_stats "
            "WHERE season_id = :s AND champion_id = 10 AND snapshot_date = :d"
        )
        params = {"s": fx.season_id, "d": DAY0.date()}
        before = (await session.execute(q, params)).scalar_one()

        late = await fx.add_match(session, 0)
        await fx.add_part(session, late, 10, 2, day_offset=0)
        await session.commit()

        await _rebuild(session, fx)
        after = (await session.execute(q, params)).scalar_one()
        assert after == before + 1


@_db
async def test_rebuild_excludes_ineligible_participants() -> None:
    """O predicado ``eligible`` do rebuild bate com o do scan cru.

    Se divergir, a tierlist materializada conta partidas que o rating não contou.
    """
    from sqlalchemy import text

    async with _seeded() as (session, fx):
        await _rebuild(session, fx)
        n = (
            await session.execute(
                text(
                    "SELECT count(*) FROM champion_daily_stats "
                    "WHERE season_id = :s AND champion_id = 50"
                ),
                {"s": fx.season_id},
            )
        ).scalar_one()
        assert n == 0


@_db
async def test_rebuild_window_leaves_older_days_untouched() -> None:
    """``since`` congela os dias anteriores — só a janela é recomputada.

    Confirma que ``champion_daily_window_days`` faz o que a config promete: um
    rebuild estreito não apaga o histórico que o backfill da migração escreveu.
    """
    from sqlalchemy import text

    async with _seeded() as (session, fx):
        await _rebuild(session, fx)
        older_day = (DAY0 - timedelta(days=2)).date()
        q = text(
            "SELECT count(*) FROM champion_daily_stats "
            "WHERE season_id = :s AND snapshot_date = :d"
        )
        before = (await session.execute(q, {"s": fx.season_id, "d": older_day})).scalar_one()
        assert before > 0

        # Janela que cobre apenas o dia mais recente.
        await StatsService().rebuild_champion_daily(
            session, season_id=str(fx.season_id), since=DAY0.date()
        )
        await session.commit()

        after = (await session.execute(q, {"s": fx.season_id, "d": older_day})).scalar_one()
        assert after == before


# ---------------------------------------------------------------------------
# champion_trend / champion_winrate_delta7d
# ---------------------------------------------------------------------------


@_db
async def test_trend_is_empty_without_rollup_history() -> None:
    """Sem histórico no rollup a série é vazia — a UI degrada os gráficos."""
    async with _seeded() as (session, fx):
        series = await StatsService().champion_trend(
            session, season_id=str(fx.season_id), champion_id=10, days=90
        )
        assert series == []


@_db
async def test_delta7d_is_zero_for_champions_without_both_windows() -> None:
    """A fixture inteira cai numa janela só → nenhum campeão tem base de comparação."""
    async with _seeded() as (session, fx):
        await _rebuild(session, fx)
        deltas = await StatsService().champion_winrate_delta7d(
            session, season_id=str(fx.season_id), champion_ids=[10, 20, 30]
        )
        assert all(v == 0 for v in deltas.values())


@_db
async def test_delta7d_empty_id_list_short_circuits() -> None:
    async with _seeded() as (session, fx):
        assert (
            await StatsService().champion_winrate_delta7d(
                session, season_id=str(fx.season_id), champion_ids=[]
            )
            == {}
        )
