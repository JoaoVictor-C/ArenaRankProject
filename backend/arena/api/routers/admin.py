"""Admin router — contract §6 overview + proposal §4.3 admin workflow.

Mounts under ``/api/v1/admin`` and serves the operator surface:

* ``GET  /admin/overview``                    — system-health dashboard DTO
  (metrics / workers / queues / integrity / flags / dlq / season / riotApi).
* ``POST /admin/seasons``                     — create a season (lifecycle: new
  ``ACTIVE`` row).
* ``PATCH /admin/seasons/{seasonId}/config``  — reconfigure season params
  (placementCount / resetFactor / sigmaCap …).
* ``POST /admin/seasons/{seasonId}/transition`` — advance the lifecycle state
  machine one legal step (ACTIVE → SOFT_LOCK → ENDED → OFF_SEASON), driven by
  :class:`arena.services.season_service.SeasonService`.
* ``GET  /admin/dlq``                          — list dead-lettered matches.
* ``POST /admin/dlq/requeue-all``              — re-enqueue every DLQ entry.
* ``POST /admin/dlq/{matchId}/requeue``        — re-enqueue a failed match.
* ``DELETE /admin/dlq/{matchId}``              — discard a DLQ entry.
* ``GET  /admin/integrity``                    — the open integrity-review queue.
* ``POST /admin/integrity/{eventId}/review``   — mark a flag reviewed (+ optional
  manual override note).

Design notes
------------
This module is importable with **no** heavy runtime deps (SQLAlchemy / Redis /
arq) installed: the router object and all Pydantic DTOs live at import time
(FastAPI + pydantic only), while every DB / queue / service touch is resolved
*lazily and defensively* inside the handlers via :func:`_runtime`. When the data
layer + a live Redis/Postgres are present the endpoints serve **real** queue,
season and integrity data; otherwise they degrade to a representative payload
(contract: the admin-overview subsystem is a "DTO sample" backed by real tables
where available — master plan §2).

Contract / ToS guardrails honored here:

* JSON keys are camelCase (DTOs derive from :class:`arena.schemas.common.ArenaModel`).
* User-facing strings are PT-BR.
* No mu/sigma and no augment/item winrate ever leave this layer — admin metrics
  speak in CR / Pontos / queue-depth / counts only.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from pydantic import Field

from arena.api.rbac import record_audit, require_scope
from arena.core.logging import get_logger
from arena.schemas.admin import (
    AdminDailyMatches,
    AdminDailyMatchStat,
    AdminDlqItem,
    AdminFlag,
    AdminIntegrityItem,
    AdminMetric,
    AdminOverview,
    AdminQueue,
    AdminRiotApi,
    AdminSeason,
    AdminWorker,
)
from arena.schemas.common import ArenaModel, Severity

_log = get_logger("arena.api.admin")

router = APIRouter(prefix="/admin", tags=["admin"])

# Mirror of the DB lifecycle enum values without importing SQLAlchemy at module
# load (arena.db.models pulls in sqlalchemy). The transition handler validates
# against the real enum lazily.
SeasonStatusValue = Literal["ACTIVE", "SOFT_LOCK", "ENDED", "OFF_SEASON"]
_SEASON_STATUS_VALUES: frozenset[str] = frozenset({"ACTIVE", "SOFT_LOCK", "ENDED", "OFF_SEASON"})

# DB Severity enum (uppercase) -> contract Severity literal (lowercase).
_SEVERITY_WIRE: dict[str, Severity] = {
    "INFO": "info",
    "WARN": "warn",
    "CRITICAL": "critical",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Operation request/response DTOs (admin-operational; not public read contract).
# Kept local to the router per the touch-scope; all camelCase on the wire.
# ---------------------------------------------------------------------------


class SeasonCreateRequest(ArenaModel):
    """Create a new season (starts its lifecycle in ``ACTIVE``)."""

    name: str = Field(min_length=1, max_length=64)
    queue_id: int
    starts_at: datetime
    ends_at: datetime
    # placementCount / resetFactor / sigmaCap … (mirrors RatingParams).
    config: dict[str, Any] = Field(default_factory=dict)


class SeasonConfigUpdateRequest(ArenaModel):
    """Patch the season's rating/lifecycle config blob (shallow-merged)."""

    config: dict[str, Any]


class SeasonTransitionRequest(ArenaModel):
    """Advance the lifecycle one legal step along the state machine."""

    to: SeasonStatusValue


class SeasonOpResult(ArenaModel):
    season_id: str
    status: str
    message: str


class DlqRequeueResult(ArenaModel):
    match_id: str
    requeued: bool
    queue: str
    message: str


class DlqRequeueAllResult(ArenaModel):
    total: int
    requeued: int
    failed: int
    queue: str
    message: str


class DlqDiscardResult(ArenaModel):
    match_id: str
    discarded: bool
    message: str


class IntegrityReviewRequest(ArenaModel):
    """Mark a flag reviewed; optional manual-override note + reviewer id."""

    reviewer_id: str | None = None
    note: str | None = Field(default=None, max_length=2000)
    # Manual override: force the participant(s) eligible/ineligible, or none.
    override: Literal["eligible", "ineligible", "none"] | None = None


class IntegrityReviewResult(ArenaModel):
    event_id: str
    reviewed: bool
    message: str


# ---------------------------------------------------------------------------
# Lazy runtime resolution. Mirrors arena.db.session / arena.workers.deps: never
# hard-fail on import order or a missing optional dep — degrade to representative.
# ---------------------------------------------------------------------------


class _Runtime:
    """Best-effort handle to the live data layer.

    Any attribute may be ``None`` when its backing dependency is absent in this
    environment (no SQLAlchemy / no Redis / no arq). Handlers branch on
    availability and fall back to representative data rather than 500-ing.
    """

    __slots__ = ("sessionmaker", "redis_factory", "arq_redis_factory", "season_service")

    def __init__(self) -> None:
        self.sessionmaker: Any | None = None
        self.redis_factory: Any | None = None
        # Async factory returning an ArqRedis (enqueue_job-capable) pool —
        # separate from redis_factory (a plain redis.asyncio.Redis) because
        # most handlers only need plain ops, and the two happen to differ in
        # sync vs async construction (Redis.from_url is sync; arq's create_pool
        # is not). Only the DLQ requeue needs this today.
        self.arq_redis_factory: Any | None = None
        self.season_service: Any | None = None


