"""Structured JSON logging via structlog.

Every emitted line is a single JSON object carrying at least::

    {"level": ..., "service": ..., "traceId": ..., "timestamp": ..., "event": ...}

- ``timestamp`` is ISO-8601 UTC.
- ``traceId`` is bound per-request by the API middleware (and falls back to the
  active OpenTelemetry span's trace id when present); it is ``null`` outside a
  request scope.
- ``service`` is the configured service name.

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

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.EventRenamer("message"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging (uvicorn, sqlalchemy, etc.) through the same JSON sink.
    handler = logging.StreamHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.EventRenamer("message"),
                structlog.processors.JSONRenderer(),
            ],
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Tame the noisy uvicorn access logger; keep it but let it flow through JSON.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(noisy)
        lg.handlers.clear()
        lg.propagate = True


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
