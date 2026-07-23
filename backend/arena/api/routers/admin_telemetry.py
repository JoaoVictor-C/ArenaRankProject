"""Live worker/processor telemetry — real-time operator stream.

A **self-contained, additive** router that exposes the *real* runtime state of
the sweep pipeline workers (``sweep`` / ``priority_sweep`` / ``bulk_processor``)
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
``Depends(require_admin)`` itself — so it is safe even if included without the
blanket admin dependency the rest of ``/admin`` uses.

Wiring (one line in ``arena/api/app.py``)::

    from arena.api.routers.admin_telemetry import router as _admin_telemetry_router
    api_router.include_router(_admin_telemetry_router)

(The router self-applies ``require_admin``; no extra ``dependencies=`` needed.)

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

from arena.api.security import require_admin
from arena.core.config import settings
from arena.core.logging import get_logger
from arena.schemas.common import ArenaModel
from arena.workers import queues as Q

_log = get_logger("arena.api.admin.telemetry")

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


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
    #: Rotating progress cursor (sweep workers page through players by offset).
    cursor: int | None = None
    #: Redis key this worker feeds / drains.
    feeds: str | None = None
    #: Backlog this worker is responsible for (pending list depth it feeds/drains).
    pending: int
    #: In-flight retry entries this worker is tracking (bulk processor only).
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
    sweep_pending_priority: int
    sweep_pending_standard: int
    sweep_attempts_tracked: int
    top_players_pool: int
    total_backlog: int


class LiveSnapshot(ArenaModel):
    """A single real-time telemetry frame."""

    ts: str
    redis_available: bool
    workers: list[LiveWorker]
    queues: list[LiveQueue]
    pipeline: LivePipeline


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
        Q.SWEEP_CURSOR_KEY,
        Q.SWEEP_PENDING_STANDARD,
        "sweep_interval_minutes",
        "Varre todos os jogadores rastreados (paginado por cursor) e enfileira "
        "novas partidas na fila pendente padrão.",
    ),
    (
        "priority_sweep",
        "Sweep prioritário",
        Q.PRIORITY_SWEEP_CURSOR_KEY,
        Q.SWEEP_PENDING_PRIORITY,
        "priority_sweep_interval_minutes",
        "Varre o Top-N por CR + jogadores selecionados e enfileira na fila "
        "pendente prioritária (isento de backpressure).",
    ),
    (
        "bulk_processor",
        "Processador em lote",
        None,
        None,
        "bulk_processor_interval_minutes",
        "Drena as filas pendentes (prioritária primeiro) e processa cada partida "
        "com concorrência limitada; reenfileira/DLQ conforme as tentativas.",
    ),
)


async def _build_snapshot(redis: Any | None) -> LiveSnapshot:
    """Assemble one live telemetry frame. ``redis is None`` => degraded zeros."""
    if redis is None:
        pipeline = LivePipeline(
            priority_queue=0,
            standard_queue=0,
            dlq=0,
            sweep_pending_priority=0,
            sweep_pending_standard=0,
            sweep_attempts_tracked=0,
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
                attempts_tracked=0 if name == "bulk_processor" else None,
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
    pend_pri = await _safe_int(redis.llen(Q.SWEEP_PENDING_PRIORITY))
    pend_std = await _safe_int(redis.llen(Q.SWEEP_PENDING_STANDARD))
    attempts = await _safe_int(redis.hlen(Q.SWEEP_ATTEMPTS_KEY))
    top_pool = await _safe_int(redis.scard(Q.TOP_PLAYERS_SET))

    pipeline = LivePipeline(
        priority_queue=priority_q,
        standard_queue=standard_q,
        dlq=dlq,
        sweep_pending_priority=pend_pri,
        sweep_pending_standard=pend_std,
        sweep_attempts_tracked=attempts,
        top_players_pool=top_pool,
        total_backlog=priority_q + standard_q + pend_pri + pend_std,
    )

    queues = [
        LiveQueue(name=Q.PRIORITY_QUEUE, depth=priority_q, kind="zset", label="Fila prioritária (arq)"),
        LiveQueue(name=Q.STANDARD_QUEUE, depth=standard_q, kind="zset", label="Fila padrão (arq)"),
        LiveQueue(name=Q.DLQ_KEY, depth=dlq, kind="list", label="Dead-letter (DLQ)"),
        LiveQueue(
            name=Q.SWEEP_PENDING_PRIORITY,
            depth=pend_pri,
            kind="list",
            label="Pendente · sweep prioritário",
        ),
        LiveQueue(
            name=Q.SWEEP_PENDING_STANDARD,
            depth=pend_std,
            kind="list",
            label="Pendente · sweep padrão",
        ),
    ]

    workers = []
    for name, label, cursor_key, feeds, interval_attr, desc in _WORKER_DEFS:
        paused, active, ttl = await _worker_runtime(redis, name)
        cursor = await _safe_int(redis.get(cursor_key)) if cursor_key else None
        if name == "bulk_processor":
            pending = pend_pri + pend_std  # its input backlog
            attempts_tracked: int | None = attempts
            feeds_label: str | None = "arena:sweep:pending:* → process_match"
        else:
            pending = pend_pri if name == "priority_sweep" else pend_std
            attempts_tracked = None
            feeds_label = feeds
        workers.append(
            LiveWorker(
                name=name,
                label=label,
                enabled=not paused,
                paused=paused,
                active=active,
                tick_lock_ttl=ttl,
                cursor=cursor,
                feeds=feeds_label,
                pending=pending,
                attempts_tracked=attempts_tracked,
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
    """Return one real-time telemetry frame from Redis."""
    return await _snapshot()


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
    interval: float = Query(
        1.5, ge=0.5, le=10.0, description="Intervalo entre frames (segundos)."
    ),
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


__all__ = ["router"]
