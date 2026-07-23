"""Match-data cache: 24h Redis TTL with an injectable S3-overflow tier.

Match records are immutable once a game ends, so they cache extremely well. We
keep a hot 24h copy in Redis. The proposal also calls for overflow archival to
S3 for the long tail; rather than couple this package to boto3, we depend on a
small :class:`OverflowStore` protocol the deployment wires up. In dev the store
is simply absent (``None``) and the cache is Redis-only.

Read path:  Redis hit -> return; Redis miss -> overflow get; if overflow hits,
            re-warm Redis and return.
Write path: always write Redis (24h TTL); also write-through to overflow when a
            store is configured (best-effort, errors swallowed and logged).

Values are JSON-serialized. Riot match payloads are plain JSON, so this is loss-
less and language-agnostic for the S3 tier.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from redis.asyncio import Redis

from ..core.logging import get_logger

_log = get_logger(__name__)

# 24 hours, per proposal section 9.3.
DEFAULT_TTL_SECONDS = 24 * 60 * 60


@runtime_checkable
class OverflowStore(Protocol):
    """Cold-tier archive (e.g. S3). All methods are async and best-effort.

    Implementations live outside this package (an S3 adapter in infra wiring).
    Keeping it a Protocol means the Riot client has zero hard dependency on any
    object store and stays unit-testable with an in-memory fake.
    """

    async def get(self, key: str) -> bytes | None: ...

    async def put(self, key: str, data: bytes) -> None: ...


class MatchCache:
    """Two-tier match cache: Redis (hot, 24h) over an optional overflow store."""

    def __init__(
        self,
        redis: Redis,
        *,
        overflow: OverflowStore | None = None,
        key_prefix: str = "riot:match",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._redis = redis
        self._overflow = overflow
        self._key_prefix = key_prefix
        self._ttl = ttl_seconds

    def _key(self, match_id: str) -> str:
        return f"{self._key_prefix}:{match_id}"

    def _overflow_key(self, match_id: str) -> str:
        # Flat, content-addressable-ish key for the object store.
        return f"{self._key_prefix.replace(':', '/')}/{match_id}.json"

    async def get(self, match_id: str) -> dict[str, Any] | None:
        """Return the cached match payload, or ``None`` on a full miss.

        On a Redis miss but overflow hit, the value is re-warmed into Redis.
        """
        raw = await self._redis.get(self._key(match_id))
        if raw is not None:
            return self._loads(raw)

        if self._overflow is None:
            return None

        try:
            blob = await self._overflow.get(self._overflow_key(match_id))
        except Exception:  # noqa: BLE001 - overflow is best-effort
            _log.warning("riot.cache.overflow_get_failed", matchId=match_id)
            return None
        if blob is None:
            return None

        value = self._loads(blob)
        if value is not None:
            # Re-warm hot tier so subsequent reads skip the cold store.
            await self._redis.set(self._key(match_id), blob, ex=self._ttl)
        return value

    async def set(self, match_id: str, payload: dict[str, Any]) -> None:
        """Write-through: Redis (24h) + overflow store when configured."""
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        await self._redis.set(self._key(match_id), data, ex=self._ttl)
        if self._overflow is not None:
            try:
                await self._overflow.put(self._overflow_key(match_id), data)
            except Exception:  # noqa: BLE001 - overflow is best-effort
                _log.warning("riot.cache.overflow_put_failed", matchId=match_id)

    @staticmethod
    def _loads(raw: bytes | str) -> dict[str, Any] | None:
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            value = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return None
        return value if isinstance(value, dict) else None
