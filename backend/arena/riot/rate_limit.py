"""Distributed token-bucket rate limiter (Redis + Lua).

Riot enforces several overlapping rate limits per API key (application-wide
limits and per-method limits). We model each as an independent token bucket and
require **all** applicable buckets to have capacity before a call proceeds.

Atomicity matters: multiple ingestion workers share one API key, so the
"refill, peek, decrement" sequence must be a single atomic operation or two
workers will race and overshoot the limit. We push that whole sequence into a
Lua script (``EVAL``), which Redis runs atomically on the server.

The bucket state lives in a single Redis hash per bucket key::

    {tokens: float, ts: float}    # ts = last refill, in seconds

The script lazily refills based on elapsed wall-clock time (taken from Redis
``TIME`` so all workers agree on "now"), then either decrements and returns
``available=1`` or returns the seconds to wait until ``n`` tokens are free.

Public API:
    TokenBucketConfig          # capacity + refill window for one bucket
    RedisTokenBucketLimiter    # acquire across one or more buckets
    default_arena_buckets()    # Riot production-key limits for the Arena client
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from redis.asyncio import Redis

# KEYS[1] = bucket hash key
# ARGV[1] = capacity (max tokens)
# ARGV[2] = refill rate (tokens/sec)
# ARGV[3] = requested tokens (n)
# ARGV[4] = key TTL seconds (housekeeping; keeps idle buckets from lingering)
#
# Returns: {available (0|1), wait_ms}
#   available=1 -> n tokens consumed; wait_ms=0
#   available=0 -> not consumed; wait_ms = ms until n tokens would be free
_TOKEN_BUCKET_LUA = """
local key      = KEYS[1]
local capacity = tonumber(ARGV[1])
local rate     = tonumber(ARGV[2])
local needed   = tonumber(ARGV[3])
local ttl      = tonumber(ARGV[4])

-- Server clock: {seconds, microseconds}. Use a single source so all workers
-- compute refill against the same monotonic-ish wall clock.
local t = redis.call('TIME')
local now = tonumber(t[1]) + (tonumber(t[2]) / 1000000)

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
  tokens = capacity
  ts = now
end

-- Lazy refill.
local elapsed = now - ts
if elapsed > 0 then
  tokens = math.min(capacity, tokens + (elapsed * rate))
  ts = now
end

if tokens >= needed then
  tokens = tokens - needed
  redis.call('HSET', key, 'tokens', tokens, 'ts', ts)
  redis.call('EXPIRE', key, ttl)
  return {1, 0}
end