_RUNTIME_WARNED = False


def _runtime() -> _Runtime:
    """Resolve DB session factory, Redis, and SeasonService defensively."""
    global _RUNTIME_WARNED
    rt = _Runtime()

    try:
        from arena.db.session import get_sessionmaker

        rt.sessionmaker = get_sessionmaker()
    except Exception:  # pragma: no cover - optional dep / import-order tolerance
        rt.sessionmaker = None

    try:
        from arena.core.config import settings
        from redis.asyncio import Redis

        def _make_redis() -> Any:
            return Redis.from_url(settings.redis_url)

        rt.redis_factory = _make_redis
    except Exception:  # pragma: no cover
        rt.redis_factory = None

    try:
        from arena.workers.deps import create_redis_pool

        rt.arq_redis_factory = create_redis_pool
    except Exception:  # pragma: no cover - worker deps absent
        rt.arq_redis_factory = None

    try:
        from arena.services.season_service import SeasonService

        rt.season_service = SeasonService()
    except Exception:  # pragma: no cover
        rt.season_service = None

    if rt.sessionmaker is None and rt.redis_factory is None and not _RUNTIME_WARNED:
        _log.warning(
            "admin.runtime.degraded",
            reason="DB/Redis runtime unavailable — serving representative admin data",
        )
        _RUNTIME_WARNED = True
    return rt


# ---------------------------------------------------------------------------
# Representative fallbacks (used when the live runtime is unavailable). These
# are intentionally small and clearly synthetic; real data overrides them.
# ---------------------------------------------------------------------------


def _representative_season() -> AdminSeason:
    return AdminSeason(
        current=1,
        state="ACTIVE",
        started_at=_now_iso(),
        config={"placementCount": "10", "resetFactor": "0.5", "sigmaCap": "350"},
    )


def _representative_overview() -> AdminOverview:
    return AdminOverview(
        metrics=[
            AdminMetric(key="activePlayers", label="Jogadores ativos", value="0"),
            AdminMetric(key="matchesToday", label="Partidas hoje", value="0"),
            AdminMetric(key="totalMatches", label="Total de partidas", value="0"),
            AdminMetric(key="queueDepth", label="Fila de processamento", value="0"),
            AdminMetric(key="dlqDepth", label="Fila de erros (DLQ)", value="0"),
        ],
        workers=[
            AdminWorker(name="ingestion", status="ok", load=0.0),
            AdminWorker(name="processor", status="ok", load=0.0),
            AdminWorker(name="scheduler", status="ok", load=0.0),
        ],
        queues=[
            AdminQueue(name="arena:priority", depth=0, rate="0/min"),
            AdminQueue(name="arena:standard", depth=0, rate="0/min"),
            AdminQueue(name="arena:dlq", depth=0, rate="0/min"),
        ],
        integrity=[],
        flags=[],
        dlq=[],
        season=_representative_season(),
        riot_api=[
            AdminRiotApi(name="match-v5", status="ok", usage="0%"),
            AdminRiotApi(name="account-v1", status="ok", usage="0%"),
        ],
    )


# ---------------------------------------------------------------------------
# Live data collectors. Each returns ``None`` on any failure so the handler can
# substitute the representative value for that one section (overview stays up).
# ---------------------------------------------------------------------------


async def _queues_from_snapshot() -> tuple[list[AdminQueue], int, int] | None:
    """Profundidades a partir do snapshot publicado pela caixa de workers.

    ``None`` quando não há snapshot ou ele está obsoleto — e ``None`` é
    importante: o chamador trata isso como "não sei" e a métrica some, em vez de
    virar um zero que o operador leria como "fila vazia, tudo processado".
    """
    from arena.services import telemetry_snapshot
    from arena.workers.queues import DLQ_KEY, PRIORITY_QUEUE, STANDARD_QUEUE

    try:
        from arena.db.session import get_sessionmaker

        async with get_sessionmaker()() as session:
            snap = await telemetry_snapshot.read_snapshot(session)
    except Exception:  # noqa: BLE001 - telemetria nunca derruba o overview
        _log.warning("admin.telemetry_snapshot_failed", exc_info=True)
        return None
    if snap is None or snap.stale:
        return None
    pipeline = (snap.payload or {}).get(telemetry_snapshot.LIVE_KEY, {}).get("pipeline") or {}
    try:
        priority = int(pipeline.get("priorityQueue", 0))
        standard = int(pipeline.get("standardQueue", 0))
        dlq = int(pipeline.get("dlq", 0))
    except (TypeError, ValueError):
        return None
    queues = [
        AdminQueue(name=PRIORITY_QUEUE, depth=priority, rate="—"),
        AdminQueue(name=STANDARD_QUEUE, depth=standard, rate="—"),
        AdminQueue(name=DLQ_KEY, depth=dlq, rate="—"),
    ]
    return queues, priority + standard, dlq


async def _live_queues(rt: _Runtime) -> tuple[list[AdminQueue], int, int] | None:
    """Real processing-pipeline depths from Redis.

    Returns (queues, queueDepth, dlqDepth). ``arena:priority``/``arena:standard``
    are real arq queues now — the sweep pipeline enqueues ``process_match`` jobs
    onto them directly (``enqueue_job``) and ``StandardWorker``/``PriorityWorker``
    consume them continuously. There is no separate pending-list stage anymore
    (that was ``BulkProcessorWorker``, now retired).
    """
    # Caixa que não divide o Redis com os workers (API pública do split): as
    # profundidades vêm do snapshot que a caixa de workers publica no banco.
    # Ler o Redis LOCAL aqui devolveria 0 com cara de fila vazia — medido, 0
    # contra 166 reais. Ver services/telemetry_snapshot.
    from arena.services import telemetry_snapshot

    if telemetry_snapshot.reads_from_db():
        return await _queues_from_snapshot()

    if rt.redis_factory is None:
        return None
    from arena.workers.queues import DLQ_KEY, PRIORITY_QUEUE, STANDARD_QUEUE

    redis = rt.redis_factory()
    try:
        priority = int(await redis.zcard(PRIORITY_QUEUE) or 0)
        standard = int(await redis.zcard(STANDARD_QUEUE) or 0)
        dlq = int(await redis.llen(DLQ_KEY) or 0)
    except Exception:  # pragma: no cover - Redis down
        return None
    finally:
        await _close_redis(redis)

    queues = [
        AdminQueue(name=PRIORITY_QUEUE, depth=priority, rate="—"),
        AdminQueue(name=STANDARD_QUEUE, depth=standard, rate="—"),
        AdminQueue(name=DLQ_KEY, depth=dlq, rate="—"),
    ]
    return queues, priority + standard, dlq


