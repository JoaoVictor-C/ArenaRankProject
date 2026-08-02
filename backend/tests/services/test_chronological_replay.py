"""Ordem cronológica — a propriedade pela qual todo o mecanismo de refill existe.

O motor de rating é dependente de ORDEM (Plackett-Luce sequencial, sequências,
janela provisória, camada de cap PDL), mas a ingestão não é: a Riot lista ids do
mais novo para o mais antigo e os consumidores rodam 10–20 em paralelo. Num
refill de 20 dias isso produz um ladder que reflete ordem de CHEGADA.

Ordem estrita no momento da avaliação é IMPOSSÍVEL — um jogador descoberto hoje
pode ter jogado há 15 dias, e é justamente isso que o backfill de histórico
traz. O que dá para garantir, e é o que estes testes travam, é que o estado
FINAL é igual ao que o processamento estritamente cronológico teria produzido:

* ``test_shuffled_ingestion_converges_to_chronological`` — ingerir embaralhado e
  depois reprocessar dá o MESMO ``player_seasons`` de ingerir em ordem. É o
  aceite decisivo;
* ``test_reverse_order_actually_diverges`` — o teste que dá sentido ao anterior:
  prova que a ordem MUDA o resultado. Sem ele, o teste de convergência poderia
  estar passando por o motor ser insensível à ordem;
* ``test_incremental_equals_full`` — o replay incremental a partir de um piso
  bate com o replay de temporada inteira;
* ``test_replay_refuses_without_restore_point`` — sem ``state_before`` o replay
  incremental RECUSA em vez de restaurar pela metade.

DB-gated: exercita o caminho de escrita real contra Postgres.
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

from arena.services import replay as replay_svc

_db = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="chronological replay tests need a migrated Postgres (set DATABASE_URL)",
)

DAY0 = datetime(2026, 5, 2, 12, 0, 0, tzinfo=UTC)
#: Estados comparados. ``cr`` é derivado de (mu, sigma), mas entra na comparação
#: de propósito: se a identidade CR quebrar num replay, isto pega.
_STATE_COLS = "mu, sigma, cr, current_streak, matches_played, placement_matches_remaining, peak_cr"


class _World:
    """Uma temporada descartável com jogadores e um roteiro de partidas."""

    def __init__(self, n_players: int = 8) -> None:
        self.season_id = uuid.uuid4()
        self.players = [uuid.uuid4() for _ in range(n_players)]
        self.puuids = [f"chrono-{p.hex}" for p in self.players]

    def payload(self, idx: int, day_offset: int, lineup: list[int], places: list[int]) -> dict:
        """Payload match-v5 sintético: 4 jogadores em 2 subteams de 2 (DUOS)."""
        parts = []
        for slot, (pi, place) in enumerate(zip(lineup, places, strict=True)):
            parts.append(
                {
                    "puuid": self.puuids[pi],
                    "riotIdGameName": self.puuids[pi],
                    "riotIdTagline": "BR1",
                    "championId": 10 + pi,
                    "playerSubteamId": 1 if slot < 2 else 2,
                    "subteamPlacement": place,
                    "profileIcon": 1,
                    "timePlayed": 900,
                    "gameEndedInEarlySurrender": False,
                }
            )
        return {
            # ID ÚNICO POR EXECUÇÃO. ``RatingService._already_processed`` procura
            # por ``riot_match_id`` SEM escopo de temporada (proposital: cobre
            # linhas de eras anteriores com id interno diferente), então um id
            # fixo faz qualquer resíduo de uma execução anterior — em QUALQUER
            # temporada — marcar a partida como já processada e o teste ingerir
            # silenciosamente menos partidas do que pediu.
            "metadata": {"matchId": f"BR1_CHRONO{self.season_id.hex[:10]}{idx:04d}"},
            "info": {
                "queueId": 1700,
                "gameDuration": 900,
                "gameStartTimestamp": int(
                    (DAY0 + timedelta(hours=day_offset)).timestamp() * 1000
                ),
                "participants": parts,
            },
        }

    def script(self) -> list[dict]:
        """12 partidas ao longo de 12 horas, com elencos sobrepostos.

        A sobreposição importa: se cada partida tivesse jogadores distintos, a
        ordem não mudaria nada e o teste não provaria coisa alguma.
        """
        rounds = [
            ([0, 1, 2, 3], [1, 1, 2, 2]),
            ([2, 3, 4, 5], [2, 2, 1, 1]),
            ([0, 4, 1, 5], [1, 1, 2, 2]),
            ([6, 7, 0, 2], [2, 2, 1, 1]),
            ([1, 3, 6, 7], [1, 1, 2, 2]),
            ([4, 6, 5, 7], [2, 2, 1, 1]),
            ([0, 5, 3, 6], [1, 1, 2, 2]),
            ([2, 7, 1, 4], [2, 2, 1, 1]),
            ([0, 3, 5, 7], [1, 1, 2, 2]),
            ([1, 2, 4, 6], [2, 2, 1, 1]),
            ([0, 6, 2, 5], [1, 1, 2, 2]),
            ([3, 4, 1, 7], [2, 2, 1, 1]),
        ]
        return [
            self.payload(i, i, lineup, places)
            for i, (lineup, places) in enumerate(rounds)
        ]

    async def seed(self, session: Any) -> None:
        # Status ENDED de propósito. Uma temporada de teste ACTIVE competiria com
        # a temporada real na resolução do caminho de escrita — e como o
        # resultado é CACHEADO, uma rajada inteira poderia ir para a temporada
        # errada. O teste fixa a resolução por monkeypatch (ver _pin_season).
        await session.execute(
            text(
                "INSERT INTO seasons (id,name,queue_id,status,starts_at,ends_at,config) "
                "VALUES (:id,:n,1700,'ENDED',:s,:e,'{}'::jsonb)"
            ),
            {
                "id": self.season_id,
                "n": f"chrono-{self.season_id.hex[:8]}",
                "s": DAY0 - timedelta(days=1),
                "e": DAY0 + timedelta(days=30),
            },
        )
        await session.commit()

    async def cleanup(self, session: Any) -> None:
        s = {"s": self.season_id}
        await session.execute(text("DELETE FROM cr_snapshots WHERE season_id=:s"), s)
        await session.execute(text("DELETE FROM cr_snapshots_recent WHERE season_id=:s"), s)
        await session.execute(text("DELETE FROM champion_stats WHERE season_id=:s"), s)
        await session.execute(
            text(
                "DELETE FROM integrity_events WHERE match_id IN "
                "(SELECT id FROM matches WHERE season_id=:s)"
            ),
            s,
        )
        await session.execute(
            text(
                "DELETE FROM match_participants WHERE match_id IN "
                "(SELECT id FROM matches WHERE season_id=:s)"
            ),
            s,
        )
        await session.execute(text("DELETE FROM player_seasons WHERE season_id=:s"), s)
        await session.execute(text("DELETE FROM matches WHERE season_id=:s"), s)
        await session.execute(text("DELETE FROM match_backlog WHERE season_id=:s"), s)
        await session.execute(text("DELETE FROM season_ingest_state WHERE season_id=:s"), s)
        # Por PUUID, não por id: ``register_players`` cunha o id da linha ele
        # mesmo, então os UUIDs de ``self.players`` nunca chegam a ser ids reais
        # — apagar por eles não removia nada. E escopado a ESTE mundo: um
        # `LIKE 'chrono-%'` apagaria os de outros mundos, batia na FK de
        # player_seasons deles e abortava a transação inteira (era assim que
        # temporadas de teste vazias ficavam para trás).
        await session.execute(
            text("DELETE FROM players WHERE puuid = ANY(:pp)"), {"pp": self.puuids}
        )
        await session.execute(text("DELETE FROM seasons WHERE id=:s"), s)
        await session.commit()


@asynccontextmanager
async def _world() -> AsyncIterator[tuple[Any, _World]]:
    """Engine própria por teste (o sessionmaker cacheado amarra o event loop)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import arena.services.match_pipeline as mp
    from arena.db import session as db_session

    # O caminho de escrita real usa o sessionmaker CACHEADO (lru_cache), cuja
    # engine fica amarrada ao event loop que a criou. O pytest-asyncio dá um loop
    # novo por teste, então sem limpar o cache o segundo teste do arquivo morre
    # com "Event loop is closed". dispose_engine() sozinho não basta: ele
    # descarta o pool mas o lru_cache devolveria a MESMA engine morta.
    db_session.get_engine.cache_clear()
    db_session.get_sessionmaker.cache_clear()

    w = _World()
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # PIN da temporada. Sem isto o caminho de escrita resolveria "a temporada
    # ativa" no banco de dev — a REAL — e o teste escreveria partidas sintéticas
    # nela. Já aconteceu; o cache de temporada torna a falha pegajosa.
    original = mp.resolve_active_season_id
    mp._season_cache.clear()

    async def _pinned(_session: Any) -> str:
        return str(w.season_id)

    mp.resolve_active_season_id = _pinned  # type: ignore[assignment]

    async with factory() as session:
        try:
            await w.seed(session)
            yield session, w
        finally:
            mp.resolve_active_season_id = original  # type: ignore[assignment]
            mp._season_cache.clear()
            await session.rollback()
            await w.cleanup(session)
            await engine.dispose()
            try:  # devolve a engine compartilhada antes de o loop fechar
                await db_session.dispose_engine()
            except Exception:  # noqa: BLE001 - teardown best-effort
                pass
            db_session.get_engine.cache_clear()
            db_session.get_sessionmaker.cache_clear()


