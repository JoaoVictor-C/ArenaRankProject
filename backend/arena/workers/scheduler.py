"""Scheduler — arq cron jobs (proposal section 13.3 + 6.3 scheduler role).

Periodic maintenance, each a thin coroutine that delegates the real work to the
Wave-2 service layer and stays import-safe before those services exist:

* :func:`season_transition` — drive ``ACTIVE→SOFT_LOCK→ENDED`` and run the new
  season's soft-reset at ``starts_at`` (proposal section 13.3). Delegates to
  ``arena.services.season_service``.
* :func:`leaderboard_refresh` — refresh the leaderboard read model and the
  Redis ``Top-1000`` set that ingestion uses for priority classification
  (proposal sections 3.4 / 13.1). Delegates to
  ``arena.services.leaderboard_service``.
* :func:`cache_warm` — pre-warm hot read caches (top players, recent matches)
  so the public API stays sub-100ms (proposal section 9.2).
* :func:`cr_snapshot_maintenance` — maintain the ``cr_snapshots`` Timescale
  continuous aggregate / compression / retention (Trinity #4, proposal
  section 8.3): refresh the aggregate window and drop/compress aged chunks.
* :func:`champion_daily_maintenance` — recompute the recent window of the
  ``champion_daily_stats`` rollup. This rollup is what the ``/champions``
  tierlist, the 7d winrate delta and the trend charts read INSTEAD of
  re-aggregating ``match_participants`` per request; without this tick it only
  ever holds the migration's one-shot backfill and goes stale immediately.
* :func:`season_records_maintenance` — recompute ``season_record_cache``, the
  materialized result behind ``/meta/records`` (same rationale: the live
  computation groups every eligible participant in the season by player).
* :func:`heartbeat_tick` — stamps a liveness timestamp every tick and, when it
  finds the PREVIOUS stamp older than ``settings.reconcile_gap_threshold_seconds``
  (i.e. this process was down or unable to tick for a while), opens a
  reconciliation window that :func:`arena.workers.sweep.reconcile_tick` picks
  up to run one bounded, time-windowed catch-up sweep. This is what lets an
  outage self-heal without an operator manually running a backfill.

The :data:`CRON_JOBS` list is consumed by :mod:`arena.workers.main`. Schedules
use arq's cron spec (``hour``/``minute``/``second`` sets, or ``second={...}``
for sub-minute cadence).
"""

from __future__ import annotations

import time
from typing import Any

from arq import cron

from arena.core.config import settings
from arena.core.logging import get_logger
from arena.workers import queues as Q
from arena.workers.bootstrap import bootstrap_tick

_log = get_logger("arena.workers.scheduler")


# ---------------------------------------------------------------------------
# Cron coroutines
# ---------------------------------------------------------------------------


async def season_transition(ctx: dict[str, Any]) -> dict[str, Any]:
    """Advance season lifecycle + run due soft-resets (proposal section 13.3).

    Idempotent by design: the season service only acts on seasons whose clock
    has actually crossed a boundary, so running every few minutes is safe.
    """
    try:
        from arena.services.season_service import (  # type: ignore[attr-defined]
            get_season_service,
        )
    except Exception:
        _log.info("scheduler.season_transition.skipped", reason="season_service unavailable (W2)")
        return {"status": "skipped"}

    service = get_season_service()
    result: dict[str, Any] = await service.run_transitions()
    _log.info("scheduler.season_transition.done", **result)
    return result


async def leaderboard_refresh(ctx: dict[str, Any]) -> dict[str, Any]:
    """Refresh the leaderboard read model + Redis Top-1000 set (§3.4 / §13.1).

    The Top-1000 set is the priority-classification source ingestion reads, so
    this job closes the loop between rating writes and the priority lane.
    """
    redis: Any = ctx["redis"]
    try:
        from arena.services.leaderboard_service import (  # type: ignore[attr-defined]
            get_leaderboard_service,
        )
    except Exception:
        _log.info(
            "scheduler.leaderboard_refresh.skipped",
            reason="leaderboard_service unavailable (W2)",
        )
        return {"status": "skipped"}

    service = get_leaderboard_service()
    result: dict[str, Any] = await service.refresh(redis=redis)
    _log.info("scheduler.leaderboard_refresh.done", **result)
    return result


