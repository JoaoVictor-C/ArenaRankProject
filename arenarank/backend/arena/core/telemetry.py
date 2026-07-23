"""OpenTelemetry setup stub.

Phase-1 scaffold: wires a ``TracerProvider`` with a service-named resource and,
when an OTLP endpoint is configured *and* tracing is enabled, an OTLP span
exporter. Otherwise it stays a no-op (the global provider returns no-op spans),
so local runs incur zero overhead and need no collector.

OpenTelemetry is an **optional** dependency (the ``[otel]`` extra). When it is not
installed this module degrades to no-ops instead of failing at import time, so the
API and workers boot without it (``pip install .`` is enough to run; install
``.[otel]`` to export traces).

Span/metric instrumentation of the FastAPI app, HTTP client, and DB is added in
later phases; this module only owns provider lifecycle and the ``get_tracer``
accessor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .config import settings
from .logging import get_logger

try:  # opentelemetry-api is optional (the ``[otel]`` extra).
    from opentelemetry import trace as _otel_trace
except ModuleNotFoundError:  # pragma: no cover - only exercised in otel-less installs
    _otel_trace = None

#: The OTel trace API, or ``None`` when opentelemetry is not installed. Typed
#: ``Any`` so the rest of the module degrades to no-ops without import errors.
trace: Any = _otel_trace

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider

_log = get_logger(__name__)
_configured = False


def configure_telemetry(
    *,
    service_name: str | None = None,
    endpoint: str | None = None,
    enabled: bool | None = None,
) -> None:
    """Install the global tracer provider.

    Idempotent. A no-op when opentelemetry is not installed, when tracing is
    disabled, or when no endpoint is set, so callers can always create spans
    without branching.
    """
    global _configured
    if _configured:
        return
    if trace is None:
        _log.info("telemetry.unavailable", reason="opentelemetry not installed ([otel] extra)")
        _configured = True
        return

    svc = service_name or settings.service_name
    otlp_endpoint = endpoint if endpoint is not None else settings.otel_exporter_otlp_endpoint
    is_enabled = enabled if enabled is not None else settings.otel_traces_enabled

    if not is_enabled or not otlp_endpoint:
        _log.info(
            "telemetry.disabled",
            reason="no_endpoint" if not otlp_endpoint else "disabled",
            service=svc,
        )
        _configured = True
        return

    # Imports are local so the SDK/exporter stay optional at runtime.
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider as _TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {
            "service.name": svc,
            "deployment.environment": settings.environment,
        }
    )
    provider: TracerProvider = _TracerProvider(resource=resource)

    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        _log.info("telemetry.enabled", endpoint=otlp_endpoint, service=svc)
    except Exception as exc:  # pragma: no cover - exporter optional / env-dependent
        _log.warning("telemetry.exporter_unavailable", error=str(exc), service=svc)

    trace.set_tracer_provider(provider)
    _configured = True


def get_tracer(name: str = "arena") -> Any:
    """Return a tracer from the global provider (no-op until configured).

    Returns ``None`` when opentelemetry is not installed (the ``[otel]`` extra).
    """
    if trace is None:
        return None
    return trace.get_tracer(name)


def current_trace_id_hex() -> str | None:
    """Return the active span's 32-char hex trace id, or ``None``.

    ``None`` when no span is sampled or when opentelemetry is not installed. Used
    by request middleware to align the log ``traceId`` with the live span.
    """
    if trace is None:
        return None
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx.is_valid:
        return None
    return format(ctx.trace_id, "032x")
