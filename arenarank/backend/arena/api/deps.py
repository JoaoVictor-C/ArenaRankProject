"""Shared FastAPI dependencies — API-side Redis client (read-path cache).

``get_redis`` yields a process-wide lazy singleton over ``settings.redis_url``,
degrading to ``None`` when Redis is unreachable so every consumer keeps the
``LeaderboardService(redis=None)`` fallback semantics: Redis is an accelerator,
never a availability dependency of the read path.

Degradation contract:

* the first use PINGs with a short timeout; on failure the dependency returns
  ``None`` and remembers the failure for ``_RETRY_AFTER_S`` seconds (no
  per-request reconnect storm while Redis is down);
* command timeouts are bounded (``socket_timeout``) so a Redis that hangs
  mid-request cannot stall API responses indefinitely.
"""

from __future__ import annotations

import time

from redis.asyncio import Redis

from arena.core.config import settings
from arena.core.logging import get_logger

_log = get_logger("arena.api.deps")

#: After a failed connect, stay in Postgres-fallback mode this long before
#: probing Redis again (seconds).
_RETRY_AFTER_S = 30.0

_client: Redis | None = None
_verified: bool = False
_failed_at: float | None = None


async def get_redis() -> Redis | None:
    """FastAPI dependency: shared async Redis client, or ``None`` if down."""
    global _client, _verified, _failed_at

    if _verified and _client is not None:
        return _client

    now = time.monotonic()
    if _failed_at is not None and now - _failed_at < _RETRY_AFTER_S:
        return None

    try:
        if _client is None:
            _client = Redis.from_url(
                settings.redis_url,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
            )
        await _client.ping()
    except Exception:
        _failed_at = now
        _verified = False
        _log.warning("api.redis.unavailable", retry_after_s=_RETRY_AFTER_S)
        return None

    _verified = True
    _failed_at = None
    return _client


async def close_redis() -> None:
    """Shutdown hook: release the shared client (called from the app lifespan)."""
    global _client, _verified
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:  # pragma: no cover - best-effort teardown
            _log.warning("api.redis.close_failed", exc_info=True)
    _client = None
    _verified = False


__all__ = ["get_redis", "close_redis"]