async def cache_warm(ctx: dict[str, Any]) -> dict[str, Any]:
    """Pre-warm hot read caches so public reads stay fast (proposal §9.2)."""
    redis: Any = ctx["redis"]
    try:
        from arena.services.leaderboard_service import (  # type: ignore[attr-defined]
            get_leaderboard_service,
        )
    except Exception:
        _log.info("scheduler.cache_warm.skipped", reason="services unavailable (W2)")
        return {"status": "skipped"}

    service = get_leaderboard_service()
    warm = getattr(service, "warm_cache", None)
    if warm is None:
        return {"status": "skipped", "reason": "no warm_cache"}
    result: dict[str, Any] = await warm(redis=redis)
    _log.info("scheduler.cache_warm.done", **result)
    return result


async def cr_snapshot_maintenance(ctx: dict[str, Any]) -> dict[str, Any]:
    """Maintain the ``cr_snapshots`` continuous aggregate (Trinity #4 / §8.3).

    Refreshes the Timescale continuous aggregate over the recent window and
    applies compression/retention to aged chunks. Delegates to the season
    service's maintenance hook (it owns the snapshot schema); no-ops until W2.

    T2.3: também mantém a janela do espelho plano ``cr_snapshots_recent``
    (dual-write do RatingService): purge das linhas de temporadas que não são
    mais a corrente, para a tabela replicada não crescer para sempre.
    """
    purged = await _purge_cr_snapshots_recent()

    try:
        from arena.services.season_service import (  # type: ignore[attr-defined]
            get_season_service,
        )
    except Exception:
        _log.info(
            "scheduler.cr_snapshot_maintenance.skipped",
            reason="season_service unavailable (W2)",
            recent_purged=purged,
        )
        return {"status": "skipped", "recentPurged": purged}

    service = get_season_service()
    maintain = getattr(service, "maintain_cr_snapshots", None)
    if maintain is None:
        return {"status": "skipped", "reason": "no maintain_cr_snapshots", "recentPurged": purged}
    result: dict[str, Any] = await maintain()
    result["recentPurged"] = purged
    _log.info("scheduler.cr_snapshot_maintenance.done", **result)
    return result


async def champion_daily_maintenance(ctx: dict[str, Any]) -> dict[str, Any]:
    """Recompute the recent window of the ``champion_daily_stats`` rollup.

    The rollup is the read path's source for the ``/champions`` tierlist, the 7d
    winrate delta and the per-champion trend series — all of which used to
    re-aggregate ``match_participants`` on every request until that stacked enough
    memory to get the API container OOM-killed on the t3.micro replica. The
    migration seeds history once; THIS tick is what keeps it current.

    ``rebuild_champion_daily`` is delete-then-insert over the window, so re-running
    is idempotent and a day's totals grow correctly as late matches land. The
    window (``settings.champion_daily_window_days``) covers the sweep's catch-up
    lag. Runs on the PRIMARY; the write replicates to the replica via ``arena_read``.

    Best-effort: a DB blip logs and returns rather than killing the tick — the next
    hour tries again.
    """
    try:
        from datetime import UTC, datetime, timedelta

        from arena.db.session import get_sessionmaker
        from arena.services.stats_service import StatsService

        season_id = await _current_season_id()
        if season_id is None:
            _log.info("scheduler.champion_daily.skipped", reason="no season")
            return {"status": "skipped", "reason": "no season"}

        since = (datetime.now(UTC) - timedelta(days=settings.champion_daily_window_days)).date()
        async with get_sessionmaker()() as session:
            rows = await StatsService().rebuild_champion_daily(
                session, season_id=season_id, since=since
            )
            await session.commit()
        _log.info(
            "scheduler.champion_daily.done", rows=rows, since=since.isoformat(), season=season_id
        )
        return {"status": "ok", "rows": rows, "since": since.isoformat()}
    except Exception:
        _log.warning("scheduler.champion_daily.failed", exc_info=True)
        return {"status": "error"}


