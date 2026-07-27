"""Structured logging via structlog — JSON in production, human-readable in dev.

Every event carries at least ``level``, ``service``, ``traceId``, ``timestamp``.

- ``timestamp`` is ISO-8601 UTC.
- ``traceId`` is bound per-request by the API middleware (and falls back to the
  active OpenTelemetry span's trace id when present); it is ``null`` outside a
  request scope.
- ``service`` is the configured service name.

Rendering is environment-gated (``Settings.is_production``): production (and
staging, via the same flag) renders one JSON object per line — the shape a log
aggregator (Loki/CloudWatch) expects — while local/dev renders a colored,
aligned ``structlog.dev.ConsoleRenderer`` line instead, because a terminal
full of raw JSON objects is unreadable at the volume the sweep/processor
workers produce. This is why per-match/per-request logs must stay
*genuinely* worth a line at INFO: the console renderer makes them easier to
read, not fewer — noise reduction is a separate, deliberate choice at each
call site (see ``arena.workers.processor``/``ingestion`` for which events
were demoted to DEBUG for exactly this reason), not something this module
can paper over.

Call :func:`configure_logging` once at startup, then use
:func:`get_logger` everywhere.
"""

from __future__ import annotations

import logging
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from .config import settings

# Context var keys bound by middleware (see arena.api.app).
TRACE_ID_KEY = "traceId"
REQUEST_ID_KEY = "requestId"


def _add_service_name(service_name: str) -> Processor:
    """Processor factory that stamps the service name on every event."""

    def processor(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
        event_dict.setdefault("service", service_name)
        return event_dict

    return processor


def _ensure_trace_id(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
    """Guarantee a ``traceId`` field is always present (``None`` if unbound).

    The middleware binds the real value via ``structlog.contextvars``; this keeps
    the JSON shape stable for logs emitted outside any request.
    """
    if TRACE_ID_KEY not in event_dict:
        event_dict[TRACE_ID_KEY] = None
    return event_dict


def configure_logging(
    *,
    log_level: str | None = None,
    service_name: str | None = None,
) -> None:
    """Configure structlog + stdlib logging for JSON output.

    Idempotent: safe to call more than once (e.g. tests, reload).
    """
    level_name = (log_level or settings.log_level).upper()
    level = getattr(logging, level_name, logging.INFO)
    svc = service_name or settings.service_name

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        _add_service_name(svc),
        _ensure_trace_id,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # JSON for anything log-aggregator-shaped (prod/staging); a colored,
    # aligned console line for local dev — a terminal full of raw JSON is
    # unreadable at worker log volume, and nothing downstream parses it there.
    final_processors: list[Processor] = (
        [structlog.processors.EventRenamer("message"), structlog.processors.JSONRenderer()]
        if settings.is_production
        # force_colors: a container's stdout is a pipe, not a real TTY, so
        # ConsoleRenderer's own isatty()-based auto-detect would otherwise
        # always resolve to plain/no-color here regardless of `colors=`.
        else [structlog.dev.ConsoleRenderer(colors=True, force_colors=True)]
    )

    structlog.configure(
        processors=[*shared_processors, *final_processors],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging (uvicorn, sqlalchemy, etc.) through the same sink.
    handler = logging.StreamHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                *final_processors,
            ],
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Tame the noisy uvicorn access logger; keep it but let it flow through.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(noisy)
        lg.handlers.clear()
        lg.propagate = True

    # httpx/httpcore log one line per outbound Riot HTTP call at INFO by
    # default — at sweep/backfill volume that's thousands of near-identical
    # "HTTP Request: GET ... 200 OK" lines drowning out everything else, and
    # we already emit our own structured event for every call's outcome
    # (arena.riot.client._note_attempt -> metrics + limit_headers). Only
    # surface these loggers when something's actually wrong.
    for chatty in ("httpx", "httpcore"):
        logging.getLogger(chatty).setLevel(logging.WARNING)


#: Pass to every ``arq`` worker CLI invocation via ``--custom-log-dict
#: arena.core.logging.ARQ_LOG_CONFIG`` (see the arq worker commands in
#: docker-compose*.yml). Without this, ``arq``'s own CLI unconditionally
#: calls ``logging.config.dictConfig(default_log_config(...))`` on startup
#: (see ``arq/cli.py``) *after* this module has already run (the CLI imports
#: the WorkerSettings class — which is what triggers `configure_logging()` —
#: before it configures logging), attaching arq's own plain
#: ``"%(asctime)s: %(message)s"`` handler directly to the ``"arq"`` logger.
#: Since that logger's records still propagate to root afterward, every
#: arq-emitted line (job start/finish, worker banner) then printed TWICE:
#: once via arq's own plain handler, once via this module's structured one.
#: This dict gives the ``"arq"`` logger no handler of its own — it only
#: gets the level, and its records still propagate up to be rendered
#: consistently (colored in dev, JSON in prod) by `configure_logging()`'s
#: own root handler, same as every other stdlib logger.
ARQ_LOG_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "loggers": {"arq": {"handlers": [], "level": "INFO"}},
}


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


def bind_trace_context(*, trace_id: str, request_id: str) -> None:
    """Bind per-request identifiers into the structlog context."""
    structlog.contextvars.bind_contextvars(**{TRACE_ID_KEY: trace_id, REQUEST_ID_KEY: request_id})


def clear_trace_context() -> None:
    """Clear per-request identifiers from the structlog context."""
    structlog.contextvars.unbind_contextvars(TRACE_ID_KEY, REQUEST_ID_KEY)
