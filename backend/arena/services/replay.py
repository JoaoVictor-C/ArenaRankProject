"""Reprocessamento cronológico — o que sustenta a garantia de ordem.

O motor de rating é dependente de ORDEM (Plackett-Luce sequencial, sequências,
janela provisória, camada de cap PDL), mas a ingestão não é: a Riot lista ids do
mais novo para o mais antigo e os consumidores rodam 10–20 em paralelo. Pior,
partidas antigas continuam chegando para sempre — um jogador descoberto hoje
pode ter jogado há 15 dias, e o backfill de histórico existe justamente para
trazer esse passado.

Logo, ordem cronológica estrita NÃO é obtenível no momento da avaliação. O que é
obtenível — e é o que este módulo entrega — é um ladder cujo estado FINAL é
igual ao que o processamento estritamente cronológico teria produzido, através
de duas operações:

``drain_backlog``
    Modo refill: as partidas foram estacionadas em ``match_backlog`` sem serem
    avaliadas. Aqui elas são avaliadas UMA A UMA, em ordem
    ``(played_at, riot_match_id)``. Nunca em paralelo — o paralelismo é
    exatamente o que destrói a ordem.

``replay_from``
    Regime normal: uma partida atrasada foi avaliada fora de ordem e armou o
    ``replay_floor``. Aqui o estado derivado a partir daquele instante é
    descartado, cada jogador é restaurado ao seu ``state_before`` e a janela é
    reavaliada em ordem. Custo proporcional ao ATRASO, não ao tamanho da
    temporada.

Duas infidelidades do ``scripts/rerate_matches.py`` que precisaram ser
corrigidas aqui, porque um replay que não reproduz a ingestão ao vivo não vale
nada como garantia:

* ele não reconstruía ``is_premade``/``party_id`` (ambos PERSISTIDOS em
  ``match_participants``), então o amortecedor de premade sumia no replay e as
  notas saíam diferentes das da ingestão;
* ele deixava ``cr_snapshots`` ser carimbado com o relógio de processamento, o
  que colapsa a temporada inteira no instante do replay e quebra o delta7d.
  Aqui o ``RatingService`` é construído com ``snapshot_at_played=True``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from arena.core.config import settings
from arena.core.logging import get_logger
from arena.db import models as m
from arena.riot.arena import parsed_from_json
from arena.services import ingest_state
from arena.services.protocols import IntegrityVerdict, RawMatch, RawParticipant
from arena.services.rating_service import RatingService, apply_state_before

_log = get_logger("arena.services.replay")


class MissingRestorePointError(RuntimeError):
    """Uma partida na janela não tem ``state_before``, logo o replay incremental
    não pode restaurar o estado daquele instante.

    Acontece com linhas anteriores à migração 0014. Não é reparável por backfill
    (o estado histórico não existe em lugar nenhum) — o conserto é um rerate de
    temporada INTEIRA, que reescreve todas as linhas com snapshot.
    """


class _FixedIntegrity:
    """Verdict de integridade reconstruído dos fatos, não recalculado.

    O conjunto de inelegíveis é lido de ``match_participants.eligible``, que já
    registrou o veredito original. Recalcular integridade no replay usaria
    sinais de HOJE (fingerprints de lobby no Redis, que expiram) sobre partidas
    de semanas atrás e produziria um resultado diferente do da ingestão.
    """

    def __init__(self, ineligible: set[str]) -> None:
        self._ineligible = ineligible

    async def evaluate(self, match: RawMatch, states: object = None) -> IntegrityVerdict:
        return IntegrityVerdict(ineligible_player_ids=set(self._ineligible))


@asynccontextmanager
async def _no_lock(_ids: Any) -> Any:
    """Sem lock por jogador: o replay é single-threaded por construção."""
    yield


def _replay_service(ineligible: set[str]) -> RatingService:
    return RatingService(_FixedIntegrity(ineligible), snapshot_at_played=True)


# ---------------------------------------------------------------------------
# Reconstrução dos fatos imutáveis
# ---------------------------------------------------------------------------


async def rebuild_raw_matches(
    session: AsyncSession, season_id: str, *, since: datetime | None = None
) -> list[tuple[RawMatch, set[str]]]:
    """Reconstrói o conjunto de replay a partir de ``matches`` + ``match_participants``.

    Em ordem ``(played_at, riot_match_id)`` — a ordem cronológica canônica, com
    o id como desempate para tornar o replay determinístico entre execuções.
    Reconstrói ``is_premade``/``party_id`` (que o rerate antigo perdia).
    """
    conds = [m.Match.season_id == season_id]
    if since is not None:
        conds.append(m.Match.played_at >= since)
    match_rows = (
        await session.execute(
            select(
                m.Match.id,
                m.Match.riot_match_id,
                m.Match.mode,
                m.Match.queue_id,
                m.Match.played_at,
                m.Match.duration_seconds,
            )
            .where(*conds)
            .order_by(m.Match.played_at, m.Match.riot_match_id)
        )
    ).all()
    if not match_rows:
        return []

    # Uma consulta para TODOS os participantes da janela, agrupada em memória —
    # o rerate antigo fazia um SELECT por partida (71k round-trips).
    part_rows = (
        await session.execute(
            select(
                m.MatchParticipant.match_id,
                m.MatchParticipant.player_id,
                m.MatchParticipant.champion_id,
                m.MatchParticipant.team_id,
                m.MatchParticipant.placement,
                m.MatchParticipant.eligible,
                m.MatchParticipant.is_premade,
                m.MatchParticipant.party_id,
            ).where(m.MatchParticipant.match_id.in_([r.id for r in match_rows]))
        )
    ).all()
    by_match: dict[Any, list[Any]] = {}
    for p in part_rows:
        by_match.setdefault(p.match_id, []).append(p)

    out: list[tuple[RawMatch, set[str]]] = []
    for mr in match_rows:
        parts = by_match.get(mr.id)
        if not parts:
            continue
        out.append(
            (
                RawMatch(
                    match_id=str(mr.id),
                    riot_match_id=mr.riot_match_id,
                    season_id=season_id,
                    mode=mr.mode.value if hasattr(mr.mode, "value") else str(mr.mode),
                    queue_id=mr.queue_id,
                    played_at=mr.played_at.isoformat(),  # preserva o instante original
                    participants=[
                        RawParticipant(
                            player_id=str(p.player_id),
                            champion_id=p.champion_id,
                            team_id=p.team_id,
                            placement=p.placement,
                            is_premade=bool(p.is_premade),
                            party_id=p.party_id,
                        )
                        for p in parts
                    ],
                    duration_seconds=mr.duration_seconds,
                ),
                {str(p.player_id) for p in parts if p.eligible is False},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Restauração e limpeza
# ---------------------------------------------------------------------------


async def restore_states_at(
    session: AsyncSession, season_id: str, since: datetime
) -> int:
    """Rebobina ``player_seasons`` para o estado imediatamente anterior a ``since``.

    Para cada jogador com partida em ``>= since``, pega a MAIS ANTIGA dessas
    linhas e aplica o ``state_before`` dela. Jogadores sem nenhuma partida na
    janela ficam intocados — o estado deles já é final em relação ao corte.

    Levanta :class:`MissingRestorePointError` se alguma dessas linhas não tiver
    snapshot: restaurar pela metade é pior que recusar.
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT DISTINCT ON (mp.player_id)
                       mp.player_id, mp.state_before
                FROM match_participants mp
                JOIN matches mt ON mt.id = mp.match_id
                WHERE mt.season_id = :s AND mp.played_at >= :since
                ORDER BY mp.player_id, mp.played_at, mp.match_id
                """
            ),
            {"s": season_id, "since": since},
        )
    ).all()
    if not rows:
        return 0

    missing = [str(r.player_id) for r in rows if r.state_before is None]
    if missing:
        raise MissingRestorePointError(
            f"{len(missing)} jogador(es) sem state_before em >= {since.isoformat()} "
            f"(ex.: {missing[:3]}); rode um rerate de temporada inteira primeiro"
        )

    states = {
        str(ps.player_id): ps
        for ps in (
            await session.execute(
                select(m.PlayerSeason).where(
                    m.PlayerSeason.season_id == season_id,
                    m.PlayerSeason.player_id.in_([r.player_id for r in rows]),
                )
            )
        ).scalars()
    }
    restored = 0
    for r in rows:
        ps = states.get(str(r.player_id))
        if ps is None:
            continue
        apply_state_before(ps, r.state_before)
        restored += 1
    return restored


async def wipe_derived(
    session: AsyncSession, season_id: str, *, since: datetime | None = None
) -> None:
    """Descarta o estado DERIVADO da janela. Fatos (matches/players) ficam.

    ``champion_stats`` é apagado da temporada INTEIRA mesmo num replay
    incremental: é um acumulado sem dimensão temporal (e ``last10_placements`` é
    um array ordenado), então não dá para subtrair a contribuição da janela.
    :func:`rebuild_champion_stats` o reconstrói dos participantes no fim.
    """
    params: dict[str, Any] = {"s": season_id}
    by_played = ""
    by_snapshot = ""
    if since is not None:
        params["since"] = since
        by_played = " AND played_at >= :since"
        # cr_snapshots é carimbado com played_at no replay
        # (RatingService(snapshot_at_played=True)), então o mesmo corte vale —
        # é por isso que aquele flag existe: com o relógio de processamento não
        # haveria janela alguma para recortar aqui.
        by_snapshot = " AND snapshot_at >= :since"

    await session.execute(
        text(f"DELETE FROM cr_snapshots WHERE season_id=:s{by_snapshot}"), params
    )
    await session.execute(
        text(f"DELETE FROM cr_snapshots_recent WHERE season_id=:s{by_snapshot}"), params
    )
    await session.execute(
        text(
            "DELETE FROM match_participants WHERE match_id IN "
            f"(SELECT id FROM matches WHERE season_id=:s{by_played})"
        ),
        params,
    )
    await session.execute(text("DELETE FROM champion_stats WHERE season_id=:s"), {"s": season_id})
    await session.execute(
        text(
            f"UPDATE matches SET processed=false, processed_at=NULL "
            f"WHERE season_id=:s{by_played}"
        ),
        params,
    )
    if since is None:
        # Replay total: os jogadores voltam ao zero do motor.
        await session.execute(
            text("DELETE FROM player_seasons WHERE season_id=:s"), {"s": season_id}
        )


async def rebuild_champion_stats(session: AsyncSession, season_id: str) -> int:
    """Recompõe ``champion_stats`` a partir de ``match_participants``.

    Acumulado puramente derivado, então recomputar é exato e evita ter de
    subtrair a contribuição de uma janela (impossível para
    ``last10_placements``). ``wins`` é top-half CIENTE DO MODO — DUOS tem 8
    subteams (metade superior = placement <= 4), TRIOS tem 6 (<= 3) — espelhando
    ``rating.engine``; usar um limiar fixo inflaria TRIOS.

    Delete-then-insert: o próprio replay já faz upsert incremental de
    ``champion_stats`` ao reprocessar cada partida, então um INSERT puro bateria
    na unique (player, season, champion). E o passo é OBRIGATÓRIO num replay
    incremental — ``wipe_derived`` apaga a temporada inteira desta tabela (não dá
    para subtrair uma janela), então sem o recompute o acumulado ficaria só com a
    janela reprocessada.
    """
    await session.execute(
        text("DELETE FROM champion_stats WHERE season_id=:s"), {"s": season_id}
    )
    result = await session.execute(
        text(
            """
            INSERT INTO champion_stats (
                id, player_id, season_id, champion_id, matches_played, wins,
                top_half, total_placement_sum, cr_delta_sum, last10_placements
            )
            SELECT gen_random_uuid(), agg.player_id, :s, agg.champion_id,
                   agg.games, agg.wins, agg.wins, agg.place_sum, agg.cr_sum,
                   COALESCE(agg.last10, '{}')
            FROM (
                SELECT mp.player_id, mp.champion_id,
                       count(*) AS games,
                       count(*) FILTER (
                           WHERE mp.placement <= CASE WHEN mt.mode = 'DUOS' THEN 4 ELSE 3 END
                       ) AS wins,
                       sum(mp.placement) AS place_sum,
                       sum(mp.cr_delta) AS cr_sum,
                       (array_agg(mp.placement ORDER BY mp.played_at DESC))[1:10] AS last10
                FROM match_participants mp
                JOIN matches mt ON mt.id = mp.match_id
                WHERE mt.season_id = :s AND mp.eligible = true
                GROUP BY mp.player_id, mp.champion_id
            ) agg
            """
        ),
        {"s": season_id},
    )
    return int(getattr(result, "rowcount", 0) or 0)


# ---------------------------------------------------------------------------
# Operações públicas
# ---------------------------------------------------------------------------


async def replay_from(
    session: AsyncSession,
    season_id: str,
    *,
    since: datetime | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Reavalia a temporada em ordem cronológica a partir de ``since``.

    ``since=None`` => temporada inteira (o modo destrutivo do rerate). O caller
    commita. ``limit`` corta o conjunto para o tick não virar uma transação
    gigante; o piso continua armado e o próximo tick segue de onde parou.
    """
    replay_set = await rebuild_raw_matches(session, season_id, since=since)
    if not replay_set:
        return {"status": "empty", "matches": 0}

    # NÃO fatiamos a janela. Um replay é wipe-then-rebuild: reprocessar só um
    # prefixo enquanto se apaga a janela inteira deixaria o resto do estado
    # derivado destruído e não reescrito. Se a janela não cabe num tick, é caso
    # de rerate de temporada operado à mão, não de meio replay silencioso.
    cap = limit or settings.replay_max_matches_per_tick
    if len(replay_set) > cap:
        _log.warning(
            "replay.window_too_large",
            seasonId=season_id,
            since=since.isoformat() if since else None,
            matches=len(replay_set),
            cap=cap,
        )
        return {"status": "too_large", "matches": len(replay_set), "cap": cap}

    restored = await restore_states_at(session, season_id, since) if since else 0

    await wipe_derived(session, season_id, since=since)
    await session.flush()

    processed = 0
    for raw, ineligible in replay_set:
        outcome = await _replay_service(ineligible).process_match(session, _no_lock, raw)
        if outcome.status == "processed":
            processed += 1

    await session.flush()
    champ_rows = await rebuild_champion_stats(session, season_id)

    _log.info(
        "replay.done",
        seasonId=season_id,
        since=since.isoformat() if since else None,
        matches=len(replay_set),
        processed=processed,
        restored=restored,
        championStats=champ_rows,
    )
    return {
        "status": "ok",
        "matches": len(replay_set),
        "processed": processed,
        "restored": restored,
        "championStats": champ_rows,
    }