async def champion_combo_maintenance(ctx: dict[str, Any]) -> dict[str, Any]:
    """Recompute ``champion_combo_stats`` — the materialized synergy rollup.

    Backs ``/champions/synergy``, ``/champions/synergy/groups`` and
    ``/champions/synergy/tierlist``. Those used to self-join
    ``match_participants`` 2–3 ways per request: 8 s / ~285 MB of temp spill for
    pairs, 19 s / ~530 MB for trios — worse than the scan that OOM-killed the API
    container, and outside the Caddy breaker that shielded the other two routes.

    The heaviest cron in the scheduler, and the only rollup that CANNOT be
    windowed (it is cumulative per season, so a partial recompute yields wrong
    totals). Hourly, off-peak minute, well away from the other maintenance ticks.

    Best-effort, same contract as :func:`champion_daily_maintenance`.
    """
    try:
        from arena.db.session import get_sessionmaker
        from arena.services.stats_service import StatsService

        season_id = await _current_season_id()
        if season_id is None:
            _log.info("scheduler.champion_combo.skipped", reason="no season")
            return {"status": "skipped", "reason": "no season"}

        async with get_sessionmaker()() as session:
            rows = await StatsService().rebuild_champion_combos(session, season_id=season_id)
            await session.commit()
        _log.info("scheduler.champion_combo.done", rows=rows, season=season_id)
        return {"status": "ok", "rows": rows}
    except Exception:
        _log.warning("scheduler.champion_combo.failed", exc_info=True)
        return {"status": "error"}


async def champion_versus_maintenance(ctx: dict[str, Any]) -> dict[str, Any]:
    """Recompute ``champion_versus_stats`` — the cross-subteam matchup rollup.

    Backs ``/champions/{id}/matchups?kind=versus``. NOT a SQL self-join (see
    :meth:`StatsService.rebuild_champion_versus`'s docstring — a cross-subteam
    self-join across ``matches``'/``match_participants``' incompatible
    partition schemes plans in the BILLIONS of estimated rows); instead one
    plain participant scan aggregated in Python. Measured live: ~19s for the
    full season. Same cumulative-per-season shape as the other rollups in
    this series (cannot be windowed), so it gets its own off-peak hourly
    minute, away from combo/build/daily/records.

    Best-effort, same contract as :func:`champion_daily_maintenance`.
    """
    try:
        from arena.db.session import get_sessionmaker
        from arena.services.stats_service import StatsService

        season_id = await _current_season_id()
        if season_id is None:
            _log.info("scheduler.champion_versus.skipped", reason="no season")
            return {"status": "skipped", "reason": "no season"}

        async with get_sessionmaker()() as session:
            rows = await StatsService().rebuild_champion_versus(session, season_id=season_id)
            await session.commit()
        _log.info("scheduler.champion_versus.done", rows=rows, season=season_id)
        return {"status": "ok", "rows": rows}
    except Exception:
        _log.warning("scheduler.champion_versus.failed", exc_info=True)
        return {"status": "error"}


async def champion_build_variant_maintenance(ctx: dict[str, Any]) -> dict[str, Any]:
    """Recompute ``champion_build_variant_stats`` — build variants by prismatic
    augment (the ``/campeao`` "BUILDS DE {campeão} por tier" panel).

    Needs the current prismatic-augment id set from ``BuildRefService``
    (HTTP-cached CDragon catalog, 12h TTL) to know which of each participant's
    3 draft picks is the round-3 (build-defining) one — not something SQL can
    derive on its own, so this fetches that first, then delegates to
    :meth:`StatsService.rebuild_champion_build_variants` (same Python-
    aggregation shape as :func:`champion_versus_maintenance`, same reasoning).

    Best-effort, same contract as :func:`champion_daily_maintenance`.
    """
    try:
        from arena.db.session import get_sessionmaker
        from arena.services.build_ref_service import get_build_ref_service
        from arena.services.stats_service import StatsService

        season_id = await _current_season_id()
        if season_id is None:
            _log.info("scheduler.champion_build_variant.skipped", reason="no season")
            return {"status": "skipped", "reason": "no season"}

        catalog = await get_build_ref_service().augment_catalog()
        prismatic_ids = {e.id for e in catalog if e.rarity == "prismatic"}
        if not prismatic_ids:
            _log.info("scheduler.champion_build_variant.skipped", reason="no prismatic augments")
            return {"status": "skipped", "reason": "no prismatic augments"}

        async with get_sessionmaker()() as session:
            rows = await StatsService().rebuild_champion_build_variants(
                session, season_id=season_id, prismatic_augment_ids=prismatic_ids
            )
            await session.commit()
        _log.info("scheduler.champion_build_variant.done", rows=rows, season=season_id)
        return {"status": "ok", "rows": rows}
    except Exception:
        _log.warning("scheduler.champion_build_variant.failed", exc_info=True)
        return {"status": "error"}


