"""Live worker/processor telemetry — real-time operator stream.

A **self-contained, additive** router that exposes the *real* runtime state of
the sweep pipeline workers (``sweep`` / ``priority_sweep`` / ``backfill``)
and the queue/pipeline depths straight from Redis — the data the static
``/admin/overview`` payload only approximates.

It powers the standalone **admin-console** (``/admin-console``) real-time
dashboard:

* ``GET /admin/workers/live``    — one live snapshot (JSON).
* ``GET /admin/workers/stream``  — Server-Sent Events; the same snapshot pushed
  every ``interval`` seconds (default 1.5s) until the client disconnects.

Why a separate module (vs. extending ``admin.py``)
--------------------------------------------------
This file is purely additive: dropping it in and mounting it adds the two routes
without touching any existing handler. It is **self-gated** — the router carries
``Depends(require_scope("telemetry:read"))`` itself — so it is safe even if
included without any extra dependency the rest of ``/admin`` uses.

Wiring (one line in ``arena/api/app.py``)::

    from arena.api.routers.admin_telemetry import router as _admin_telemetry_router
    api_router.include_router(_admin_telemetry_router)

(The router self-applies ``require_scope("telemetry:read")``; no extra
``dependencies=`` needed.)

Everything degrades defensively: if Redis is unavailable the snapshot still
returns with ``redisAvailable: false`` and zeroed counters rather than 500-ing.
All JSON keys are camelCase (``ArenaModel``); user-facing strings are PT-BR.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from arena.api.rbac import require_scope
from arena.core.config import settings
from arena.core.logging import get_logger
from arena.schemas.common import ArenaModel
from arena.services import telemetry_snapshot
from arena.workers import queues as Q

_log = get_logger("arena.api.admin.telemetry")

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_scope("telemetry:read"))]
)


# ---------------------------------------------------------------------------
# DTOs (camelCase on the wire via ArenaModel).
# ---------------------------------------------------------------------------


class LiveWorker(ArenaModel):
    """Real runtime state of one cron-driven sweep-pipeline worker."""

    name: str
    label: str
    #: True unless the Redis enable flag is explicitly "0" (paused by an operator).
    enabled: bool
    paused: bool
    #: True while a tick is currently executing (the per-tick mutex is held).
    active: bool
    #: Seconds left on the active tick mutex (0 when idle).
    tick_lock_ttl: int
    #: Rotating progress cursor, when the worker has a numeric one. The standard
    #: sweep pages by keyset (last puuid) and therefore reports None.
    cursor: int | None = None
    #: Redis key this worker feeds / drains.
    feeds: str | None = None
    #: Backlog this worker is responsible for (pending list depth it feeds/drains).
    pending: int
    #: In-flight retry entries this worker is tracking. Unused today (arq's own
    #: per-job retry counters replaced the old manual tracking hash) — kept as
    #: an optional field so a future worker can populate it without a schema
    #: change.
    attempts_tracked: int | None = None
    #: Configured tick cadence (minutes).
    interval_minutes: int
    description: str


class LiveQueue(ArenaModel):
    """One queue/list depth with its Redis structure kind."""

    name: str
    depth: int
    kind: str  # "zset" | "list"
    label: str


class LivePipeline(ArenaModel):
    """Flat roll-up of every pipeline counter (handy for tiles + sparklines)."""

    priority_queue: int
    standard_queue: int
    dlq: int
    top_players_pool: int
    total_backlog: int


#: De onde um frame de telemetria veio. O console PRECISA disto: sem ele um
#: frame lido do snapshot é indistinguível de um ao vivo, e um snapshot velho
#: vira um número errado apresentado com confiança.
SOURCE_LIVE = "live"          # Redis deste processo (divide com os workers)
SOURCE_SNAPSHOT = "snapshot"  # tabela worker_telemetry, publicada pela outra caixa
SOURCE_UNAVAILABLE = "unavailable"  # nada publicado ainda, ou velho demais


class LiveSnapshot(ArenaModel):
    """A single real-time telemetry frame."""

    ts: str
    redis_available: bool
    workers: list[LiveWorker]
    queues: list[LiveQueue]
    pipeline: LivePipeline
    #: live | snapshot | unavailable — ver as constantes SOURCE_* acima.
    source: str = SOURCE_LIVE
    #: Quando o frame foi CAPTURADO. Igual a ``ts`` ao vivo; mais antigo quando
    #: vem do snapshot. É o que permite a UI dizer "visto há N min".
    as_of: str | None = None
    #: Idade do frame em segundos (0 ao vivo). ``None`` quando não há frame.
    age_seconds: int | None = None


# ---------------------------------------------------------------------------
# Redis resolution (defensive — mirrors admin.py's lazy runtime).
# ---------------------------------------------------------------------------


def _redis_factory() -> Any | None:
    try:
        from redis.asyncio import Redis

        return lambda: Redis.from_url(settings.redis_url)
    except Exception:  # pragma: no cover - redis not installed
        return None


async def _close_redis(redis: Any) -> None:
    try:
        aclose = getattr(redis, "aclose", None)
        if aclose is not None:
            await aclose()
        else:  # pragma: no cover - older redis-py
            await redis.close()
    except Exception:  # pragma: no cover
        pass


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Per-key safe readers — one bad/typed key never breaks the whole snapshot.
# ---------------------------------------------------------------------------


async def _safe_int(coro: Any) -> int:
    try:
        return int(await coro or 0)
    except Exception:  # noqa: BLE001 - WRONGTYPE / Redis down / key absent
        return 0


async def _worker_runtime(redis: Any, name: str) -> tuple[bool, bool, int]:
    """Return ``(paused, active, tick_lock_ttl)`` for *name* from Redis."""
    try:
        raw = await redis.get(Q.worker_enabled_key(name))
    except Exception:  # noqa: BLE001
        raw = None
    paused = raw in (b"0", "0")
    try:
        ttl = int(await redis.ttl(Q.worker_tick_lock_key(name)))
    except Exception:  # noqa: BLE001
        ttl = -2
    active = ttl != -2  # ttl == -2 => key absent => not ticking
    return paused, active, max(ttl, 0)


# Static worker descriptors: (name, label, cursor_key, feeds_key, interval_attr, desc).
_WORKER_DEFS: tuple[tuple[str, str, str | None, str | None, str, str], ...] = (
    (
        "sweep",
        "Sweep padrão",
        # Sem cursor numérico: a paginação virou keyset sobre o puuid (um insert
        # atrás do offset antigo pulava um jogador rastreado pelo resto da
        # rotação). Expor o puuid aqui daria 0 via _safe_int — melhor omitir.
        None,
        Q.STANDARD_QUEUE,
        "sweep_interval_minutes",
        "Varre todos os jogadores rastreados (paginado por cursor keyset sobre "
        "o puuid) e enfileira novas partidas na fila arq padrão.",
    ),
    (
        "priority_sweep",
        "Sweep prioritário",
        Q.PRIORITY_SWEEP_CURSOR_KEY,
        Q.PRIORITY_QUEUE,
        "priority_sweep_interval_minutes",
        "Varre o Top-N por CR + jogadores selecionados e enfileira na fila "
        "arq prioritária (isenta de backpressure).",
    ),
    (
        "backfill",
        "Backfill de novos jogadores",
        None,
        Q.BACKFILL_PENDING_LIST,
        "backfill_interval_minutes",
        "Importa o histórico de contas vistas pela primeira vez (registradas "
        "pelo write path) e enfileira as partidas encontradas na fila arq "
        "padrão. Segura quando a fila arq está acima da marca d'água.",
    ),
)


async def _build_snapshot(redis: Any | None) -> LiveSnapshot:
    """Assemble one live telemetry frame. ``redis is None`` => degraded zeros."""
    if redis is None:
        pipeline = LivePipeline(
            priority_queue=0,
            standard_queue=0,
            dlq=0,
            top_players_pool=0,
            total_backlog=0,
        )
        workers = [
            LiveWorker(
                name=name,
                label=label,
                enabled=True,
                paused=False,
                active=False,
                tick_lock_ttl=0,
                cursor=None,
                feeds=feeds,
                pending=0,
                attempts_tracked=None,
                interval_minutes=int(getattr(settings, interval_attr, 0)),
                description=desc,
            )
            for name, label, _cursor, feeds, interval_attr, desc in _WORKER_DEFS
        ]
        return LiveSnapshot(
            ts=_now_iso(),
            redis_available=False,
            workers=workers,
            queues=[],
            pipeline=pipeline,
        )

    # --- pipeline counters (each read isolated) ---
    priority_q = await _safe_int(redis.zcard(Q.PRIORITY_QUEUE))
    standard_q = await _safe_int(redis.zcard(Q.STANDARD_QUEUE))
    dlq = await _safe_int(redis.llen(Q.DLQ_KEY))
    backfill_pending = await _safe_int(redis.llen(Q.BACKFILL_PENDING_LIST))
    top_pool = await _safe_int(redis.scard(Q.TOP_PLAYERS_SET))

    pipeline = LivePipeline(
        priority_queue=priority_q,
        standard_queue=standard_q,
        dlq=dlq,
        top_players_pool=top_pool,
        total_backlog=priority_q + standard_q,
    )

    queues = [
        LiveQueue(
            name=Q.PRIORITY_QUEUE, depth=priority_q, kind="zset", label="Fila prioritária (arq)"
        ),
        LiveQueue(name=Q.STANDARD_QUEUE, depth=standard_q, kind="zset", label="Fila padrão (arq)"),
        LiveQueue(name=Q.DLQ_KEY, depth=dlq, kind="list", label="Dead-letter (DLQ)"),
    ]

    # Per-worker backlog: each entry's OWN output — sweep/priority_sweep feed
    # the arq queues directly now (no separate pending-list stage), backfill
    # still drains its own list.
    _PENDING_BY_WORKER: dict[str, int] = {
        "sweep": standard_q,
        "priority_sweep": priority_q,
        "backfill": backfill_pending,
    }

    workers = []
    for name, label, cursor_key, feeds, interval_attr, desc in _WORKER_DEFS:
        paused, active, ttl = await _worker_runtime(redis, name)
        cursor = await _safe_int(redis.get(cursor_key)) if cursor_key else None
        workers.append(
            LiveWorker(
                name=name,
                label=label,
                enabled=not paused,
                paused=paused,
                active=active,
                tick_lock_ttl=ttl,
                cursor=cursor,
                feeds=feeds,
                pending=_PENDING_BY_WORKER.get(name, 0),
                attempts_tracked=None,
                interval_minutes=int(getattr(settings, interval_attr, 0)),
                description=desc,
            )
        )

    return LiveSnapshot(
        ts=_now_iso(),
        redis_available=True,
        workers=workers,
        queues=queues,
        pipeline=pipeline,
    )


async def _snapshot() -> LiveSnapshot:
    """One snapshot with a short-lived Redis connection."""
    factory = _redis_factory()
    if factory is None:
        return await _build_snapshot(None)
    redis = factory()
    try:
        return await _build_snapshot(redis)
    finally:
        await _close_redis(redis)


# ---------------------------------------------------------------------------
# GET /admin/workers/live — single frame
# ---------------------------------------------------------------------------


@router.get(
    "/workers/live",
    response_model=LiveSnapshot,
    response_model_by_alias=True,
    summary="Snapshot ao vivo dos workers e filas (Redis)",
)
async def workers_live() -> LiveSnapshot:
    """Um frame de telemetria — ao vivo, ou do snapshot publicado pela caixa de
    workers quando esta API não divide o Redis com eles.

    Sem essa bifurcação a API do EC2 lia o PRÓPRIO Redis (que não tem fila,
    heartbeat nem token-bucket) e respondia zeros: fila vazia, todo worker
    ``active: false``. Nunca ficava sem resposta — ficava com a resposta errada.
    """
    if telemetry_snapshot.reads_from_db():
        return await _live_from_snapshot()
    frame = await _snapshot()
    frame.source = SOURCE_LIVE
    frame.as_of = frame.ts
    frame.age_seconds = 0
    return frame


# ---------------------------------------------------------------------------
# Leitura via snapshot (caixa que NÃO divide o Redis com os workers)
# ---------------------------------------------------------------------------


def _empty_live(source: str, age: int | None, as_of: str | None) -> LiveSnapshot:
    """Frame vazio marcado como indisponível.

    Deliberadamente NÃO é um frame de zeros: ``source`` diz à UI que não há
    dado, para ela mostrar "indisponível" em vez de desenhar uma fila vazia e
    workers mortos que não existem.
    """
    return LiveSnapshot(
        ts=_now_iso(),
        redis_available=False,
        workers=[],
        queues=[],
        pipeline=LivePipeline(
            priority_queue=0, standard_queue=0, dlq=0, top_players_pool=0, total_backlog=0
        ),
        source=source,
        as_of=as_of,
        age_seconds=age,
    )


async def _read_snapshot() -> Any:
    """Último snapshot publicado, ou ``None`` (banco fora / nada publicado)."""
    try:
        from arena.db.session import get_sessionmaker

        async with get_sessionmaker()() as session:
            return await telemetry_snapshot.read_snapshot(session)
    except Exception:  # noqa: BLE001 - telemetria nunca derruba o console
        _log.warning("telemetry.snapshot_read_failed", exc_info=True)
        return None


async def _live_from_snapshot() -> LiveSnapshot:
    snap = await _read_snapshot()
    if snap is None:
        return _empty_live(SOURCE_UNAVAILABLE, None, None)
    as_of = snap.as_of.isoformat()
    if snap.stale:
        # Existe, mas é velho demais para passar por estado atual. A idade vai
        # junto para a UI poder dizer há quanto tempo a caixa sumiu.
        return _empty_live(SOURCE_UNAVAILABLE, snap.age_seconds, as_of)
    raw = (snap.payload or {}).get(telemetry_snapshot.LIVE_KEY)
    if not raw:
        return _empty_live(SOURCE_UNAVAILABLE, snap.age_seconds, as_of)
    try:
        frame = LiveSnapshot.model_validate(raw)
    except Exception:  # noqa: BLE001 - payload de uma versão incompatível
        _log.warning("telemetry.snapshot_live_invalid", exc_info=True)
        return _empty_live(SOURCE_UNAVAILABLE, snap.age_seconds, as_of)
    frame.source = SOURCE_SNAPSHOT
    frame.as_of = as_of
    frame.age_seconds = snap.age_seconds
    return frame


async def _riot_usage_from_snapshot() -> RiotUsage:
    snap = await _read_snapshot()
    empty = RiotUsage(
        ts=_now_iso(),
        key_suffix="—",
        key_configured=False,
        headroom=settings.riot_bucket_headroom,
        buckets=[],
        requests_last_minute=0,
        requests_last_hour=0,
        rate_limited_last_hour=0,
        errors_last_hour=0,
        source=SOURCE_UNAVAILABLE,
    )
    if snap is None:
        return empty
    empty.as_of = snap.as_of.isoformat()
    empty.age_seconds = snap.age_seconds
    if snap.stale:
        return empty
    raw = (snap.payload or {}).get(telemetry_snapshot.RIOT_KEY)
    if not raw:
        return empty
    try:
        usage = RiotUsage.model_validate(raw)
    except Exception:  # noqa: BLE001
        _log.warning("telemetry.snapshot_riot_invalid", exc_info=True)
        return empty
    usage.source = SOURCE_SNAPSHOT
    usage.as_of = snap.as_of.isoformat()
    usage.age_seconds = snap.age_seconds
    return usage


async def build_publish_payload() -> dict[str, Any]:
    """Frame completo para a caixa de workers publicar (scheduler).

    Reusa EXATAMENTE os mesmos construtores das rotas ao vivo, para o que o EC2
    lê não poder divergir do que a caixa de workers mostraria de si mesma.
    """
    live = await _snapshot()
    live.source = SOURCE_SNAPSHOT
    riot = await _build_riot_usage()
    riot.source = SOURCE_SNAPSHOT
    return {
        telemetry_snapshot.LIVE_KEY: live.model_dump(by_alias=True, mode="json"),
        telemetry_snapshot.RIOT_KEY: riot.model_dump(by_alias=True, mode="json"),
    }


# ---------------------------------------------------------------------------
# GET /admin/workers/stream — Server-Sent Events
# ---------------------------------------------------------------------------


async def _event_stream(interval: float) -> AsyncIterator[bytes]:
    """Yield SSE frames until the client disconnects.

    One Redis connection is held for the stream's lifetime (re-used each tick)
    rather than reconnecting per frame. A leading comment frame opens the stream
    immediately so the client flips to "live" without waiting a full interval.
    """
    factory = _redis_factory()
    redis = factory() if factory is not None else None
    yield b": connected\n\n"
    try:
        while True:
            try:
                snap = await _build_snapshot(redis)
                payload = json.dumps(snap.model_dump(by_alias=True), ensure_ascii=False)
                yield f"event: telemetry\ndata: {payload}\n\n".encode()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - never kill the stream on one bad frame
                _log.warning("admin.telemetry.frame_failed", exc_info=True)
                yield b": frame-error\n\n"
            await asyncio.sleep(interval)
    except asyncio.CancelledError:  # pragma: no cover - normal client disconnect
        raise
    finally:
        if redis is not None:
            await _close_redis(redis)


@router.get(
    "/workers/stream",
    summary="Stream SSE de telemetria ao vivo (push a cada ~1,5s)",
)
async def workers_stream(
    interval: float = Query(1.5, ge=0.5, le=10.0, description="Intervalo entre frames (segundos)."),
) -> StreamingResponse:
    """Server-Sent Events stream of live telemetry frames.

    Consume from the browser via ``fetch`` (so the ``X-Admin-Key`` header can be
    sent) and parse the ``text/event-stream`` body, or via ``EventSource`` if you
    instead front this with a key-bearing proxy.
    """
    return StreamingResponse(
        _event_stream(interval),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering (nginx)
        },
    )


# ---------------------------------------------------------------------------
# GET /admin/riot/usage — Riot key consumption
# ---------------------------------------------------------------------------


class RiotObservedWindow(ArenaModel):
    """What Riot itself reported for a window, via its rate-limit headers.

    This is ground truth, unlike the bucket gauges below which are our *model*
    of Riot's accounting. When the two disagree, this one is right.
    """

    limit: int
    seconds: int
    count: int
    utilization: float
    #: Epoch seconds of the response this came from (staleness indicator).
    observed_at: float


class RiotBucketUsage(ArenaModel):
    """One Riot rate-limit bucket: how much of the window is currently spent."""

    name: str
    label: str
    #: Requests the limiter will actually allow per window (after headroom).
    capacity: int
    #: Riot's advertised ceiling for this window, before our headroom margin.
    advertised: int
    #: Window length in seconds (Riot's per-method limit period).
    window_seconds: float
    #: Tokens left right now (refills continuously).
    available: int
    #: capacity - available.
    used: int
    #: used / capacity, 0..1. The gauge the console renders.
    utilization: float
    #: Calls counted in the last 60s / 60min (from the metrics counters).
    last_minute: int
    last_hour: int
    #: Riot's own reading for this window; absent until a call has been made.
    observed: RiotObservedWindow | None = None
    #: Set when the configured capacity exceeds what Riot advertises (PT-BR).
    drift: str | None = None


class RiotUsage(ArenaModel):
    """Riot API key consumption — live buckets + recent call counts."""

    ts: str
    #: Last 8 chars of the key in use, so operators can tell keys apart without
    #: the secret ever leaving the server.
    key_suffix: str
    key_configured: bool
    #: Fraction of Riot's advertised limits the limiter is allowed to spend.
    headroom: float
    buckets: list[RiotBucketUsage]
    #: Totals across all endpoints.
    requests_last_minute: int
    requests_last_hour: int
    rate_limited_last_hour: int
    errors_last_hour: int
    #: Every bucket whose configuration disagrees with Riot's headers. Empty is
    #: the healthy state; non-empty means the key is being over-driven.
    drift_warnings: list[str] = []
    #: live | snapshot | unavailable — mesma semântica de LiveSnapshot.source.
    source: str = SOURCE_LIVE
    as_of: str | None = None
    age_seconds: int | None = None


_BUCKET_LABELS: dict[str, str] = {
    "account-v1": "Contas (account-v1)",
    "match-v5:ids": "IDs de partida (match-v5)",
    "match-v5:match": "Detalhe de partida (match-v5)",
    "app": "Limite global do app",
}


async def _build_riot_usage() -> RiotUsage:
    """Report Riot key consumption without ever exposing the key itself.

    Bucket fill is read straight from the limiter's Redis hashes (the same state
    that gates real calls), so it reflects what the workers are actually
    spending. Call counts come from the minute-bucketed metrics counters.
    """
    from arena.core import metrics
    from arena.riot import limit_headers as lh
    from arena.riot.rate_limit import default_arena_buckets

    api_key = settings.riot_api_key
    suffix = api_key[-8:] if api_key else "anon"
    configs = default_arena_buckets(
        app_capacity=settings.riot_app_bucket_capacity,
        app_refill_seconds=settings.riot_app_bucket_refill_seconds,
        match_v5_capacity=settings.riot_match_v5_bucket_capacity,
        match_v5_refill_seconds=settings.riot_match_v5_bucket_refill_seconds,
        headroom=settings.riot_bucket_headroom,
    )

    factory = _redis_factory()
    redis = factory() if factory is not None else None
    try:
        events = [metrics.EVENT_RIOT_REQUEST, metrics.EVENT_RIOT_429, metrics.EVENT_RIOT_ERROR]
        events += [f"{metrics.EVENT_RIOT_REQUEST}:{name}" for name in configs]
        hourly = await metrics.series(redis, events, 60)
        observed = await lh.read_observed(redis, suffix, [*configs, lh.APP_SCOPE])

        buckets: list[RiotBucketUsage] = []
        drift_warnings: list[str] = []
        for name, cfg in configs.items():
            available = cfg.capacity
            if redis is not None:
                try:
                    raw = await redis.hget(f"riot:ratelimit:{suffix}:{name}", "tokens")
                    if raw is not None:
                        available = max(0, min(cfg.capacity, int(float(raw))))
                except Exception:  # noqa: BLE001 - absent/typed key => full bucket
                    available = cfg.capacity
            per_bucket = hourly.get(f"{metrics.EVENT_RIOT_REQUEST}:{name}", [0] * 60)
            used = max(0, cfg.capacity - available)

            # Riot's own reading for this bucket, when we have one. The app-wide
            # scope stores its windows under `app`; method buckets under their
            # own name.
            snapshot = observed.get(lh.APP_SCOPE if name == "app" else name)
            windows = (snapshot.app if name == "app" else snapshot.method) if snapshot else ()
            window = next((w for w in windows if w.seconds == int(round(cfg.refill_seconds))), None)
            drift = lh.detect_drift(
                windows, capacity=cfg.advertised, refill_seconds=cfg.refill_seconds
            )
            if drift:
                drift_warnings.append(f"{_BUCKET_LABELS.get(name, name)}: {drift}")

            buckets.append(
                RiotBucketUsage(
                    name=name,
                    label=_BUCKET_LABELS.get(name, name),
                    capacity=cfg.capacity,
                    advertised=cfg.advertised,
                    window_seconds=cfg.refill_seconds,
                    available=available,
                    used=used,
                    utilization=(used / cfg.capacity) if cfg.capacity else 0.0,
                    last_minute=per_bucket[-1] if per_bucket else 0,
                    last_hour=sum(per_bucket),
                    observed=(
                        RiotObservedWindow(
                            limit=window.limit,
                            seconds=window.seconds,
                            count=window.count,
                            utilization=window.utilization,
                            observed_at=snapshot.observed_at if snapshot else 0.0,
                        )
                        if window is not None
                        else None
                    ),
                    drift=drift,
                )
            )

        req = hourly.get(metrics.EVENT_RIOT_REQUEST, [0] * 60)
        return RiotUsage(
            ts=_now_iso(),
            key_suffix=suffix,
            key_configured=bool(api_key),
            headroom=settings.riot_bucket_headroom,
            buckets=buckets,
            requests_last_minute=req[-1] if req else 0,
            requests_last_hour=sum(req),
            rate_limited_last_hour=sum(hourly.get(metrics.EVENT_RIOT_429, [])),
            errors_last_hour=sum(hourly.get(metrics.EVENT_RIOT_ERROR, [])),
            drift_warnings=drift_warnings,
        )
    finally:
        if redis is not None:
            await _close_redis(redis)


@router.get(
    "/riot/usage",
    response_model=RiotUsage,
    response_model_by_alias=True,
    summary="Consumo da chave da Riot (buckets de rate limit + chamadas recentes)",
)
async def riot_usage() -> RiotUsage:
    """Uso da chave da Riot — ao vivo, ou do snapshot publicado pela caixa de
    workers quando esta API não divide o Redis com eles (ver
    ``services/telemetry_snapshot``)."""
    if telemetry_snapshot.reads_from_db():
        return await _riot_usage_from_snapshot()
    usage = await _build_riot_usage()
    usage.source = SOURCE_LIVE
    usage.as_of = usage.ts
    return usage


# ---------------------------------------------------------------------------
# GET /admin/stats/series — backend statistics over time
# ---------------------------------------------------------------------------


class StatSeries(ArenaModel):
    """One named counter sampled per minute, oldest value first."""

    event: str
    label: str
    points: list[int]
    total: int


class StatsSeries(ArenaModel):
    """Minute-resolution counters over a trailing window."""

    ts: str
    #: Window length actually returned (minutes).
    minutes: int
    #: Epoch-minute of the newest point, so the client can label the x axis.
    end_minute: int
    series: list[StatSeries]


_EVENT_LABELS: dict[str, str] = {
    "match.processed": "Partidas processadas",
    "match.filtered": "Partidas filtradas",
    "match.skipped": "Partidas ignoradas",
    "match.failed": "Falhas de processamento",
    "sweep.enqueued": "Partidas descobertas",
    "riot.request": "Chamadas à Riot",
    "riot.rate_limited": "429 da Riot",
    "riot.error": "Erros da Riot",
}


@router.get(
    "/stats/series",
    response_model=StatsSeries,
    response_model_by_alias=True,
    summary="Estatísticas do backend ao longo do tempo (resolução de 1 minuto)",
)
async def stats_series(
    minutes: int = Query(60, ge=1, le=1440, description="Tamanho da janela em minutos (máx. 24h)."),
) -> StatsSeries:
    """Trailing per-minute counters for the console's over-time charts.

    Series are zero-filled to exactly *minutes* points so the client can plot
    them without gap handling.
    """
    from arena.core import metrics

    factory = _redis_factory()
    redis = factory() if factory is not None else None
    try:
        data = await metrics.series(redis, metrics.DEFAULT_EVENTS, minutes)
    finally:
        if redis is not None:
            await _close_redis(redis)

    return StatsSeries(
        ts=_now_iso(),
        minutes=minutes,
        end_minute=metrics.current_minute(),
        series=[
            StatSeries(
                event=event,
                label=_EVENT_LABELS.get(event, event),
                points=points,
                total=sum(points),
            )
            for event, points in data.items()
        ],
    )


__all__ = ["router"]
