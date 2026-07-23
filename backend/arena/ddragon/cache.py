"""Two-tier cache for Data Dragon static blobs: Redis (optional) + in-process.

Data Dragon (``ddragon``) is Riot's *official* static CDN — the same data the
LoL client ships with — so it is ToS-compliant and free to cache aggressively.
The version and champion map roll forward only on each patch (~every 2 weeks),
so a 12h TTL is comfortable.

Design goals (per task contract):

* **Redis optional.** If ``REDIS_URL`` is absent / unreachable, the service must
  still work, degrading to a process-local cache. We never raise on a Redis
  error — every Redis touch is best-effort and logged at debug.
* **In-process layer always on.** Even with Redis present we keep a tiny
  in-memory copy so request handlers resolve champion metadata without any
  network/Redis round-trip on the hot path.

Values are JSON strings. The champion map is ``{int championId: {...}}``; JSON
object keys must be strings, so we coerce on read.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..core.logging import get_logger

_log = get_logger(__name__)

# 12 hours — ddragon only changes on a patch (~biweekly). Per task contract.
DEFAULT_TTL_SECONDS = 12 * 60 * 60


class _InProcessEntry:
    """A single in-memory cache slot with a monotonic expiry."""

    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, ttl_seconds: int) -> None:
        self.value = value
        self.expires_at = time.monotonic() + ttl_seconds

    @property
    def expired(self) -> bool:
        return time.monotonic() >= self.expires_at


class DDragonCache:
    """Best-effort two-tier cache: in-process first, optional Redis behind it.

    A single instance is shared by the service singleton. ``redis`` may be
    ``None`` (Redis disabled / unavailable), in which case only the in-process
    tier is used and the service falls back to live HTTP fetches once the
    in-process entry expires.
    """

    def __init__(
        self,
        *,
        redis: Any | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._redis = redis
        self._ttl = ttl_seconds
        self._local: dict[str, _InProcessEntry] = {}

    @property
    def has_redis(self) -> bool:
        return self._redis is not None

    # -- in-process tier ----------------------------------------------------

    def get_local(self, key: str) -> Any | None:
        entry = self._local.get(key)
        if entry is None:
            return None
        if entry.expired:
            self._local.pop(key, None)
            return None
        return entry.value

    def set_local(self, key: str, value: Any) -> None:
        self._local[key] = _InProcessEntry(value, self._ttl)

    # -- Redis tier (best-effort) -------------------------------------------

    async def get_redis(self, key: str) -> Any | None:
        """Read + JSON-decode a Redis value, or ``None`` on any miss/error."""
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(key)
        except Exception:  # noqa: BLE001 - Redis is best-effort
            _log.debug("ddragon.cache.redis_get_failed", key=key)
            return None
        if raw is None:
            return None
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return None

    async def set_redis(self, key: str, value: Any) -> None:
        """Write a JSON value to Redis with the shared TTL (best-effort)."""
        if self._redis is None:
            return
        try:
            data = json.dumps(value, separators=(",", ":"))
            await self._redis.set(key, data, ex=self._ttl)
        except Exception:  # noqa: BLE001 - Redis is best-effort
            _log.debug("ddragon.cache.redis_set_failed", key=key)

    # -- combined helpers ---------------------------------------------------

    async def get(self, key: str) -> Any | None:
        """In-process hit first; on miss fall through to Redis and re-warm local."""
        local = self.get_local(key)
        if local is not None:
            return local
        value = await self.get_redis(key)
        if value is not None:
            self.set_local(key, value)
        return value

    async def set(self, key: str, value: Any) -> None:
        """Write-through to both tiers (Redis best-effort)."""
        self.set_local(key, value)
        await self.set_redis(key, value)

    def clear_local(self) -> None:
        self._local.clear()