def _dlq_entry_ts(payload: dict[str, Any]) -> str:
    """Dead-lettered-at timestamp as ISO 8601.

    ``processor._dead_letter`` writes ``deadLetteredAt`` as a ``time.time()``
    epoch float, not an ISO string — falling straight back to "now" here (the
    old behavior) made every DLQ row show the same "há Ns" regardless of how
    long it had actually been stuck.
    """
    raw = payload.get("deadLetteredAt")
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw, tz=UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            pass
    legacy = payload.get("ts") or payload.get("failedAt")
    return str(legacy) if legacy else _now_iso()


async def _live_dlq_items(rt: _Runtime, limit: int) -> list[AdminDlqItem] | None:
    """Inspect dead-lettered matches (JSON payloads on the DLQ Redis list)."""
    if rt.redis_factory is None:
        return None
    from arena.workers.queues import DLQ_KEY

    redis = rt.redis_factory()
    try:
        raw = await redis.lrange(DLQ_KEY, 0, max(0, limit - 1))
    except Exception:  # pragma: no cover
        return None
    finally:
        await _close_redis(redis)

    items: list[AdminDlqItem] = []
    for entry in raw:
        payload = _decode_json(entry)
        items.append(
            AdminDlqItem(
                match_id=str(payload.get("riotMatchId") or payload.get("matchId") or "?"),
                # `_dead_letter` writes the field as "tries", not "attempts" —
                # the old key name never matched, so this always read 0.
                attempts=int(payload.get("tries") or payload.get("attempts") or 0),
                reason=str(payload.get("error") or payload.get("reason") or "desconhecido"),
                ts=_dlq_entry_ts(payload),
            )
        )
    return items


