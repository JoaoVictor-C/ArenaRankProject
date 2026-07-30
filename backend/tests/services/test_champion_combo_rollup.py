"""``champion_combo_stats`` — sinergias (duplas/trios) materializadas.

As três rotas ``/champions/synergy*`` faziam self-join de 2–3 vias sobre
``match_participants`` a cada request. Medido na temporada com 1,2M
participações: 8,0 s / 63,5M buffers / ~285 MB de spill para duplas, 19,1 s /
~530 MB para trios — pior que o scan que fazia o OOM killer derrubar a api, e
fora do circuit breaker do Caddy.

Aceites:

* **paridade** — o rollup reproduz o self-join exatamente, no piso de leitura,
  para size=2 e size=3;
* combos se formam UMA vez (cadeia ``c0 < c1 < c2``) — um trio {A,B,C} não pode
  aparecer nas 6 permutações;
* o sentinela ``c2 = 0`` distingue dupla de trio sem coluna anulável na PK;
* ``rebuild_champion_combos`` é idempotente e recompute a temporada INTEIRA
  (cumulativo — ao contrário de champion_daily_stats não dá para janelar);
* o piso de ESCRITA nunca pode subir acima do piso de LEITURA, senão a rota
  perde combos silenciosamente.

DB-gated: os agregados são SQL de Postgres (self-join sobre tabela particionada).
As invariantes puras rodam sempre.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.pool import NullPool

from arena.core.config import settings
from arena.services.stats_service import SYNERGY_MIN_GAMES, StatsService

# ---------------------------------------------------------------------------
# Invariante pura: a relação entre os dois pisos
# ---------------------------------------------------------------------------


def test_write_floor_stays_below_the_read_floor() -> None:
    """Piso de escrita >= piso de leitura => a rota perde combos que deveria mostrar.

    O rollup só guarda combos com ``games >= synergy_combo_min_games``. Se esse
    piso alcançar ``SYNERGY_MIN_GAMES`` (o piso que a rota aplica), combos
    legítimos somem sem erro nenhum — falha silenciosa, a pior espécie.
    """
    assert settings.synergy_combo_min_games < SYNERGY_MIN_GAMES
    assert settings.synergy_combo_min_games >= 1


# ---------------------------------------------------------------------------
# Daqui para baixo: Postgres real
# ---------------------------------------------------------------------------

_db = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="combo rollup tests need a migrated Postgres (set DATABASE_URL)",
)

DAY0 = datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)

#: Um trio fixo (A,B,C) repetido N vezes + uma dupla (A,B) extra, para que dupla
#: e trio tenham contagens DIFERENTES e um não possa mascarar o outro.
_A, _B, _C = 101, 202, 303
_TRIO_GAMES = 6
_EXTRA_PAIR_GAMES = 4


class _Fixture:
    def __init__(self) -> None:
        self.season_id = uuid.uuid4()
        # Um jogador por slot do subteam (UNIQUE (match_id, player_id)).
        self.players = [uuid.uuid4() for _ in range(3)]
        self.match_ids: list[uuid.UUID] = []

    async def add_team(
        self, session: Any, champions: list[int], placement: int, *, eligible: bool = True
    ) -> None:
        """Uma partida com UM subteam formado por ``champions``."""
        from sqlalchemy import text

        mid = uuid.uuid4()
        self.match_ids.append(mid)
        await session.execute(
            text(
                "INSERT INTO matches (id, riot_match_id, queue_id, mode, season_id, "
                "played_at, processed, integrity_flags, duration_seconds) "
                "VALUES (:id,:rid,1750,'TRIOS',:s,:p,true,'[]'::jsonb,600)"
            ),
            {"id": mid, "rid": f"C_{mid.hex[:12]}", "s": self.season_id, "p": DAY0},
        )
        for slot, champ in enumerate(champions):
            await session.execute(
                text(
                    "INSERT INTO match_participants (id,match_id,player_id,played_at,"
                    "champion_id,team_id,placement,eligible,cr_before,cr_after,cr_delta,"
                    "is_premade,modifiers) VALUES (:i,:m,:pl,:p,:c,1,:pc,:e,1000,1000,0,false,'{}'::jsonb)"
                ),
                {
                    "i": uuid.uuid4(), "m": mid, "pl": self.players[slot], "p": DAY0,
                    "c": champ, "pc": placement, "e": eligible,
                },
            )

    async def cleanup(self, session: Any) -> None:
        from sqlalchemy import text

        await session.execute(
            text("DELETE FROM champion_combo_stats WHERE season_id=:s"), {"s": self.season_id}
        )
        for mid in self.match_ids:
            await session.execute(
                text("DELETE FROM match_participants WHERE match_id=:m"), {"m": mid}
            )
            await session.execute(text("DELETE FROM matches WHERE id=:m"), {"m": mid})
        for pid in self.players:
            await session.execute(text("DELETE FROM players WHERE id=:p"), {"p": pid})
        await session.execute(text("DELETE FROM seasons WHERE id=:s"), {"s": self.season_id})
        await session.commit()


@asynccontextmanager
async def _seeded() -> AsyncIterator[tuple[Any, _Fixture]]:
    """Temporada descartável. Engine própria (ver test_champion_daily_rollup)."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    fx = _Fixture()
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        try:
            await session.execute(
                text(
                    "INSERT INTO seasons (id,name,queue_id,status,starts_at,ends_at,config) "
                    "VALUES (:id,:n,1750,'ENDED',:s,:e,'{}'::jsonb)"
                ),
                {
                    "id": fx.season_id, "n": f"combo-test-{fx.season_id.hex[:8]}",
                    "s": DAY0 - timedelta(days=30), "e": DAY0 + timedelta(days=30),
                },
            )
            for pid in fx.players:
                await session.execute(
                    text("INSERT INTO players (id,puuid) VALUES (:i,:p)"),
                    {"i": pid, "p": f"combo-test-{pid.hex}"},
                )
            # Trio (A,B,C): metade top-half, um 1º lugar.
            for i in range(_TRIO_GAMES):
                await fx.add_team(session, [_A, _B, _C], 1 if i == 0 else (3 if i % 2 else 5))
            # Dupla (A,B) sozinha: só engorda o par, nunca o trio.
            for _ in range(_EXTRA_PAIR_GAMES):
                await fx.add_team(session, [_A, _B], 2)
            # Time inelegível: não pode contar em lado nenhum.
            await fx.add_team(session, [_A, _B, _C], 1, eligible=False)
            await session.commit()
            yield session, fx
        finally:
            await session.rollback()
            await fx.cleanup(session)