async def _ingest(w: _World, payloads: list[dict], *, expect_all: bool = True) -> None:
    """Empurra payloads pelo caminho de escrita REAL, na ordem dada.

    ``expect_all`` guarda contra um modo de falha que já aconteceu e é
    INVISÍVEL: com ids de partida fixos, resíduo de uma execução anterior fazia
    o guard de idempotência devolver ``already_processed`` e o teste ingeria 4
    de 12 partidas — continuava "passando", só que exercitando um cenário muito
    mais fraco do que anunciava. Se o roteiro não entrar inteiro, falhe alto.
    """
    from arena.services.match_pipeline import WorkerRatingService

    svc = WorkerRatingService()
    statuses: list[str] = []
    for p in payloads:
        result = await svc.process_match(p["metadata"]["matchId"], p, redis=None)
        statuses.append(str(result.get("status")))
    if expect_all:
        processed = sum(1 for s in statuses if s == "processed")
        assert processed == len(payloads), (
            f"só {processed}/{len(payloads)} partidas entraram ({set(statuses)}) — "
            "o teste estaria medindo um roteiro mais fraco do que pensa"
        )


async def _final_state(session: Any, w: _World) -> dict[str, tuple]:
    rows = (
        await session.execute(
            text(
                f"SELECT player_id, {_STATE_COLS} FROM player_seasons "
                "WHERE season_id=:s ORDER BY player_id"
            ),
            {"s": w.season_id},
        )
    ).all()
    return {
        str(r.player_id): (
            round(r.mu, 9),
            round(r.sigma, 9),
            round(r.cr, 6),
            r.current_streak,
            r.matches_played,
            r.placement_matches_remaining,
            round(r.peak_cr, 6),
        )
        for r in rows
    }