async def _live_season_and_metrics(
    rt: _Runtime,
) -> tuple[AdminSeason, list[AdminIntegrityItem], list[AdminFlag], int, int, int] | None:
    """Real ACTIVE season + open integrity queue + player flags + counts.

    Returns (season, integrity, flags, activePlayers, matchesToday, totalMatches)
    or ``None``.
    """
    if rt.sessionmaker is None:
        return None
    try:
        from sqlalchemy import func, select

        from arena.db import models as md
    except Exception:  # pragma: no cover
        return None

    try:
        async with rt.sessionmaker() as session:
            # Current season: most recent ACTIVE, else most recent by start.
            season_row = (
                await session.execute(
                    select(md.Season)
                    .where(md.Season.status == md.SeasonStatus.ACTIVE)
                    .order_by(md.Season.starts_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if season_row is None:
                season_row = (
                    await session.execute(
                        select(md.Season).order_by(md.Season.starts_at.desc()).limit(1)
                    )
                ).scalar_one_or_none()

            season = _season_dto(season_row)

            # Active players this season + matches today.
            active_players = 0
            matches_today = 0
            if season_row is not None:
                active_players = int(
                    (
                        await session.execute(
                            select(func.count())
                            .select_from(md.PlayerSeason)
                            .where(
                                md.PlayerSeason.season_id == season_row.id,
                                md.PlayerSeason.matches_played > 0,
                            )
                        )
                    ).scalar_one()
                )
                start_of_day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
                matches_today = int(
                    (
                        await session.execute(
                            select(func.count())
                            .select_from(md.Match)
                            .where(
                                md.Match.season_id == season_row.id,
                                md.Match.played_at >= start_of_day,
                            )
                        )
                    ).scalar_one()
                )

            # All-time count across every season — not scoped to season_row,
            # unlike matches_today, so it's still meaningful when no season
            # is active/found.
            total_matches = int(
                (await session.execute(select(func.count()).select_from(md.Match))).scalar_one()
            )

            integrity = await _open_integrity(session, md)
            flags = await _player_flags(session, md)
            return season, integrity, flags, active_players, matches_today, total_matches
    except Exception:  # pragma: no cover - DB unreachable / schema not migrated
        _log.warning("admin.live_data.failed", exc_info=True)
        return None


async def _live_daily_matches(rt: _Runtime, *, days: int) -> list[AdminDailyMatchStat] | None:
    """Matches per UTC calendar day, across all seasons, for the last *days* days.

    One grouped query (day, mode) rather than a query per day — the per-day
    duration average and integrity-flag count are folded in so the console
    doesn't need a second round-trip. Sparse by design, like
    ``StatsService.season_activity``: a day with zero matches is simply absent
    rather than a fabricated zero row.
    """
    if rt.sessionmaker is None:
        return None
    try:
        from sqlalchemy import case, func, select

        from arena.db import models as md
    except Exception:  # pragma: no cover
        return None

    try:
        cutoff = datetime.now(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=days - 1)
        day = func.date(md.Match.played_at)
        flagged = case((func.jsonb_array_length(md.Match.integrity_flags) > 0, 1), else_=0)
        stmt = (
            select(
                day.label("d"),
                md.Match.mode.label("mode"),
                func.count().label("c"),
                func.avg(md.Match.duration_seconds).label("avg_dur"),
                func.sum(flagged).label("flagged"),
            )
            .where(md.Match.played_at >= cutoff)
            .group_by(day, md.Match.mode)
            .order_by(day.desc())
        )
        async with rt.sessionmaker() as session:
            rows = (await session.execute(stmt)).all()

        # Fold the per-(day, mode) rows into one stat per day.
        by_day: dict[str, AdminDailyMatchStat] = {}
        dur_weighted: dict[str, float] = {}
        for r in rows:
            d = r.d
            key = d.isoformat() if hasattr(d, "isoformat") else str(d)
            stat = by_day.setdefault(key, AdminDailyMatchStat(date=key, matches=0))
            count = int(r.c or 0)
            stat.matches += count
            stat.with_integrity_flags += int(r.flagged or 0)
            if r.mode is not None and getattr(r.mode, "value", r.mode) == "DUOS":
                stat.duos += count
            elif r.mode is not None and getattr(r.mode, "value", r.mode) == "TRIOS":
                stat.trios += count
            if r.avg_dur is not None:
                dur_weighted[key] = dur_weighted.get(key, 0.0) + float(r.avg_dur) * count

        for key, stat in by_day.items():
            if stat.matches > 0 and key in dur_weighted:
                stat.avg_duration_seconds = round(dur_weighted[key] / stat.matches, 1)

        return sorted(by_day.values(), key=lambda s: s.date)
    except Exception:  # pragma: no cover - DB unreachable / schema not migrated
        _log.warning("admin.daily_matches.failed", exc_info=True)
        return None


async def _open_integrity(session: Any, md: Any) -> list[AdminIntegrityItem]:
    """Open (unreviewed) integrity events — the moderation review queue."""
    from sqlalchemy import select

    rows = (
        await session.execute(
            select(md.IntegrityEvent)
            .where(md.IntegrityEvent.reviewed.is_(False))
            .order_by(md.IntegrityEvent.created_at.desc())
            .limit(50)
        )
    ).scalars()
    return [
        AdminIntegrityItem(
            id=str(ev.id),
            player=str(ev.player_id) if ev.player_id is not None else "—",
            reason=ev.flag_type,
            severity=_SEVERITY_WIRE.get(ev.severity.value, "info"),
            ts=ev.created_at.isoformat() if ev.created_at else _now_iso(),
        )
        for ev in rows
    ]


async def _player_flags(session: Any, md: Any) -> list[AdminFlag]:
    """Account-level moderation flags (shadowban / ban / restriction)."""
    from sqlalchemy import or_, select

    rows = (
        await session.execute(
            select(md.Player)
            .where(
                or_(
                    md.Player.shadowbanned.is_(True),
                    md.Player.banned.is_(True),
                    md.Player.restricted.is_(True),
                )
            )
            .limit(50)
        )
    ).scalars()
    flags: list[AdminFlag] = []
    for p in rows:
        if p.banned:
            flag, sev = "banido", "critical"
        elif p.shadowbanned:
            flag, sev = "shadowban", "warn"
        else:
            flag, sev = "restrito", "warn"
        flags.append(
            AdminFlag(
                id=str(p.id),
                player=p.summoner_name or str(p.id),
                flag=flag,
                severity=sev,  # type: ignore[arg-type]
            )
        )
    return flags


def _season_dto(season_row: Any | None) -> AdminSeason:
    if season_row is None:
        return _representative_season()
    raw_config = season_row.config if isinstance(season_row.config, dict) else {}
    config = {str(k): str(v) for k, v in raw_config.items()}
    # ``current`` is a small int the UI shows as "Temporada N"; derive from the
    # season name's trailing digits when present, else 1.
    current = _season_ordinal(season_row.name)
    return AdminSeason(
        current=current,
        state=season_row.status.value,
        started_at=season_row.starts_at.isoformat() if season_row.starts_at else _now_iso(),
        config=config,
    )


def _season_ordinal(name: str) -> int:
    digits = "".join(ch for ch in (name or "") if ch.isdigit())
    return int(digits) if digits else 1


# ---------------------------------------------------------------------------
# Small Redis/JSON helpers.
# ---------------------------------------------------------------------------


async def _close_redis(redis: Any) -> None:
    try:
        aclose = getattr(redis, "aclose", None)
        if aclose is not None:
            await aclose()
        else:  # pragma: no cover - older redis-py
            await redis.close()
    except Exception:  # pragma: no cover
        pass


def _decode_json(entry: Any) -> dict[str, Any]:
    if isinstance(entry, bytes | bytearray):
        entry = entry.decode("utf-8", "replace")
    if isinstance(entry, str):
        try:
            parsed = json.loads(entry)
            return parsed if isinstance(parsed, dict) else {"raw": entry}
        except (ValueError, TypeError):
            return {"raw": entry}
    if isinstance(entry, dict):
        return entry
    return {"raw": str(entry)}


def _db_unavailable(action: str) -> HTTPException:
    """A PT-BR 503 for when the data layer is unreachable / not migrated."""
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Camada de dados indisponível para {action}.",
    )


# ===========================================================================
# GET /admin/overview — system-health dashboard
# ===========================================================================


@router.get(
    "/overview",
    response_model=AdminOverview,
    summary="Visão geral do painel administrativo",
    response_model_by_alias=True,
    dependencies=[Depends(require_scope("telemetry:read"))],
)
async def get_overview() -> AdminOverview:
    """Aggregate the operator dashboard.

    Backed by real queue depths (Redis), the live ACTIVE season, the open
    integrity-review queue and account flags (Postgres) when those runtimes are
    available; falls back to a representative payload per section otherwise so
    the dashboard never hard-fails.
    """
    rt = _runtime()
    overview = _representative_overview()

    # --- queues + queue/dlq depth metrics ---
    # ``None`` = NÃO SEI, e isso não pode virar 0. Esta era a mentira do deploy
    # dividido: a API do EC2 não enxerga o Redis dos workers e o painel mostrava
    # "fila 0" — medido, 0 contra 166 reais — que o operador lê como "tudo
    # processado". Um traço diz a verdade; um zero inventa uma.
    queue_depth: int | None = None
    dlq_depth: int | None = None
    live_q = await _live_queues(rt)
    if live_q is not None:
        overview.queues, queue_depth, dlq_depth = live_q

    # --- DLQ items (Redis) ---
    live_dlq = await _live_dlq_items(rt, limit=25)
    if live_dlq is not None:
        overview.dlq = live_dlq

    # --- season + integrity + flags + business metrics (Postgres) ---
    active_players = 0
    matches_today = 0
    total_matches = 0
    live = await _live_season_and_metrics(rt)
    if live is not None:
        season, integrity, flags, active_players, matches_today, total_matches = live
        overview.season = season
        overview.integrity = integrity
        overview.flags = flags

    overview.metrics = [
        AdminMetric(key="activePlayers", label="Jogadores ativos", value=str(active_players)),
        AdminMetric(key="matchesToday", label="Partidas hoje", value=str(matches_today)),
        AdminMetric(key="totalMatches", label="Total de partidas", value=str(total_matches)),
        # "—" quando a profundidade é desconhecida (esta caixa não enxerga o
        # Redis dos workers e o snapshot está ausente ou obsoleto). O tile
        # continua visível — sumir esconderia que a métrica existe — mas para de
        # afirmar um número que ninguém mediu.
        AdminMetric(
            key="queueDepth",
            label="Fila de processamento",
            value="—" if queue_depth is None else str(queue_depth),
        ),
        AdminMetric(
            key="dlqDepth",
            label="Fila de erros (DLQ)",
            value="—" if dlq_depth is None else str(dlq_depth),
        ),
    ]
    return overview


@router.get(
    "/matches/daily",
    response_model=AdminDailyMatches,
    summary="Partidas por dia + estatísticas (duração, modo, flags de integridade)",
    response_model_by_alias=True,
    dependencies=[Depends(require_scope("telemetry:read"))],
)
async def get_daily_matches(
    days: int = Query(14, ge=1, le=90, description="Janela em dias (UTC), inclusive hoje."),
) -> AdminDailyMatches:
    """Match volume per UTC day, across all seasons, for the last *days* days.

    Backed by the ``matches`` table (real per-match rows: duration, mode,
    integrity flags) — degrades to an empty list rather than 500-ing when
    Postgres is unavailable, same convention as the rest of this router.
    """
    rt = _runtime()
    result = await _live_daily_matches(rt, days=days)
    return AdminDailyMatches(ts=_now_iso(), days=result or [])


# ===========================================================================
# Season management (proposal §4.3 — create / configure / transition)
# ===========================================================================


@router.post(
    "/seasons",
    response_model=SeasonOpResult,
    status_code=status.HTTP_201_CREATED,
    summary="Criar temporada",
    response_model_by_alias=True,
    dependencies=[Depends(require_scope("season:write"))],
)
async def create_season(request: Request, body: SeasonCreateRequest) -> SeasonOpResult:
    """Create a season row in ``ACTIVE`` (the lifecycle entry state)."""
    if body.ends_at <= body.starts_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A data de término deve ser posterior à data de início.",
        )
    rt = _runtime()
    if rt.sessionmaker is None:
        raise _db_unavailable("criar temporada")
    try:
        from arena.db import models as md

        async with rt.sessionmaker() as session:
            season = md.Season(
                name=body.name,
                queue_id=body.queue_id,
                starts_at=body.starts_at,
                ends_at=body.ends_at,
                status=md.SeasonStatus.ACTIVE,
                config=body.config or {},
            )
            session.add(season)
            await session.commit()
            await session.refresh(season)
            _log.info("admin.season.created", seasonId=str(season.id), name=season.name)
            await record_audit(request, action="season.created", target=season.name)
            return SeasonOpResult(
                season_id=str(season.id),
                status=season.status.value,
                message=f"Temporada '{season.name}' criada.",
            )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - DB unreachable / not migrated
        _log.warning("admin.season.create_failed", exc_info=True)
        raise _db_unavailable("criar temporada") from exc


@router.patch(
    "/seasons/{season_id}/config",
    response_model=SeasonOpResult,
    summary="Reconfigurar parâmetros da temporada",
    response_model_by_alias=True,
    dependencies=[Depends(require_scope("season:write"))],
)
async def update_season_config(
    request: Request,
    body: SeasonConfigUpdateRequest,
    season_id: str = Path(..., description="ID da temporada"),
) -> SeasonOpResult:
    """Shallow-merge new rating/lifecycle params into the season config blob."""
    rt = _runtime()
    if rt.sessionmaker is None:
        raise _db_unavailable("configurar temporada")
    try:
        from arena.db import models as md

        async with rt.sessionmaker() as session:
            season = await session.get(md.Season, season_id)
            if season is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Temporada não encontrada.",
                )
            merged = dict(season.config or {})
            merged.update(body.config)
            season.config = merged
            await session.commit()
            _log.info("admin.season.config_updated", seasonId=season_id)
            await record_audit(request, action="season.config_updated", target=season_id)
            return SeasonOpResult(
                season_id=season_id,
                status=season.status.value,
                message="Configuração da temporada atualizada.",
            )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - DB unreachable / not migrated
        _log.warning("admin.season.config_failed", seasonId=season_id, exc_info=True)
        raise _db_unavailable("configurar temporada") from exc