async def _rebuild(session: Any, fx: _Fixture, floor: int = 1) -> int:
    n = await StatsService().rebuild_champion_combos(
        session, season_id=str(fx.season_id), min_games=floor
    )
    await session.commit()
    return n


def _combo(rows: list[Any], champions: tuple[int, ...]) -> Any:
    return next((r for r in rows if r.champions == champions), None)


# ---------------------------------------------------------------------------
# Paridade — o aceite decisivo
# ---------------------------------------------------------------------------


@_db
@pytest.mark.parametrize("size", [2, 3])
async def test_rollup_matches_the_live_self_join_exactly(size: int) -> None:
    """O rollup tem de reproduzir o self-join campo a campo, no piso de leitura."""
    async with _seeded() as (session, fx):
        svc = StatsService()
        sid = str(fx.season_id)
        live = await svc._champion_synergies_n_live(
            session, season_id=sid, size=size, min_games=1, limit=100
        )
        await _rebuild(session, fx)
        rolled = await svc.champion_synergies_n(
            session, season_id=sid, size=size, min_games=1, limit=100
        )
        assert {r.champions for r in live} == {r.champions for r in rolled}
        by_live = {r.champions: r for r in live}
        for r in rolled:
            assert r == by_live[r.champions], f"divergência em {r.champions}"


@_db
async def test_pair_and_trio_counts_are_independent() -> None:
    """A dupla (A,B) inclui as partidas do trio E as suas próprias; o trio, não.

    Se o self-join do rollup vazasse entre tamanhos, estes dois números
    colapsariam num só.
    """
    async with _seeded() as (session, fx):
        await _rebuild(session, fx)
        svc = StatsService()
        sid = str(fx.season_id)
        pairs = await svc.champion_synergies_n(session, season_id=sid, size=2, min_games=1)
        trios = await svc.champion_synergies_n(session, season_id=sid, size=3, min_games=1)

        ab = _combo(pairs, (_A, _B))
        abc = _combo(trios, (_A, _B, _C))
        assert ab is not None and abc is not None
        assert abc.games == _TRIO_GAMES
        assert ab.games == _TRIO_GAMES + _EXTRA_PAIR_GAMES


@_db
async def test_combo_forms_exactly_once_no_permutations() -> None:
    """{A,B,C} aparece uma vez, ordenado asc — nunca nas 6 permutações."""
    async with _seeded() as (session, fx):
        await _rebuild(session, fx)
        trios = await StatsService().champion_synergies_n(
            session, season_id=str(fx.season_id), size=3, min_games=1, limit=100
        )
        matching = [r for r in trios if set(r.champions) == {_A, _B, _C}]
        assert len(matching) == 1
        assert matching[0].champions == (_A, _B, _C)  # ordenado por championId asc