async def champion_build_stats_maintenance(ctx: dict[str, Any]) -> dict[str, Any]:
    """Recompute ``champion_build_stats`` — the NATIVE augment/item rollup.

    Backs the ``/winrate`` "Build recomendada" panel, the "Augments em alta"
    rail, and the augment catalog's tier/champions fields — replacing
    ``champion_build_ref`` (an external third-party aggregate; see
    ``build_ref_service.py``'s module docstring). Same cumulative-per-season
    shape as :func:`champion_combo_maintenance` (unnest over an ARRAY column
    instead of a self-join, but no windowing either way), so it gets its own
    off-peak hourly minute.

    Best-effort, same contract as :func:`champion_daily_maintenance`.
    """
    try:
        from arena.db.session import get_sessionmaker
        from arena.services.stats_service import StatsService

        season_id = await _current_season_id()
        if season_id is None:
            _log.info("scheduler.champion_build_stats.skipped", reason="no season")
            return {"status": "skipped", "reason": "no season"}

        async with get_sessionmaker()() as session:
            rows = await StatsService().rebuild_champion_build_stats(session, season_id=season_id)
            await session.commit()
        _log.info("scheduler.champion_build_stats.done", rows=rows, season=season_id)
        return {"status": "ok", "rows": rows}
    except Exception:
        _log.warning("scheduler.champion_build_stats.failed", exc_info=True)
        return {"status": "error"}


async def season_records_maintenance(ctx: dict[str, Any]) -> dict[str, Any]:
    """Recompute ``season_record_cache`` — the materialized ``/meta/records``.

    The live computation groups every eligible participant in the season by player
    (~127k rows materialized) and sorts ``cr_delta`` without an index; it was the
    second route the OOM killer took down. Hourly is the right cadence: the only
    time-sensitive record is "Mais partidas hoje", and an hour of staleness on a
    rotating highlight card is invisible.

    Best-effort, same contract as :func:`champion_daily_maintenance`.
    """
    try:
        from arena.db.session import get_sessionmaker
        from arena.services.stats_service import StatsService

        season_id = await _current_season_id()
        if season_id is None:
            _log.info("scheduler.season_records.skipped", reason="no season")
            return {"status": "skipped", "reason": "no season"}

        async with get_sessionmaker()() as session:
            rows = await StatsService().rebuild_season_records(session, season_id=season_id)
            await session.commit()
        _log.info("scheduler.season_records.done", rows=rows, season=season_id)
        return {"status": "ok", "rows": rows}
    except Exception:
        _log.warning("scheduler.season_records.failed", exc_info=True)
        return {"status": "error"}


async def backlog_drain_tick(ctx: dict[str, Any]) -> dict[str, Any]:
    """Avalia o ``match_backlog`` da temporada em ordem cronológica estrita.

    Só faz algo quando a temporada está em ``catching_up`` (refill). Serial por
    construção — o paralelismo dos consumidores é exatamente o que destrói a
    ordem que o backlog existe para garantir, então drenar em paralelo anularia
    todo o mecanismo.

    Ao esvaziar, a temporada NÃO vira ``live`` automaticamente: a saturação da
    fronteira de descoberta é quem decide isso (ver ``workers/bootstrap.py``).
    Um backlog vazio só significa "nada estacionado neste instante", e a
    descoberta pode muito bem estar a meio caminho.

    Drena INDEPENDENTE do modo. O modo decide se partidas NOVAS são estacionadas;
    o que já está estacionado tem de ser avaliado de qualquer forma. Havia um
    ``skip`` quando o modo não era ``catching_up``, e ele encalhava o backlog
    para sempre no instante em que o operador encerrava o refill — 215 partidas
    descobertas ficavam paradas sem nunca virar rating, exatamente o oposto do
    que ``stop_bootstrap`` promete ("o drenador continua esvaziando em ordem").
    """
    try:
        from arena.db.session import get_sessionmaker
        from arena.services import replay

        season_id = await _current_season_id()
        if season_id is None:
            return {"status": "skipped", "reason": "no season"}

        async with get_sessionmaker()() as session:
            result = await replay.drain_backlog(
                session, season_id, redis=ctx.get("redis")
            )
        if result.get("drained"):
            _log.info("scheduler.backlog_drain.done", **result)
        return result
    except Exception:
        _log.warning("scheduler.backlog_drain.failed", exc_info=True)
        return {"status": "error"}