@router.post(
    "/seasons/{season_id}/transition",
    response_model=SeasonOpResult,
    summary="Avançar o ciclo de vida da temporada",
    response_model_by_alias=True,
    dependencies=[Depends(require_scope("season:write"))],
)
async def transition_season(
    request: Request,
    body: SeasonTransitionRequest,
    season_id: str = Path(..., description="ID da temporada"),
) -> SeasonOpResult:
    """Advance one legal step of the lifecycle state machine.

    Delegates to :meth:`SeasonService.advance_status`, which rejects any
    non-adjacent transition with a PT-BR error.
    """
    if body.to not in _SEASON_STATUS_VALUES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Estado de destino inválido: '{body.to}'.",
        )
    rt = _runtime()
    if rt.sessionmaker is None or rt.season_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Serviço de temporadas indisponível.",
        )
    from arena.db import models as md
    from arena.services.season_service import SeasonTransitionError

    target = md.SeasonStatus(body.to)
    try:
        async with rt.sessionmaker() as session:
            try:
                new_status = await rt.season_service.advance_status(
                    session, season_id=season_id, to=target
                )
            except SeasonTransitionError as exc:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
            _log.info(
                "admin.season.transition",
                seasonId=season_id,
                to=new_status.value,
            )
            await record_audit(
                request, action="season.transitioned", target=season_id, to=new_status.value
            )
            return SeasonOpResult(
                season_id=season_id,
                status=new_status.value,
                message=f"Temporada avançada para '{new_status.value}'.",
            )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - DB unreachable / not migrated
        _log.warning("admin.season.transition_failed", seasonId=season_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Serviço de temporadas indisponível.",
        ) from exc