async def drain_backlog(
    session: AsyncSession,
    season_id: str,
    *,
    redis: Any = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Avalia o ``match_backlog`` em ordem cronológica estrita, uma por vez.

    Este é o caminho do refill. Deliberadamente serial: o paralelismo é
    exatamente o que destrói a ordem que estamos tentando garantir. Cada partida
    passa pelo MESMO ``WorkerRatingService`` da ingestão ao vivo, então registro,
    integridade e persistência ficam idênticos — o backlog só adia, nunca vira um
    segundo caminho de escrita.
    """
    from arena.services.match_pipeline import WorkerRatingService

    cap = limit or settings.replay_max_matches_per_tick
    rows = (
        await session.execute(
            select(m.MatchBacklog.riot_match_id, m.MatchBacklog.parsed)
            .where(m.MatchBacklog.season_id == season_id)
            .order_by(m.MatchBacklog.played_at, m.MatchBacklog.riot_match_id)
            .limit(cap)
        )
    ).all()
    if not rows:
        return {"status": "empty", "drained": 0}

    service = WorkerRatingService()
    drained = 0
    failed = 0
    for row in rows:
        parsed = parsed_from_json(row.parsed)
        try:
            # MESMO caminho de escrita da ingestão ao vivo (o parse já aconteceu
            # no estacionamento). ``allow_stage=False`` senão o gate re-estaciona
            # a partida que estamos drenando — laço infinito.
            await service.process_parsed(parsed, redis=redis, allow_stage=False)
            drained += 1
        except Exception:  # noqa: BLE001
            failed += 1
            _log.warning("replay.drain_failed", matchId=row.riot_match_id, exc_info=True)
            continue
        await session.execute(
            delete(m.MatchBacklog).where(
                m.MatchBacklog.riot_match_id == row.riot_match_id
            )
        )
    await session.commit()

    remaining = (
        await session.execute(
            select(m.MatchBacklog.riot_match_id)
            .where(m.MatchBacklog.season_id == season_id)
            .limit(1)
        )
    ).first()
    _log.info("replay.drained", seasonId=season_id, drained=drained, failed=failed)
    return {
        "status": "ok",
        "drained": drained,
        "failed": failed,
        "empty": remaining is None,
    }


__all__ = [
    "MissingRestorePointError",
    "rebuild_raw_matches",
    "restore_states_at",
    "wipe_derived",
    "rebuild_champion_stats",
    "replay_from",
    "drain_backlog",
    "ingest_state",
]