async def rating_replay_tick(ctx: dict[str, Any]) -> dict[str, Any]:
    """Consome o ``replay_floor``: reavalia a cauda que chegou fora de ordem.

    O piso é armado pelo caminho de escrita quando uma partida é avaliada com um
    ``played_at`` anterior ao que a temporada já processou — coisa que acontece o
    tempo todo, porque todo jogador recém-descoberto traz histórico antigo.
    Reprocessar por partida seria thrashing permanente; por isso o piso acumula e
    só é consumido aqui, e só quando as filas estão paradas: reprocessar enquanto
    a ingestão ainda despeja passado apenas reabriria o piso em seguida.
    """
    try:
        from arena.db.session import get_sessionmaker
        from arena.services import ingest_state, replay
        from arena.workers.ingestion import _combined_queue_depth

        redis = ctx.get("redis")
        if redis is not None and await _combined_queue_depth(redis) > 0:
            return {"status": "skipped", "reason": "queues busy"}

        season_id = await _current_season_id()
        if season_id is None:
            return {"status": "skipped", "reason": "no season"}

        async with get_sessionmaker()() as session:
            state = await ingest_state.get_state(session, season_id)
            floor = state.replay_floor if state else None
            if floor is None:
                return {"status": "skipped", "reason": "no floor"}

            try:
                result = await replay.replay_from(session, season_id, since=floor)
            except replay.MissingRestorePointError as exc:
                # Linhas anteriores à migração 0014 não têm ponto de restauração,
                # e isso não é reparável automaticamente. Deixa o piso armado e
                # grita: o conserto é um rerate de temporada inteira, decisão de
                # operador (é destrutivo), não de cron.
                _log.error(
                    "scheduler.replay.needs_full_rerate",
                    seasonId=season_id,
                    floor=floor.isoformat(),
                    reason=str(exc),
                )
                return {"status": "blocked", "reason": "missing restore point"}

            if result.get("status") == "ok":
                await ingest_state.clear_replay_floor(session, season_id)
            await session.commit()

        _log.info("scheduler.replay.done", seasonId=season_id, **result)
        return result
    except Exception:
        _log.warning("scheduler.replay.failed", exc_info=True)
        return {"status": "error"}


async def telemetry_publish_tick(ctx: dict[str, Any]) -> dict[str, Any]:
    """Publica a telemetria desta caixa em ``worker_telemetry`` (RDS).

    Existe por causa do deploy dividido: a API pública (EC2) tem um Redis
    PRÓPRIO, sem filas, heartbeats nem token-bucket da Riot. Lendo o próprio
    Redis ela não ficava sem resposta — respondia ZERO: fila vazia, todo worker
    ``active: false``, chave da Riot ausente. Medido lado a lado, 0 contra 166 de
    profundidade real. Um operador conclui que a ingestão caiu.

    Publicar via banco usa o único canal que as duas caixas já compartilham, e
    o sentido é de dentro para fora — nada precisa alcançar o notebook, que fica
    atrás de NAT e às vezes desligado.

    Só roda onde este processo divide o Redis com os workers (ou seja, onde
    ``worker_telemetry_source`` NÃO é 'db'); do contrário a caixa publicaria de
    volta o snapshot que acabou de ler.

    Best-effort: telemetria nunca pode derrubar o scheduler.
    """
    try:
        from arena.api.routers.admin_telemetry import build_publish_payload
        from arena.db.session import get_sessionmaker
        from arena.services import telemetry_snapshot

        if telemetry_snapshot.reads_from_db():
            return {"status": "skipped", "reason": "this box reads telemetry from db"}

        payload = await build_publish_payload()
        async with get_sessionmaker()() as session:
            await telemetry_snapshot.publish(session, payload)
            await session.commit()
        return {"status": "ok", "source": settings.worker_telemetry_publish_source}
    except Exception:
        _log.warning("scheduler.telemetry_publish.failed", exc_info=True)
        return {"status": "error"}