# ===========================================================================
# DLQ review (proposal §4.3 — inspect / requeue / discard failed matches)
# ===========================================================================


@router.get(
    "/dlq",
    response_model=list[AdminDlqItem],
    summary="Listar partidas na fila de erros (DLQ)",
    response_model_by_alias=True,
    dependencies=[Depends(require_scope("telemetry:read"))],
)
async def list_dlq(
    limit: int = Query(50, ge=1, le=500, description="Máximo de itens"),
) -> list[AdminDlqItem]:
    """List dead-lettered matches (most-recent first)."""
    rt = _runtime()
    items = await _live_dlq_items(rt, limit=limit)
    return items if items is not None else []


@router.post(
    "/dlq/requeue-all",
    response_model=DlqRequeueAllResult,
    summary="Reprocessar toda a DLQ",
    response_model_by_alias=True,
    dependencies=[Depends(require_scope("dlq:write"))],
)
async def requeue_all_dlq(request: Request) -> DlqRequeueAllResult:
    """Re-enqueue every dead-lettered match onto the priority arq queue.

    Claims the whole DLQ in one shot — one ``LRANGE`` to read it, then
    ``LTRIM`` to drop exactly the range just read — instead of the per-match
    route's ``LREM`` scan repeated once per entry (O(n) per item, O(n²) for a
    bulk drain of a large backlog). Trimming by the captured length rather
    than clearing the key outright also means an entry dead-lettered
    *during* this call (appended to the tail after we already read) is left
    alone rather than raced away. Each captured entry is pushed back onto the
    DLQ if its own requeue fails (e.g. a Redis blip mid-drain), so a partial
    failure loses nothing — it just stays queued for the next attempt.
    """
    rt = _runtime()
    if rt.redis_factory is None or rt.arq_redis_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Fila indisponível para reprocessamento.",
        )
    from arena.workers.queues import DLQ_KEY, PRIORITY_QUEUE, PROCESS_MATCH_TASK

    redis = await rt.arq_redis_factory()
    try:
        raw = await redis.lrange(DLQ_KEY, 0, -1)
        total = len(raw)
        if total:
            await redis.ltrim(DLQ_KEY, total, -1)

        requeued = 0
        failed = 0
        for entry in raw:
            payload = _decode_json(entry)
            match_id = str(payload.get("riotMatchId") or payload.get("matchId") or "")
            if not match_id:
                failed += 1
                continue
            try:
                await redis.enqueue_job(
                    PROCESS_MATCH_TASK,
                    match_id,
                    _queue_name=PRIORITY_QUEUE,
                    _job_id=f"{PROCESS_MATCH_TASK}:{match_id}:requeue:{int(time.time())}",
                )
                requeued += 1
            except Exception:  # noqa: BLE001 - don't lose the entry, put it back
                await redis.rpush(DLQ_KEY, entry)
                failed += 1
    finally:
        await _close_redis(redis)

    _log.info("admin.dlq.requeued_all", total=total, requeued=requeued, failed=failed)
    await record_audit(
        request, action="dlq.requeued_all", total=total, requeued=requeued, failed=failed
    )
    return DlqRequeueAllResult(
        total=total,
        requeued=requeued,
        failed=failed,
        queue=PRIORITY_QUEUE,
        message=(
            f"{requeued} partida(s) reenviada(s) para processamento."
            if failed == 0
            else f"{requeued} reenviada(s), {failed} falhou(aram) e voltaram para a DLQ."
        ),
    )


@router.post(
    "/dlq/{match_id}/requeue",
    response_model=DlqRequeueResult,
    summary="Reprocessar partida com falha",
    response_model_by_alias=True,
    dependencies=[Depends(require_scope("dlq:write"))],
)
async def requeue_dlq(
    request: Request,
    match_id: str = Path(..., description="riotMatchId da partida com falha"),
) -> DlqRequeueResult:
    """Re-enqueue a failed match onto the priority arq queue.

    Removes the matching DLQ entry (by ``riotMatchId``) and enqueues a fresh
    ``process_match`` job on ``arena:priority`` — same ``enqueue_job`` pattern
    as the sweep pipeline and ``ingestion.py``, so ``PriorityWorker`` picks it
    up immediately rather than waiting for any cron tick. A requeue after a
    dead-letter gets a fresh ``MAX_TRIES`` budget automatically (arq's own
    ``job_try`` starts over for a new job id). Returns a 404 when the match is
    not present in the DLQ.
    """
    rt = _runtime()
    if rt.redis_factory is None or rt.arq_redis_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Fila indisponível para reprocessamento.",
        )
    from arena.workers.queues import DLQ_KEY, PRIORITY_QUEUE, PROCESS_MATCH_TASK

    # An arq-capable pool, not rt.redis_factory()'s plain redis.asyncio.Redis —
    # enqueue_job is an ArqRedis-only method.
    redis = await rt.arq_redis_factory()
    try:
        removed = await _remove_dlq_entry(redis, DLQ_KEY, match_id)
        if not removed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Partida não encontrada na DLQ.",
            )
        # Deliberately NOT the plain "process_match:{match_id}" job id used by
        # discovery: arq's own _job_id dedup collapses an enqueue whose id
        # already has a result cached (success OR failure) within the keep-
        # result window, which the dead-lettered job just left behind. Reusing
        # that id here would make this endpoint return 200 while silently
        # enqueuing nothing. The timestamp suffix guarantees a fresh job id
        # every time an operator asks for a requeue.
        await redis.enqueue_job(
            PROCESS_MATCH_TASK,
            match_id,
            _queue_name=PRIORITY_QUEUE,
            _job_id=f"{PROCESS_MATCH_TASK}:{match_id}:requeue:{int(time.time())}",
        )
    finally:
        await _close_redis(redis)

    _log.info("admin.dlq.requeued", matchId=match_id, queue=PRIORITY_QUEUE)
    await record_audit(request, action="dlq.requeued", target=match_id)
    return DlqRequeueResult(
        match_id=match_id,
        requeued=True,
        queue=PRIORITY_QUEUE,
        message="Partida reenviada para processamento.",
    )