-- Not enough: report wait until `needed` tokens accrue.
local deficit = needed - tokens
local wait_ms = math.ceil((deficit / rate) * 1000)
redis.call('HSET', key, 'tokens', tokens, 'ts', ts)
redis.call('EXPIRE', key, ttl)
return {0, wait_ms}
"""


@dataclass(frozen=True, slots=True)
class TokenBucketConfig:
    """One token bucket: ``capacity`` tokens refilling over ``refill_seconds``."""

    name: str
    capacity: int
    refill_seconds: float

    @property
    def rate(self) -> float:
        """Refill rate in tokens per second."""
        return self.capacity / self.refill_seconds


class RedisTokenBucketLimiter:
    """Atomic, Redis-backed multi-bucket token-bucket limiter.

    ``acquire`` blocks (cooperatively) until every applicable bucket has a token,
    consuming one from each. The script is server-side atomic per bucket; the
    cross-bucket acquire loop re-checks all buckets each pass so it never holds a
    token from one bucket while waiting on another.
    """

    def __init__(
        self,
        redis: Redis,
        buckets: Mapping[str, TokenBucketConfig],
        *,
        key_prefix: str = "riot:ratelimit",
        key_ttl_seconds: int = 120,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_wait_seconds: float = 30.0,
    ) -> None:
        self._redis = redis
        self._buckets = dict(buckets)
        self._key_prefix = key_prefix
        self._key_ttl = key_ttl_seconds
        self._sleep = sleep
        self._max_wait = max_wait_seconds
        # registerScript-style handle; redis-py picks EVALSHA with EVAL fallback.
        self._script = redis.register_script(_TOKEN_BUCKET_LUA)

    def _key(self, api_key: str, bucket: str) -> str:
        # One bucket-set per API key so multiple keys do not share state.
        suffix = api_key[-8:] if api_key else "anon"
        return f"{self._key_prefix}:{suffix}:{bucket}"

    async def _try_bucket(self, api_key: str, cfg: TokenBucketConfig, n: int) -> float:
        """Attempt to consume ``n`` from one bucket.

        Returns 0.0 when consumed, else the seconds to wait before retrying.
        """
        result = await self._script(
            keys=[self._key(api_key, cfg.name)],
            args=[cfg.capacity, cfg.rate, n, self._key_ttl],
        )
        available, wait_ms = int(result[0]), int(result[1])
        return 0.0 if available == 1 else wait_ms / 1000.0

    async def acquire(self, api_key: str, bucket_names: Sequence[str], *, n: int = 1) -> None:
        """Consume one token from every named bucket that is configured.

        Buckets not present in the configuration are ignored (so callers can
        pass an optimistic superset). Loops until all applicable buckets grant.
        """
        applicable = [self._buckets[b] for b in bucket_names if b in self._buckets]
        if not applicable:
            return
        while True:
            waits = [await self._try_bucket(api_key, cfg, n) for cfg in applicable]
            longest = max(waits, default=0.0)
            if longest <= 0.0:
                # Every bucket reported available *this pass*. Because each
                # _try_bucket already consumed when available, an all-zero pass
                # means all consumed. (A bucket that granted on an earlier pass
                # but a later bucket blocked is acceptable slack — Riot limits
                # are ceilings, and the refund cost is at most one token.)
                return
            await self._sleep(min(longest, self._max_wait))


# --- Riot production-key limits for the Arena client -----------------------
# The Riot developer portal lists limits PER METHOD for this key:
#   account-v1 by-puuid / by-riot-id: 1000 req / 60s
#   match-v5   by-puuid/ids:          2000 req / 10s
#   match-v5   matches/{id}:          2000 req / 10s   (separate from ids!)
# There is no app-wide limit on the portal table; APP_BUCKET therefore defaults
# to DISABLED (capacity 0 => omitted, and the limiter ignores unconfigured
# names). It exists so a key that does carry an app-wide limit can model it via
# settings without code changes.
APP_BUCKET = "app"
ACCOUNT_V1_BUCKET = "account-v1"
MATCH_V5_IDS_BUCKET = "match-v5:ids"
MATCH_V5_MATCH_BUCKET = "match-v5:match"


def default_arena_buckets(
    *,
    app_capacity: int = 0,
    app_refill_seconds: float = 10.0,
    match_v5_capacity: int = 2000,
    match_v5_refill_seconds: float = 10.0,
    account_v1_capacity: int = 1000,
    account_v1_refill_seconds: float = 60.0,
) -> dict[str, TokenBucketConfig]:
    """Token buckets matching Riot's per-method limits for the Arena client.

    ``match_v5_capacity`` applies to EACH of the two match-v5 buckets — Riot
    enforces ids-list and match-detail as independent 2000/10s limits, so
    discovery and payload fetch must not share one bucket (that would halve
    the real budget). ``app_capacity=0`` omits the app-wide bucket entirely.
    """
    buckets = {
        ACCOUNT_V1_BUCKET: TokenBucketConfig(
            ACCOUNT_V1_BUCKET, capacity=account_v1_capacity, refill_seconds=account_v1_refill_seconds
        ),
        MATCH_V5_IDS_BUCKET: TokenBucketConfig(
            MATCH_V5_IDS_BUCKET, capacity=match_v5_capacity, refill_seconds=match_v5_refill_seconds
        ),
        MATCH_V5_MATCH_BUCKET: TokenBucketConfig(
            MATCH_V5_MATCH_BUCKET, capacity=match_v5_capacity, refill_seconds=match_v5_refill_seconds
        ),
    }
    if app_capacity > 0:
        buckets[APP_BUCKET] = TokenBucketConfig(
            APP_BUCKET, capacity=app_capacity, refill_seconds=app_refill_seconds
        )
    return buckets