# ---------------------------------------------------------------------------
# O aceite decisivo
# ---------------------------------------------------------------------------


@_db
async def test_reverse_order_actually_diverges() -> None:
    """A ordem MUDA o resultado — sem isto, o teste de convergência é vazio.

    Se este teste algum dia passar a falhar (ou seja, ordem deixar de importar),
    o mecanismo inteiro de backlog/replay perdeu a razão de existir.
    """
    async with _world() as (session, w):
        script = w.script()
        await _ingest(w, script)
        forward = await _final_state(session, w)

        await replay_svc.wipe_derived(session, str(w.season_id))
        await session.execute(text("DELETE FROM matches WHERE season_id=:s"), {"s": w.season_id})
        await session.commit()

        await _ingest(w, list(reversed(script)))
        backward = await _final_state(session, w)

        assert forward and backward
        assert forward != backward, (
            "ingerir em ordem inversa deu o MESMO estado — ou o motor virou "
            "insensível à ordem, ou a fixture não tem sobreposição de jogadores"
        )


@_db
async def test_shuffled_ingestion_converges_to_chronological() -> None:
    """Ingerir fora de ordem + replay == ingerir em ordem cronológica.

    Esta é a garantia que o refill vende: o estado FINAL é o que o
    processamento estritamente cronológico teria produzido.
    """
    async with _world() as (session, w):
        script = w.script()

        # 1) Referência: ingestão em ordem cronológica.
        await _ingest(w, script)
        chronological = await _final_state(session, w)

        # 2) Zera e ingere na ordem RUIM (a que a Riot+paralelismo produzem).
        await replay_svc.wipe_derived(session, str(w.season_id))
        await session.execute(text("DELETE FROM matches WHERE season_id=:s"), {"s": w.season_id})
        await session.commit()
        await _ingest(w, list(reversed(script)))
        assert await _final_state(session, w) != chronological  # de fato divergiu

        # 3) Replay de temporada inteira -> tem de convergir.
        result = await replay_svc.replay_from(session, str(w.season_id), since=None)
        await session.commit()
        assert result["status"] == "ok", result
        assert await _final_state(session, w) == chronological