@router.delete(
    "/dlq/{match_id}",
    response_model=DlqDiscardResult,
    summary="Descartar entrada da DLQ",
    response_model_by_alias=True,
    dependencies=[Depends(require_scope("dlq:write"))],
)
async def discard_dlq(
    request: Request,
    match_id: str = Path(..., description="riotMatchId da partida a descartar"),
) -> DlqDiscardResult:
    """Permanently discard a DLQ entry without reprocessing."""
    rt = _runtime()
    if rt.redis_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Fila indisponível.",
        )
    from arena.workers.queues import DLQ_KEY

    redis = rt.redis_factory()
    try:
        removed = await _remove_dlq_entry(redis, DLQ_KEY, match_id)
    finally:
        await _close_redis(redis)

    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Partida não encontrada na DLQ.",
        )
    _log.info("admin.dlq.discarded", matchId=match_id)
    await record_audit(request, action="dlq.discarded", target=match_id)
    return DlqDiscardResult(match_id=match_id, discarded=True, message="Entrada da DLQ descartada.")


async def _remove_dlq_entry(redis: Any, dlq_key: str, match_id: str) -> bool:
    """Remove the DLQ list entry whose payload matches ``match_id``.

    DLQ entries are JSON blobs; we scan the list, find the first whose
    ``riotMatchId``/``matchId`` equals the target, and ``LREM`` that exact value.
    """
    try:
        raw = await redis.lrange(dlq_key, 0, -1)
    except Exception:  # pragma: no cover
        return False
    for entry in raw:
        payload = _decode_json(entry)
        candidate = str(payload.get("riotMatchId") or payload.get("matchId") or "")
        if candidate == match_id:
            try:
                removed = await redis.lrem(dlq_key, 1, entry)
            except Exception:  # pragma: no cover
                return False
            return bool(removed)
    return False


# ===========================================================================
# Integrity review queue (proposal §4.3 — review flags / manual overrides)
# ===========================================================================


@router.get(
    "/integrity",
    response_model=list[AdminIntegrityItem],
    summary="Fila de revisão de integridade",
    response_model_by_alias=True,
    dependencies=[Depends(require_scope("telemetry:read"))],
)
async def list_integrity_queue(
    limit: int = Query(50, ge=1, le=500, description="Máximo de itens"),
) -> list[AdminIntegrityItem]:
    """Open (unreviewed) integrity events, most-recent first."""
    rt = _runtime()
    if rt.sessionmaker is None:
        return []
    try:
        from arena.db import models as md
    except Exception:  # pragma: no cover
        return []
    try:
        async with rt.sessionmaker() as session:
            from sqlalchemy import select

            rows = (
                await session.execute(
                    select(md.IntegrityEvent)
                    .where(md.IntegrityEvent.reviewed.is_(False))
                    .order_by(md.IntegrityEvent.created_at.desc())
                    .limit(limit)
                )
            ).scalars()
            return [
                AdminIntegrityItem(
                    id=str(ev.id),
                    player=str(ev.player_id) if ev.player_id is not None else "—",
                    reason=ev.flag_type,
                    severity=_SEVERITY_WIRE.get(ev.severity.value, "info"),
                    ts=ev.created_at.isoformat() if ev.created_at else _now_iso(),
                )
                for ev in rows
            ]
    except Exception:  # pragma: no cover
        _log.warning("admin.integrity.list_failed", exc_info=True)
        return []


@router.post(
    "/integrity/{event_id}/review",
    response_model=IntegrityReviewResult,
    summary="Revisar evento de integridade (override manual)",
    response_model_by_alias=True,
    dependencies=[Depends(require_scope("integrity:review"))],
)
async def review_integrity_event(
    request: Request,
    body: IntegrityReviewRequest,
    event_id: str = Path(..., description="ID do evento de integridade"),
) -> IntegrityReviewResult:
    """Mark an integrity event reviewed, optionally recording a manual override.

    The override decision and reviewer note are stored on the event's metadata
    JSONB so the audit trail is preserved; ``reviewed`` flips to true and the
    reviewer id is recorded.

    ``integrity:review`` (route-level) covers a plain reviewed-with-no-verdict
    pass; actually setting an eligible/ineligible override is the stronger
    action and additionally requires ``integrity:override`` — checked here,
    against the scopes ``require_scope`` already resolved onto
    ``request.state``, rather than adding a second route for the same
    endpoint.
    """
    if body.override and body.override != "none":
        scopes: frozenset[str] = getattr(request.state, "scopes", frozenset())
        if "integrity:override" not in scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Este operador não tem permissão para aplicar override manual.",
            )
    rt = _runtime()
    if rt.sessionmaker is None:
        raise _db_unavailable("revisão de integridade")
    import uuid as _uuid

    try:
        from arena.db import models as md

        async with rt.sessionmaker() as session:
            event = await _get_integrity_event(session, md, event_id)
            if event is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Evento de integridade não encontrado.",
                )
            meta = dict(event.metadata_ or {})
            review_meta: dict[str, Any] = {"reviewedAt": _now_iso()}
            if body.note:
                review_meta["note"] = body.note
            if body.override and body.override != "none":
                review_meta["override"] = body.override
            if body.reviewer_id:
                review_meta["reviewerId"] = body.reviewer_id
                try:
                    event.reviewer_id = _uuid.UUID(body.reviewer_id)
                except (ValueError, AttributeError):
                    review_meta["reviewerIdRaw"] = body.reviewer_id
            meta["review"] = review_meta
            event.metadata_ = meta
            event.reviewed = True
            await session.commit()
            _log.info(
                "admin.integrity.reviewed",
                eventId=event_id,
                override=body.override or "none",
            )
            has_override = bool(body.override and body.override != "none")
            await record_audit(
                request,
                action="integrity.override_applied" if has_override else "integrity.reviewed",
                target=event_id,
                override=body.override or "none",
            )
            return IntegrityReviewResult(
                event_id=event_id,
                reviewed=True,
                message="Evento de integridade revisado.",
            )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - DB unreachable / not migrated
        _log.warning("admin.integrity.review_failed", eventId=event_id, exc_info=True)
        raise _db_unavailable("revisão de integridade") from exc


