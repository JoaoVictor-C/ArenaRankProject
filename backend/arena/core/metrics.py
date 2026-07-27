"""Minute-bucketed counters in Redis — the backing store for the admin console's
"statistics over time" panels.

Why not Prometheus/OTel: this is operator-facing product surface (the admin
console renders it), not infra telemetry. It has to work in the same Redis the
workers already share, survive a worker restart, and be readable by the API
process without a scrape endpoint. ``arena/core/telemetry.py`` (OTel tracing)
stays the place for distributed tracing.

Shape: one Redis string per ``(event, minute)`` holding an integer, keyed
``arena:metrics:<event>:<epoch_minute>`` with a retention TTL. Counting is a
plain ``INCRBY`` (atomic, no read-modify-write), and reading a window is one
``MGET`` over the minute keys — both O(window) with no scans.

Everything here is **best-effort**: metrics must never break the path they
measure, so every call swallows Redis failures and returns a neutral value.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from typing import Any, Final

from arena.core.logging import get_logger

_log = get_logger("arena.core.metrics")

#: Key prefix for every counter series.
PREFIX: Final[str] = "arena:metrics"

#: How long a minute bucket is kept (24h of history at 1-minute resolution).
RETENTION_SECONDS: Final[int] = 24 * 60 * 60

#: Hard cap on how many minutes a single read may span, so a bad query can't
#: build an unbounded MGET.
MAX_WINDOW_MINUTES: Final[int] = 24 * 60


# --- event names (single source of truth; console renders these) -----------

#: Riot API calls, per rate-limit bucket. Suffixed with the bucket name.
EVENT_RIOT_REQUEST: Final[str] = "riot.request"
#: Riot responses that were rate-limited (HTTP 429).
EVENT_RIOT_429: Final[str] = "riot.rate_limited"
#: Riot calls that ended in an error (any typed RiotError).
EVENT_RIOT_ERROR: Final[str] = "riot.error"

#: Pipeline outcomes, recorded by the bulk processor per match.
EVENT_MATCH_PROCESSED: Final[str] = "match.processed"
EVENT_MATCH_FILTERED: Final[str] = "match.filtered"
EVENT_MATCH_SKIPPED: Final[str] = "match.skipped"
EVENT_MATCH_FAILED: Final[str] = "match.failed"

#: Discovery: match ids the sweep newly pushed onto a pending list.
EVENT_SWEEP_ENQUEUED: Final[str] = "sweep.enqueued"

#: Events the console graphs by default, in display order.
DEFAULT_EVENTS: Final[tuple[str, ...]] = (
    EVENT_MATCH_PROCESSED,
    EVENT_MATCH_FILTERED,
    EVENT_MATCH_SKIPPED,
    EVENT_MATCH_FAILED,
    EVENT_SWEEP_ENQUEUED,
    EVENT_RIOT_REQUEST,
    EVENT_RIOT_429,
    EVENT_RIOT_ERROR,
)


def current_minute(now: float | None = None) -> int:
    """Epoch-minute bucket id for *now*."""
    return int((now if now is not None else time.time()) // 60)


def key(event: str, minute: int) -> str:
    """Redis key holding *event*'s count for *minute*."""
    return f"{PREFIX}:{event}:{minute}"


async def record(redis: Any, event: str, n: int = 1, *, now: float | None = None) -> None:
    """Add *n* to *event*'s current minute bucket. Never raises."""
    if redis is None or n == 0:
        return
    await record_many(redis, {event: n}, now=now)


async def record_many(redis: Any, counts: Mapping[str, int], *, now: float | None = None) -> None:
    """Add several counters in one round-trip. Never raises.

    Used on the hot paths (one call per processed batch instead of per match).
    """
    if redis is None or not counts:
        return
    minute = current_minute(now)
    try:
        pipe = redis.pipeline(transaction=False)
        for event, n in counts.items():
            if not n:
                continue
            k = key(event, minute)
            pipe.incrby(k, n)
            pipe.expire(k, RETENTION_SECONDS)
        await pipe.execute()
    except Exception:  # noqa: BLE001 - metrics must never break the caller
        _log.debug("metrics.record_failed", events=sorted(counts), exc_info=True)


async def series(
    redis: Any, events: Iterable[str], minutes: int, *, now: float | None = None
) -> dict[str, list[int]]:
    """Return ``{event: [count_oldest, ..., count_newest]}`` over *minutes*.

    Missing buckets read as 0, so a series is always exactly *minutes* long and
    the console can plot it without gap handling. Returns all-zero series when
    Redis is unavailable.
    """
    names = list(events)
    window = max(1, min(int(minutes), MAX_WINDOW_MINUTES))
    end = current_minute(now)
    buckets = [end - offset for offset in range(window - 1, -1, -1)]
    empty = {name: [0] * window for name in names}
    if redis is None or not names:
        return empty

    try:
        keys = [key(name, minute) for name in names for minute in buckets]
        raw = await redis.mget(keys)
    except Exception:  # noqa: BLE001 - degrade to zeros rather than 500
        _log.debug("metrics.series_failed", events=names, exc_info=True)
        return empty

    out: dict[str, list[int]] = {}
    for i, name in enumerate(names):
        chunk = raw[i * window : (i + 1) * window]
        out[name] = [_as_int(v) for v in chunk]
    return out


def _as_int(value: object) -> int:
    """Coerce a raw MGET entry (bytes | str | None) to int; 0 on anything odd."""
    if value is None:
        return 0
    if isinstance(value, bytes | bytearray):
        value = value.decode("utf-8", "ignore")
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    if isinstance(value, int):
        return value
    return 0


__all__ = [
    "PREFIX",
    "RETENTION_SECONDS",
    "MAX_WINDOW_MINUTES",
    "EVENT_RIOT_REQUEST",
    "EVENT_RIOT_429",
    "EVENT_RIOT_ERROR",
    "EVENT_MATCH_PROCESSED",
    "EVENT_MATCH_FILTERED",
    "EVENT_MATCH_SKIPPED",
    "EVENT_MATCH_FAILED",
    "EVENT_SWEEP_ENQUEUED",
    "DEFAULT_EVENTS",
    "current_minute",
    "key",
    "record",
    "record_many",
    "series",
]