@_db
async def test_incremental_equals_full() -> None:
    """Replay incremental a partir de um piso == replay de temporada inteira."""
    async with _world() as (session, w):
        script = w.script()
        await _ingest(w, script)

        full = await replay_svc.replay_from(session, str(w.season_id), since=None)
        await session.commit()
        assert full["status"] == "ok"
        expected = await _final_state(session, w)

        # Piso no meio da temporada; o incremental restaura de state_before.
        floor = DAY0 + timedelta(hours=5)
        inc = await replay_svc.replay_from(session, str(w.season_id), since=floor)
        await session.commit()
        assert inc["status"] == "ok", inc
        assert inc["matches"] < len(script), "o incremental tem de ser um subconjunto"
        assert inc["restored"] > 0, "nenhum jogador restaurado de state_before"

        assert await _final_state(session, w) == expected


@_db
async def test_replay_refuses_without_restore_point() -> None:
    """Sem ``state_before`` o incremental RECUSA — restaurar pela metade é pior."""
    async with _world() as (session, w):
        await _ingest(w, w.script())
        # Simula linhas anteriores à migração 0014.
        await session.execute(
            text(
                "UPDATE match_participants SET state_before=NULL WHERE match_id IN "
                "(SELECT id FROM matches WHERE season_id=:s)"
            ),
            {"s": w.season_id},
        )
        await session.commit()

        with pytest.raises(replay_svc.MissingRestorePointError):
            await replay_svc.replay_from(
                session, str(w.season_id), since=DAY0 + timedelta(hours=5)
            )


@_db
async def test_state_before_is_written_for_every_participant() -> None:
    """Todo participante vira ponto de restauração — senão o incremental trava."""
    async with _world() as (session, w):
        await _ingest(w, w.script())
        row = (
            await session.execute(
                text(
                    "SELECT count(*) total, count(state_before) with_state "
                    "FROM match_participants WHERE match_id IN "
                    "(SELECT id FROM matches WHERE season_id=:s)"
                ),
                {"s": w.season_id},
            )
        ).one()
        assert row.total > 0
        assert row.with_state == row.total

        keys = (
            await session.execute(
                text(
                    "SELECT state_before FROM match_participants WHERE match_id IN "
                    "(SELECT id FROM matches WHERE season_id=:s) LIMIT 1"
                ),
                {"s": w.season_id},
            )
        ).scalar_one()
        assert set(keys) == {
            "mu",
            "sigma",
            "current_streak",
            "matches_played",
            "placement_matches_remaining",
            "peak_cr",
        }