@_db
async def test_ineligible_participants_are_excluded() -> None:
    """Mesmo predicado ``eligible`` do scan cru — senão o rollup conta o que o rating não contou."""
    async with _seeded() as (session, fx):
        await _rebuild(session, fx)
        trios = await StatsService().champion_synergies_n(
            session, season_id=str(fx.season_id), size=3, min_games=1
        )
        abc = _combo(trios, (_A, _B, _C))
        assert abc is not None
        assert abc.games == _TRIO_GAMES  # o time inelegível não entrou


@_db
async def test_pairs_use_the_c2_sentinel_and_trios_do_not() -> None:
    """``c2 = 0`` marca "ausente" numa dupla (ids de campeão são positivos)."""
    from sqlalchemy import text

    async with _seeded() as (session, fx):
        await _rebuild(session, fx)
        rows = (
            await session.execute(
                text(
                    "SELECT size, count(*) FILTER (WHERE c2=0) z, count(*) n "
                    "FROM champion_combo_stats WHERE season_id=:s GROUP BY size ORDER BY size"
                ),
                {"s": fx.season_id},
            )
        ).all()
        by_size = {int(r.size): (int(r.z), int(r.n)) for r in rows}
        assert by_size[2][0] == by_size[2][1]  # toda dupla tem c2 = 0
        assert by_size[3][0] == 0  # nenhum trio tem c2 = 0


@_db
async def test_rebuild_is_idempotent() -> None:
    """Delete-then-insert da temporada inteira: rodar duas vezes converge."""
    from sqlalchemy import text

    async with _seeded() as (session, fx):
        q = text(
            "SELECT size,c0,c1,c2,games,top4,first_place,placement_sum "
            "FROM champion_combo_stats WHERE season_id=:s ORDER BY size,c0,c1,c2"
        )
        first = await _rebuild(session, fx)
        snap1 = (await session.execute(q, {"s": fx.season_id})).all()
        second = await _rebuild(session, fx)
        snap2 = (await session.execute(q, {"s": fx.season_id})).all()
        assert first == second
        assert snap1 == snap2 and snap1


@_db
async def test_write_floor_drops_the_tail() -> None:
    """O piso de escrita descarta combos raros — a razão de a tabela caber."""
    from sqlalchemy import text

    async with _seeded() as (session, fx):
        await _rebuild(session, fx, floor=1)
        low = (
            await session.execute(
                text("SELECT count(*) FROM champion_combo_stats WHERE season_id=:s"),
                {"s": fx.season_id},
            )
        ).scalar_one()
        # Piso acima do trio (6 jogos) mas abaixo da dupla (10): só a dupla fica.
        await _rebuild(session, fx, floor=_TRIO_GAMES + 1)
        high = (
            await session.execute(
                text("SELECT count(*) FROM champion_combo_stats WHERE season_id=:s"),
                {"s": fx.season_id},
            )
        ).scalar_one()
        assert high < low


@_db
async def test_read_floor_is_clamped_up_to_the_write_floor() -> None:
    """Pedir abaixo do piso de escrita não pode fingir que o rollup tem a cauda.

    As linhas não existem; devolver uma resposta "completa" seria mentira.
    """
    async with _seeded() as (session, fx):
        await _rebuild(session, fx, floor=_TRIO_GAMES + 1)  # trio fora do rollup
        trios = await StatsService().champion_synergies_n(
            session, season_id=str(fx.season_id), size=3, min_games=1
        )
        assert _combo(trios, (_A, _B, _C)) is None


@_db
async def test_empty_rollup_yields_empty_not_a_live_fallback() -> None:
    """Sem rollup as rotas devolvem vazio — nunca caem no self-join de 8–19 s."""
    async with _seeded() as (session, fx):
        svc = StatsService()
        sid = str(fx.season_id)
        assert await svc.champion_synergies_n(session, season_id=sid, size=2, min_games=1) == []
        assert await svc.champion_synergies_n(session, season_id=sid, size=3, min_games=1) == []
        assert await svc.champion_synergies(session, season_id=sid, min_games=1) == []


@_db
async def test_pair_route_dto_shape_is_preserved() -> None:
    """``champion_synergies`` continua devolvendo o DTO a/b antigo sobre o rollup."""
    async with _seeded() as (session, fx):
        await _rebuild(session, fx)
        pairs = await StatsService().champion_synergies(
            session, season_id=str(fx.season_id), min_games=1, limit=10
        )
        ab = next((p for p in pairs if (p.champion_a, p.champion_b) == (_A, _B)), None)
        assert ab is not None
        assert ab.champion_a < ab.champion_b  # ordenado por championId asc
        assert ab.games == _TRIO_GAMES + _EXTRA_PAIR_GAMES
