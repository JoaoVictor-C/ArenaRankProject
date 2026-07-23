"""Core infrastructure: settings, structured logging, telemetry.

Re-exports the most commonly used handles so callers can write
``from arena.core import settings, get_logger``.
"""

from __future__ import annotations

from .config import Settings, get_settings, settings
from .logging import configure_logging, get_logger
from .telemetry import configure_telemetry, get_tracer

__all__ = [
    "Settings",
    "get_settings",
    "settings",
    "configure_logging",
    "get_logger",
    "configure_telemetry",
    "get_tracer",
]