async def _current_season_id() -> str | None:
    """The current season's id, or ``None`` when no season exists yet.

    "Corrente" = the season with the most recent ``starts_at`` — the same
    resolution :func:`_purge_cr_snapshots_recent` and the read path use. Kept in
    one place so the maintenance crons and the purge can never disagree about
    which season they're operating on.
    """
    from sqlalchemy import select

    from arena.db import models as m
    from arena.db.session import get_sessionmaker

    async with get_sessionmaker()() as session:
        row = (
            await session.execute(
                select(m.Season.id).order_by(m.Season.starts_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
    return str(row) if row is not None else None


async def heartbeat_tick(ctx: dict[str, Any]) -> dict[str, Any]:
    """Stamp liveness + detect an outage gap on restart (proposal §13.3 gap).

    ``run_at_startup=True`` is the whole mechanism: the tick right after a
    restart reads the heartbeat written before the process went down, compares
    it to "now", and — if the gap is wider than
    ``settings.reconcile_gap_threshold_seconds`` — opens a reconciliation
    window (``SET NX`` so an already-pending, not-yet-consumed window is never
    narrowed). The window is capped at ``reconcile_max_gap_seconds`` back from
    now; anything older is out of scope for the automatic catch-up and needs a
    manual ``scripts/backfill.py --mode refresh`` run.
    """
    redis: Any = ctx["redis"]
    now = int(time.time())
    try:
        raw = await redis.get(Q.SCHEDULER_HEARTBEAT_KEY)
        await redis.set(Q.SCHEDULER_HEARTBEAT_KEY, str(now))
    except Exception as exc:  # noqa: BLE001 — heartbeat is best-effort, never fatal
        _log.warning("scheduler.heartbeat.failed", error=str(exc))
        return {"status": "error", "error": str(exc)}

    if raw is None:
        # First tick ever (fresh Redis) — nothing to reconcile, not an outage.
        return {"status": "ok", "gap": 0}

    last = int(raw)
    gap = now - last
    if gap <= settings.reconcile_gap_threshold_seconds:
        return {"status": "ok", "gap": gap}

    since = max(last, now - settings.reconcile_max_gap_seconds)
    capped = since > last
    opened = bool(await redis.set(Q.RECONCILE_WINDOW_KEY, str(since), nx=True))
    _log.warning(
        "scheduler.gap_detected",
        gapSeconds=gap,
        since=since,
        capped=capped,
        windowOpened=opened,
    )
    return {"status": "ok", "gap": gap, "since": since, "capped": capped, "windowOpened": opened}


async def _purge_cr_snapshots_recent() -> int:
    """Delete ``cr_snapshots_recent`` rows outside the current-season window.

    "Corrente" = temporada de ``starts_at`` mais recente (mesma resolução do
    read path). Best-effort: DB fora do ar loga e devolve 0 — o cron tenta de
    novo na próxima hora. Roda no PRIMÁRIO (o purge replica para a réplica).
    """
    try:
        from typing import Any, cast

        from sqlalchemy import delete, select
        from sqlalchemy.engine import CursorResult

        from arena.db import models as m
        from arena.db.session import get_sessionmaker

        async with get_sessionmaker()() as session:
            current = (
                select(m.Season.id).order_by(m.Season.starts_at.desc()).limit(1)
            ).scalar_subquery()
            result = await session.execute(
                delete(m.CrSnapshotRecent).where(m.CrSnapshotRecent.season_id != current)
            )
            await session.commit()
            purged = int(cast(CursorResult[Any], result).rowcount or 0)
            if purged:
                _log.info("scheduler.cr_snapshots_recent.purged", rows=purged)
            return purged
    except Exception:
        _log.warning("scheduler.cr_snapshots_recent.purge_failed", exc_info=True)
        return 0


# ---------------------------------------------------------------------------
# Cron schedule registry (consumed by main.SchedulerWorker)
# ---------------------------------------------------------------------------

#: arq CronJob specs. ``run_at_startup`` is off for transitions (avoid acting on
#: a half-warm process) but on for the maintenance jobs so a fresh deploy warms
#: caches / the Top-1000 set immediately.
CRON_JOBS = [
    # Season lifecycle — every 5 minutes.
    cron(season_transition, minute=set(range(0, 60, 5)), run_at_startup=False),
    # Leaderboard + Top-1000 set — every minute (priority-lane SLA, §3.4).
    cron(leaderboard_refresh, minute=set(range(0, 60)), run_at_startup=True),
    # Cache warm — every 5 minutes, offset from the transition tick.
    cron(cache_warm, minute=set(range(2, 60, 5)), run_at_startup=True),
    # cr_snapshot continuous-aggregate maintenance — hourly at :07.
    cron(cr_snapshot_maintenance, minute={7}, run_at_startup=False),
    # champion_daily_stats rollup — every 15 minutes, offset off the :07 snapshot
    # tick. Frequent because it backs the /champions tierlist: a stale rollup is a
    # stale tierlist, and the window recompute is cheap (a few recent days).
    cron(champion_daily_maintenance, minute={3, 18, 33, 48}, run_at_startup=True),
    # season_record_cache — hourly at :22. Only "Mais partidas hoje" is remotely
    # time-sensitive, and this is the more expensive of the two rebuilds.
    cron(season_records_maintenance, minute={22}, run_at_startup=True),
    # champion_combo_stats — hourly at :41. The heaviest tick (full-season
    # recompute of a 2- and 3-way self-join); parked away from every other job.
    cron(champion_combo_maintenance, minute={41}, run_at_startup=True),
    # champion_build_stats — hourly at :56. Native augment/item rollup (unnest
    # over an ARRAY column); own off-peak minute, away from combo/daily/records.
    cron(champion_build_stats_maintenance, minute={56}, run_at_startup=True),
    # champion_versus_stats — hourly at :26. Cross-subteam matchup rollup
    # (~19s measured); own off-peak minute, away from every other tick.
    cron(champion_versus_maintenance, minute={26}, run_at_startup=True),
    # champion_build_variant_stats — hourly at :11. Build-variant rollup
    # (grouped by prismatic augment) — heaviest tick after versus (~99s
    # measured: 2 ARRAY columns per row + Python-side Counter work per
    # participant); own off-peak minute.
    cron(champion_build_variant_maintenance, minute={11}, run_at_startup=True),
    # Drenagem do match_backlog — de minuto em minuto durante um refill. Só faz
    # algo em ``catching_up``, e é serial de propósito.
    cron(backlog_drain_tick, minute=set(range(0, 60)), run_at_startup=True),
    # Medição da fronteira do refill — de minuto em minuto, também só em
    # ``catching_up``. É quem declara saturação e devolve a temporada a ``live``.
    cron(bootstrap_tick, minute=set(range(0, 60)), run_at_startup=False),
    # Replay incremental — de meia em meia hora, e só com as filas paradas.
    # Consome o replay_floor armado por chegadas fora de ordem.
    cron(rating_replay_tick, minute={14, 44}, run_at_startup=False),
    # Outage-gap heartbeat — every minute, AND at startup so a restart detects
    # the gap immediately instead of waiting up to a minute.
    cron(heartbeat_tick, minute=set(range(0, 60)), run_at_startup=True),
    # Telemetria para a caixa da API pública — de minuto em minuto. Precisa ser
    # bem mais frequente que worker_telemetry_stale_after_seconds (180s) para um
    # tick perdido não marcar tudo como obsoleto.
    cron(telemetry_publish_tick, minute=set(range(0, 60)), run_at_startup=True),
]


__all__ = [
    "season_transition",
    "leaderboard_refresh",
    "cache_warm",
    "cr_snapshot_maintenance",
    "champion_daily_maintenance",
    "champion_combo_maintenance",
    "champion_build_stats_maintenance",
    "champion_versus_maintenance",
    "champion_build_variant_maintenance",
    "season_records_maintenance",
    "backlog_drain_tick",
    "bootstrap_tick",
    "rating_replay_tick",
    "telemetry_publish_tick",
    "heartbeat_tick",
    "CRON_JOBS",
]