async def _get_integrity_event(session: Any, md: Any, event_id: str) -> Any | None:
    """Fetch an integrity event by id.

    ``integrity_events`` is RANGE-partitioned with a composite PK
    ``(id, created_at)``; a plain ``session.get`` needs the full PK, so we query
    by id and take the single row.
    """
    from sqlalchemy import select

    return (
        await session.execute(
            select(md.IntegrityEvent).where(md.IntegrityEvent.id == event_id).limit(1)
        )
    ).scalar_one_or_none()


# ===========================================================================
# Worker runtime control (pause / resume) + player selection for priority sweep
# ===========================================================================


def _valid_worker_names() -> frozenset[str]:
    """Names accepted by pause/resume, from ``queues`` (single source of truth).

    Resolved lazily (like every other queue touch in this module) so admin.py
    stays importable without the worker deps. Sourcing it from
    :data:`arena.workers.queues.PAUSABLE_WORKERS` means a newly added pausable
    worker — e.g. ``backfill`` — is controllable from the admin console instead
    of 404-ing against a hardcoded list that drifted.
    """
    try:
        from arena.workers.queues import PAUSABLE_WORKERS

        return PAUSABLE_WORKERS
    except Exception:  # noqa: BLE001 - worker deps absent; fall back to the core pair
        return frozenset({"sweep", "priority_sweep"})


class WorkerControlResult(ArenaModel):
    worker: str
    status: str
    message: str


class PlayerSelectRequest(ArenaModel):
    is_selected: bool


class PlayerSelectResult(ArenaModel):
    player_id: str
    is_selected: bool
    message: str


async def _set_worker_enabled(worker_name: str, *, paused: bool) -> None:
    """Pause (set flag '0') or resume (delete flag) a worker via Redis."""
    rt = _runtime()
    if rt.redis_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis indisponível para controle de worker.",
        )
    from arena.workers.queues import worker_enabled_key

    redis = rt.redis_factory()
    try:
        if paused:
            await redis.set(worker_enabled_key(worker_name), "0")
        else:
            await redis.delete(worker_enabled_key(worker_name))
    except Exception as exc:  # noqa: BLE001 - Redis down/unreachable at call time
        # `redis_factory` being present only means redis-py is importable; the
        # connection is made lazily here. Surface the same 503 as a missing
        # factory instead of a 500 so the console shows "Redis indisponível"
        # rather than a generic server error.
        _log.warning("admin.worker.control_failed", worker=worker_name, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis indisponível para controle de worker.",
        ) from exc
    finally:
        await _close_redis(redis)


@router.post(
    "/workers/{worker_name}/pause",
    response_model=WorkerControlResult,
    response_model_by_alias=True,
    summary="Pausar um worker (ver PAUSABLE_WORKERS)",
    dependencies=[Depends(require_scope("workers:write"))],
)
async def pause_worker(
    request: Request,
    worker_name: str = Path(
        ..., description="sweep | priority_sweep | backfill | rearm | reconcile"
    ),
) -> WorkerControlResult:
    if worker_name not in _valid_worker_names():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Worker '{worker_name}' desconhecido."
        )
    await _set_worker_enabled(worker_name, paused=True)
    _log.info("admin.worker.paused", worker=worker_name)
    await record_audit(request, action="worker.paused", target=worker_name)
    return WorkerControlResult(
        worker=worker_name, status="paused", message=f"Worker '{worker_name}' pausado."
    )


@router.post(
    "/workers/{worker_name}/resume",
    response_model=WorkerControlResult,
    response_model_by_alias=True,
    summary="Retomar um worker pausado",
    dependencies=[Depends(require_scope("workers:write"))],
)
async def resume_worker(
    request: Request,
    worker_name: str = Path(
        ..., description="sweep | priority_sweep | backfill | rearm | reconcile"
    ),
) -> WorkerControlResult:
    if worker_name not in _valid_worker_names():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Worker '{worker_name}' desconhecido."
        )
    await _set_worker_enabled(worker_name, paused=False)
    _log.info("admin.worker.resumed", worker=worker_name)
    await record_audit(request, action="worker.resumed", target=worker_name)
    return WorkerControlResult(
        worker=worker_name, status="resumed", message=f"Worker '{worker_name}' retomado."
    )


@router.patch(
    "/players/{player_id}/select",
    response_model=PlayerSelectResult,
    response_model_by_alias=True,
    summary="Marcar/desmarcar jogador para o sweep prioritário",
    dependencies=[Depends(require_scope("workers:write"))],
)
async def set_player_selected(
    request: Request,
    body: PlayerSelectRequest,
    player_id: str = Path(..., description="UUID do jogador"),
) -> PlayerSelectResult:
    rt = _runtime()
    if rt.sessionmaker is None:
        raise _db_unavailable("seleção de jogador")
    try:
        from sqlalchemy import select

        from arena.db import models as md

        async with rt.sessionmaker() as session:
            player = (
                await session.execute(select(md.Player).where(md.Player.id == player_id).limit(1))
            ).scalar_one_or_none()
            if player is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Jogador não encontrado."
                )
            player.is_selected = body.is_selected
            await session.commit()
        _log.info("admin.player.select_updated", playerId=player_id, isSelected=body.is_selected)
        # Logged under the "worker." prefix (not "player.") — this toggles
        # priority-sweep eligibility, a workers:write action, not moderation.
        # Phase D's real moderation endpoint is what earns the player.* prefix.
        await record_audit(
            request, action="worker.player_selected", target=player_id, isSelected=body.is_selected
        )
        return PlayerSelectResult(
            player_id=player_id,
            is_selected=body.is_selected,
            message="Seleção do jogador atualizada.",
        )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - DB unreachable / not migrated
        _log.warning("admin.player.select_failed", playerId=player_id, exc_info=True)
        raise _db_unavailable("seleção de jogador") from exc


__all__ = ["router"]
