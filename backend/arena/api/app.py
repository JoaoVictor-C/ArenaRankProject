"""FastAPI application factory.

Wires the cross-cutting concerns for the arenarank API:

- versioned prefix ``/api/v1`` (an empty ``api_router`` placeholder; routers
  arrive in Phase 3);
- CORS for the Vite dev server;
- JSON error handlers producing RFC-style bodies (``404 {detail}``, ``422``);
- a lightweight ``GET /healthz`` liveness probe (outside the versioned prefix);
- structured-logging middleware that binds a request id + traceId and emits one
  ``http.request`` access line per request.

All user-facing strings (error messages) are PT-BR per project contract; the
JSON envelope keys (``detail``, ``requestId``, ``traceId``) are camelCase.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from arena.core.config import Settings, settings
from arena.core.logging import (
    bind_trace_context,
    clear_trace_context,
    configure_logging,
    get_logger,
)
from arena.core.telemetry import configure_telemetry, current_trace_id_hex

if TYPE_CHECKING:
    from fastapi import APIRouter as _APIRouter

from fastapi import APIRouter

API_V1_PREFIX = "/api/v1"
REQUEST_ID_HEADER = "x-request-id"

# Starlette renamed the 422 constant; prefer the new name, fall back gracefully.
HTTP_422 = getattr(
    status,
    "HTTP_422_UNPROCESSABLE_CONTENT",
    status.HTTP_422_UNPROCESSABLE_ENTITY,
)

_log = get_logger("arena.api")

# ---------------------------------------------------------------------------
# Versioned router. Per-contract routers attach here; mounting them on a single
# ``api_router`` keeps the wiring stable and OpenAPI tags coherent. Routers are
# included defensively so the app still boots if an optional router's runtime
# deps are absent in a given environment.
# ---------------------------------------------------------------------------
api_router: _APIRouter = APIRouter()

try:
    from arena.api.routers import (
        champions_router as _champions_router,
        leaderboard_router as _leaderboard_router,
        match_router as _match_router,
        meta_router as _meta_router,
        player_router as _player_router,
    )

    api_router.include_router(_leaderboard_router)
    api_router.include_router(_player_router)
    api_router.include_router(_match_router)
    api_router.include_router(_champions_router)
    api_router.include_router(_meta_router)
except Exception:  # pragma: no cover - import-order / optional-dep tolerance
    _log.warning("api.router.read_api_unavailable", exc_info=True)

try:
    from arena.api.routers.search import router as _search_router

    api_router.include_router(_search_router)
except Exception:  # pragma: no cover - import-order / optional-dep tolerance
    _log.warning("api.router.search_unavailable", exc_info=True)

try:
    from arena.api.routers.admin import router as _admin_router
    from arena.api.security import require_admin as _require_admin

    # Gate the entire operator surface (overview + season/DLQ/integrity ops).
    api_router.include_router(_admin_router, dependencies=[Depends(_require_admin)])
except Exception:  # pragma: no cover - import-order / optional-dep tolerance
    _log.warning("api.router.admin_unavailable", exc_info=True)

try:
    from arena.api.routers.admin_telemetry import router as _admin_telemetry_router

    # Live worker/processor telemetry (admin console). The router self-applies
    # ``require_admin`` so no extra dependency is needed here.
    api_router.include_router(_admin_telemetry_router)
except Exception:  # pragma: no cover - import-order / optional-dep tolerance
    _log.warning("api.router.admin_telemetry_unavailable", exc_info=True)

try:
    from arena.tournaments.router import router as _tournaments_router

    api_router.include_router(_tournaments_router)
except Exception:  # pragma: no cover - import-order / optional-dep tolerance
    _log.warning("api.router.tournaments_unavailable", exc_info=True)

try:
    from arena.api.routers.payments import router as _payments_router

    # Router self-applies require_admin on every route.
    api_router.include_router(_payments_router)
except Exception:  # pragma: no cover - import-order / optional-dep tolerance
    _log.warning("api.router.payments_unavailable", exc_info=True)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown hooks. Telemetry is initialized lazily and idempotently.

    Preloads the Data Dragon (ddragon) champion map + version into the singleton's
    in-process cache so request handlers resolve real champion names/icon URLs
    synchronously (no network on the hot path). ddragon is fully optional: a warm
    failure (offline CDN, no Redis) is swallowed and the handlers degrade to the
    gradient ``avatar`` placeholders — the API still boots.
    """
    configure_telemetry()
    try:
        from arena.ddragon import warm_ddragon

        summary = await warm_ddragon()
        _log.info("api.ddragon.warmed", **summary)
    except Exception:  # pragma: no cover - ddragon is best-effort / optional
        _log.warning("api.ddragon.warm_failed", exc_info=True)
    _log.info("api.startup", env=settings.environment)
    yield
    try:
        from arena.api.deps import close_redis

        await close_redis()
    except Exception:  # pragma: no cover - best-effort teardown
        _log.warning("api.redis.close_failed", exc_info=True)
    _log.info("api.shutdown")


