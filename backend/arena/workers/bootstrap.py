"""Refill de temporada — semeadura e expansão da fronteira de descoberta.

A Riot NÃO tem endpoint de "todas as partidas da região": todo id de partida é
alcançado através de um puuid que já conhecemos. Com ``players`` vazio não existe
puuid nenhum, então a descoberta simplesmente nunca começa — é exatamente o
buraco que aparece ao abrir uma temporada com janela retroativa sobre uma base
zerada. Este módulo fecha esse buraco.

Cobertura total da REGIÃO é inalcançável por construção. O alvo honesto é
*100% das partidas dos jogadores alcançáveis a partir das sementes*, e o
mecanismo de alcance já existe no repositório — este módulo só o inicia e mede:

1. sementes (``settings.bootstrap_seed_riot_ids``) viram puuids via account-v1;
2. cada puuid vai para :func:`arena.workers.backfill.enqueue_backfill`, que já
   pagina o histórico até o corte da janela e empurra para a fila padrão;
3. cada lobby processado registra até 16 jogadores novos, e
   ``match_pipeline.register_players`` JÁ chama ``enqueue_backfill`` para eles —
   é essa a aresta viral, e ela não precisou de mudança nenhuma;
4. quando uma passada inteira não acrescenta jogador novo e nada está pendente,
   a fronteira **saturou**: acabou o que dava para alcançar.

Enquanto o refill roda a temporada fica em ``catching_up``, então nada é
avaliado na chegada — as partidas se acumulam em ``match_backlog`` e são
avaliadas depois em ordem cronológica estrita (``services/replay.py``). Só
quando a fronteira satura E o backlog esvazia a temporada passa a ``live``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from arena.core.config import settings
from arena.core.logging import get_logger
from arena.db import models as m
from arena.db.session import get_sessionmaker
from arena.services import ingest_state
from arena.workers import queues as Q
from arena.workers.backfill import enqueue_backfill

_log = get_logger("arena.workers.bootstrap")

#: Passadas consecutivas sem jogador novo E sem nada pendente antes de declarar
#: saturação. >1 porque uma passada pode cair numa janela em que o backfill
#: ainda não devolveu — declarar saturação cedo encerraria o refill no meio.
_SATURATION_STREAK = 3

#: Chave Redis do contador de passadas quietas (some com o Redis; no pior caso
#: a saturação demora mais alguns ticks a ser declarada).
_QUIET_KEY = "arena:bootstrap:quiet_passes"


def seed_riot_ids() -> list[tuple[str, str]]:
    """``settings.bootstrap_seed_riot_ids`` -> [(gameName, tagLine)].

    Entradas malformadas são descartadas com log em vez de derrubar o bootstrap:
    uma vírgula sobrando no env não pode impedir um refill.
    """
    out: list[tuple[str, str]] = []
    for chunk in settings.bootstrap_seed_riot_ids.split(","):
        raw = chunk.strip()
        if not raw:
            continue
        if "#" not in raw:
            _log.warning("bootstrap.bad_seed", value=raw, reason="sem '#'")
            continue
        name, _, tag = raw.partition("#")
        if not name.strip() or not tag.strip():
            _log.warning("bootstrap.bad_seed", value=raw, reason="nome ou tag vazio")
            continue
        out.append((name.strip(), tag.strip()))
    return out


async def resolve_seed_puuids() -> list[str]:
    """Resolve os Riot IDs de semente para puuids (account-v1)."""
    pairs = seed_riot_ids()
    if not pairs:
        return []
    from arena.riot import get_client

    # ``get_client`` devolve o adapter dos workers (list_match_ids/get_match), que
    # deliberadamente não expõe account-v1 — resolver Riot ID só acontece aqui.
    # Descemos para o RiotClient real por ``_real`` em vez de alargar o protocolo
    # dos workers por causa de um único chamador.
    client: Any = get_client()
    real: Any = getattr(client, "_real", client)
    puuids: list[str] = []
    for name, tag in pairs:
        try:
            account = await real.get_account_by_riot_id(
                name, tag, region=settings.bootstrap_seed_region
            )
        except Exception:  # noqa: BLE001
            _log.warning("bootstrap.seed_resolve_failed", riotId=f"{name}#{tag}", exc_info=True)
            continue
        puuid = (account or {}).get("puuid")
        if puuid:
            puuids.append(str(puuid))
        else:
            _log.warning("bootstrap.seed_no_puuid", riotId=f"{name}#{tag}")
    return puuids


async def start_bootstrap(redis: Any, season_id: str) -> dict[str, Any]:
    """Coloca a temporada em ``catching_up`` e injeta as sementes.

    Idempotente: re-executar só re-enfileira as sementes, e o
    ``BACKFILL_CLAIMED_SET`` já garante que um puuid não seja importado duas
    vezes — então retomar um refill interrompido é seguro.
    """
    if not settings.bootstrap_seed_riot_ids.strip():
        return {"status": "error", "reason": "no seeds configured"}

    puuids = await resolve_seed_puuids()
    if not puuids:
        return {"status": "error", "reason": "no seed resolved"}

    async with get_sessionmaker()() as session:
        await ingest_state.set_mode(session, season_id, m.IngestMode.catching_up)
        await ingest_state.update_progress(
            session, season_id, saturated_at=None, frontier_pending=len(puuids)
        )
        await session.commit()

    queued = await enqueue_backfill(redis, puuids)
    if redis is not None:
        try:
            await redis.delete(_QUIET_KEY)
        except Exception:  # noqa: BLE001
            pass
    _log.info("bootstrap.started", seasonId=season_id, seeds=len(puuids), queued=queued)
    return {"status": "ok", "seeds": len(puuids), "queued": queued}


async def stop_bootstrap(season_id: str) -> dict[str, Any]:
    """Volta a temporada para ``live`` sem esperar saturação (escape do operador).

    O backlog que já existe NÃO é descartado — o drenador continua esvaziando em
    ordem. Isto só para de estacionar partidas novas.
    """
    async with get_sessionmaker()() as session:
        await ingest_state.set_mode(session, season_id, m.IngestMode.live)
        await session.commit()
    _log.info("bootstrap.stopped", seasonId=season_id)
    return {"status": "ok"}


async def _counts(session: Any, season_id: str) -> tuple[int, int]:
    """(jogadores conhecidos, partidas ainda estacionadas)."""
    players = int(
        (await session.execute(select(func.count()).select_from(m.Player))).scalar_one()
    )
    staged = int(
        (
            await session.execute(
                select(func.count())
                .select_from(m.MatchBacklog)
                .where(m.MatchBacklog.season_id == season_id)
            )
        ).scalar_one()
    )
    return players, staged


async def bootstrap_tick(ctx: dict[str, Any]) -> dict[str, Any]:
    """Mede a fronteira e decide quando o refill acabou.

    "Saturado" = ``_SATURATION_STREAK`` passadas seguidas sem jogador NOVO e sem
    nada pendente no backfill. Aí a descoberta alcançou tudo que dava, e quando o
    backlog também esvaziar a temporada volta a ``live``.

    Só roda em ``catching_up`` — em regime normal não há fronteira a medir.
    """
    try:
        redis = ctx.get("redis")
        season_id = await _current_season()
        if season_id is None:
            return {"status": "skipped", "reason": "no season"}

        async with get_sessionmaker()() as session:
            if await ingest_state.get_mode(session, season_id) is not m.IngestMode.catching_up:
                return {"status": "skipped", "reason": "not catching up"}

            players, staged = await _counts(session, season_id)
            state = await ingest_state.get_state(session, season_id)
            previous = state.frontier_done if state else 0

            pending = 0
            if redis is not None:
                try:
                    pending = int(await redis.llen(Q.BACKFILL_PENDING_LIST) or 0)
                except Exception:  # noqa: BLE001
                    pending = 0

            grew = players > previous
            quiet = (not grew) and pending == 0

            passes = 0
            if redis is not None:
                try:
                    passes = int(await redis.incr(_QUIET_KEY)) if quiet else 0
                    if not quiet:
                        await redis.delete(_QUIET_KEY)
                except Exception:  # noqa: BLE001
                    passes = 0

            saturated = quiet and passes >= _SATURATION_STREAK
            fields: dict[str, Any] = {
                "frontier_done": players,
                "frontier_pending": pending,
            }
            if saturated and (state is None or state.saturated_at is None):
                fields["saturated_at"] = datetime.now(UTC)
            await ingest_state.update_progress(session, season_id, **fields)

            # Saturado E backlog vazio => o refill terminou de verdade.
            if saturated and staged == 0:
                await ingest_state.set_mode(session, season_id, m.IngestMode.live)
                await session.commit()
                _log.info("bootstrap.completed", seasonId=season_id, players=players)
                return {"status": "completed", "players": players}

            await session.commit()

        return {
            "status": "running",
            "players": players,
            "pending": pending,
            "staged": staged,
            "quietPasses": passes,
            "saturated": saturated,
        }
    except Exception:
        _log.warning("bootstrap.tick_failed", exc_info=True)
        return {"status": "error"}


async def _current_season() -> str | None:
    from arena.workers.scheduler import _current_season_id

    return await _current_season_id()


__all__ = [
    "seed_riot_ids",
    "resolve_seed_puuids",
    "start_bootstrap",
    "stop_bootstrap",
    "bootstrap_tick",
]