def _new_request_id(request: Request) -> str:
    """Honor an inbound request id header, else mint a new one."""
    incoming = request.headers.get(REQUEST_ID_HEADER)
    return incoming or uuid.uuid4().hex


async def _logging_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable["JSONResponse"]],
) -> "JSONResponse":
    """Bind request/trace context, time the request, emit one access log line."""
    request_id = _new_request_id(request)
    # Prefer the live span's trace id so logs correlate with traces when sampled.
    trace_id = current_trace_id_hex() or request_id

    bind_trace_context(trace_id=trace_id, request_id=request_id)
    request.state.request_id = request_id
    request.state.trace_id = trace_id

    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        _log.exception(
            "http.request.error",
            method=request.method,
            path=request.url.path,
            durationMs=duration_ms,
        )
        clear_trace_context()
        raise

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    response.headers[REQUEST_ID_HEADER] = request_id
    response.headers["x-trace-id"] = trace_id
    _log.info(
        "http.request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        durationMs=duration_ms,
    )
    clear_trace_context()
    return response


def _error_body(request: Request, detail: object) -> dict[str, object]:
    """Build the standard camelCase JSON error envelope."""
    return {
        "detail": detail,
        "requestId": getattr(request.state, "request_id", None),
        "traceId": getattr(request.state, "trace_id", None),
    }


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """RFC-style handler for HTTPException (incl. 404 ``{detail}``)."""
    detail = exc.detail if exc.detail else "Recurso não encontrado."
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(request, detail),
        headers=getattr(exc, "headers", None),
    )


async def _not_found_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Explicit 404 envelope with a PT-BR default message."""
    detail = exc.detail if exc.detail and exc.detail != "Not Found" else "Recurso não encontrado."
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=_error_body(request, detail),
    )


async def _validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422 handler exposing the per-field validation errors under ``detail``."""
    return JSONResponse(
        status_code=HTTP_422,
        content={
            **_error_body(request, "Dados de requisição inválidos."),
            "errors": exc.errors(),
        },
    )


def create_app(app_settings: Settings | None = None) -> FastAPI:
    """Build and return the configured FastAPI application."""
    cfg = app_settings or settings

    configure_logging(log_level=cfg.log_level, service_name=cfg.service_name)

    app = FastAPI(
        title="arenarank API",
        version="0.1.0",
        description="API gamificada de ranking (CRS) — arenarank.",
        lifespan=_lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Response cache (T0.3) — registered FIRST so it sits innermost: cache
    # hits still cross CORS + logging above, but nunca abrem sessão de DB.
    from arena.api.cache import ResponseCacheMiddleware, build_rules

    app.add_middleware(ResponseCacheMiddleware, rules=build_rules(cfg))

    # CORS — leitura pública SEM cookies/credenciais, ACAO fixo "*" (T1.1).
    # Motivo: a Cloudflare ignora ``Vary`` no cache de edge; com credenciais +
    # lista de origens o ACAO ecoado por origem envenenaria o cache entre
    # origens. A chave de admin viaja no header X-Admin-Key (não é credencial
    # CORS) e continua funcionando com allow_headers "*".
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER, "x-trace-id"],
    )

    # Structured-logging middleware (request id + traceId).
    app.middleware("http")(_logging_middleware)

    # JSON error handlers.
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        RequestValidationError,
        _validation_exception_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(status.HTTP_404_NOT_FOUND, _not_found_handler)  # type: ignore[arg-type]

    # Liveness probe (outside the versioned prefix).
    @app.get("/healthz", tags=["meta"], summary="Liveness probe")
    async def healthz() -> dict[str, object]:
        out: dict[str, object] = {
            "status": "ok",
            "service": cfg.service_name,
            "environment": cfg.environment,
        }
        if cfg.replica_lag_check:
            # T3.1: idade do último apply da replicação lógica (réplica EC2).
            # Best-effort: DB fora não derruba o probe de liveness.
            from arena.services.replication_status import replica_sync_status

            try:
                from arena.db.session import get_sessionmaker

                async with get_sessionmaker()() as session:
                    sync = await replica_sync_status(session)
            except Exception:
                _log.warning("api.healthz.replica_probe_failed", exc_info=True)
                sync = None
            if sync is None or sync.last_sync_at is None:
                out["replica"] = {"status": "unknown", "lastSyncAt": None, "lagSeconds": None}
            else:
                out["replica"] = {
                    "status": "ok",
                    "lastSyncAt": sync.last_sync_at.isoformat(),
                    "lagSeconds": round(sync.lag_seconds or 0.0, 3),
                }
        return out

    # Mount the (empty) versioned router. Phase 3 attaches real routes here.
    app.include_router(api_router, prefix=API_V1_PREFIX)

    return app


# Module-level ASGI app for ``uvicorn arena.api.app:app``.
app = create_app()
