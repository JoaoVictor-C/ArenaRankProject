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

-- Lazy refill. A `ts` in the FUTURE is a 429 penalty (see the penalize script):
-- elapsed is negative, so no refill happens until the penalty window elapses.
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

-- Not enough: report wait until `needed` tokens accrue. Under a penalty the
-- refill clock has not started yet, so the caller must also wait out the
-- remainder of the penalty — without this the wait is understated and callers
-- spin, re-hammering Redis while the bucket is still frozen at zero.
local deficit = needed - tokens
local wait_ms = math.ceil((deficit / rate) * 1000)
if ts > now then
  wait_ms = wait_ms + math.ceil((ts - now) * 1000)
end
redis.call('HSET', key, 'tokens', tokens, 'ts', ts)
redis.call('EXPIRE', key, ttl)
return {0, wait_ms}
"""

# KEYS[1] = bucket hash key
# ARGV[1] = key TTL seconds
# ARGV[2] = penalty seconds (how long the bucket stays empty)
#
# Empties the bucket and parks `ts` that many seconds in the FUTURE, so the
# acquire script's lazy refill cannot start until the penalty expires. Used when
# Riot answers 429: every worker sharing the key backs off at once, instead of
# each discovering the rejection on its own request.
_PENALIZE_LUA = """
local key     = KEYS[1]
local ttl     = tonumber(ARGV[1])
local penalty = tonumber(ARGV[2])

local t = redis.call('TIME')
local now = tonumber(t[1]) + (tonumber(t[2]) / 1000000)

-- Never shorten an existing penalty: concurrent 429s must not race each other
-- into a weaker backoff than the longest Retry-After already seen.
local current_ts = tonumber(redis.call('HGET', key, 'ts'))
local until_ts = now + penalty
if current_ts ~= nil and current_ts > until_ts then
  until_ts = current_ts
end

redis.call('HSET', key, 'tokens', 0, 'ts', until_ts)
redis.call('EXPIRE', key, ttl)
return math.ceil((until_ts - now) * 1000)
"""


@dataclass(frozen=True, slots=True)
class TokenBucketConfig:
    """One token bucket: ``capacity`` tokens refilling over ``refill_seconds``.

    ``capacity`` is the **effective** ceiling the limiter enforces — Riot's
    advertised limit after the headroom factor. ``nominal`` keeps the
    pre-headroom number so the admin console can render "1800 / 2000 (90%)"
    instead of silently presenting the reduced budget as the real limit.
    """

    name: str
    capacity: int
    refill_seconds: float
    #: Riot's advertised ceiling before headroom. 0 => same as ``capacity``.
    nominal: int = 0

    @property
    def advertised(self) -> int:
        """The limit Riot publishes, independent of our safety margin."""
        return self.nominal or self.capacity

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
        self._penalize_script = redis.register_script(_PENALIZE_LUA)

    def configured(self, bucket: str) -> bool:
        """Whether *bucket* is modelled. Callers use this to pick a fallback
        target when Riot blames a limit we do not track (e.g. an app-wide one
        on a key whose portal lists per-method limits only)."""
        return bucket in self._buckets

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

    async def penalize(
        self, api_key: str, bucket_names: Sequence[str], *, seconds: float
    ) -> float:
        """Freeze the named buckets at zero tokens for *seconds*.

        Called when Riot answers 429. The token bucket is a *model* of Riot's
        accounting, and a 429 is proof the model drifted optimistic — so we
        stop guessing and hand authority to Riot's own ``Retry-After``. Because
        the penalty lives in the shared Redis hash, every worker on the key
        backs off immediately, rather than each one learning about the limit by
        spending another rejected request.

        Returns the longest penalty applied, in seconds (0.0 if nothing was
        penalized). Best-effort: a Redis failure here must not turn a
        recoverable 429 into a hard error, since the caller's own retry with
        ``Retry-After`` remains the backstop.
        """
        applicable = [self._buckets[b] for b in bucket_names if b in self._buckets]
        if not applicable or seconds <= 0:
            return 0.0
        # The bucket key must outlive the penalty: if it expired mid-penalty the
        # next acquire would treat the absent hash as a full bucket and undo it.
        ttl = max(self._key_ttl, int(seconds * 2) + 1)
        longest = 0.0
        for cfg in applicable:
            try:
                wait_ms = await self._penalize_script(
                    keys=[self._key(api_key, cfg.name)],
                    args=[ttl, seconds],
                )
                longest = max(longest, int(wait_ms) / 1000.0)
            except Exception:  # noqa: BLE001 - retry/Retry-After is the backstop
                continue
        return longest


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


def apply_headroom(nominal: int, headroom: float) -> int:
    """Effective capacity for a bucket whose advertised limit is *nominal*.

    Floors at 1 token: a headroom small enough to round a real limit down to
    zero would deadlock the limiter (no token ever becomes available) instead of
    merely throttling it.
    """
    if nominal <= 0:
        return 0
    return max(1, int(nominal * headroom))


def default_arena_buckets(
    *,
    app_capacity: int = 0,
    app_refill_seconds: float = 10.0,
    match_v5_capacity: int = 2000,
    match_v5_refill_seconds: float = 10.0,
    account_v1_capacity: int = 1000,
    account_v1_refill_seconds: float = 60.0,
    headroom: float = 1.0,
) -> dict[str, TokenBucketConfig]:
    """Token buckets matching Riot's per-method limits for the Arena client.

    ``match_v5_capacity`` applies to EACH of the two match-v5 buckets — Riot
    enforces ids-list and match-detail as independent 2000/10s limits, so
    discovery and payload fetch must not share one bucket (that would halve
    the real budget). ``app_capacity=0`` omits the app-wide bucket entirely.

    The capacities passed in are Riot's **advertised** limits; ``headroom``
    (0..1) scales them into the effective ceiling the limiter enforces, and the
    advertised value is preserved on :attr:`TokenBucketConfig.nominal` for the
    admin console. Default 1.0 keeps callers that do not opt in unchanged.
    """

    def _bucket(name: str, nominal: int, refill_seconds: float) -> TokenBucketConfig:
        return TokenBucketConfig(
            name,
            capacity=apply_headroom(nominal, headroom),
            refill_seconds=refill_seconds,
            nominal=nominal,
        )

    buckets = {
        ACCOUNT_V1_BUCKET: _bucket(ACCOUNT_V1_BUCKET, account_v1_capacity, account_v1_refill_seconds),
        MATCH_V5_IDS_BUCKET: _bucket(MATCH_V5_IDS_BUCKET, match_v5_capacity, match_v5_refill_seconds),
        MATCH_V5_MATCH_BUCKET: _bucket(
            MATCH_V5_MATCH_BUCKET, match_v5_capacity, match_v5_refill_seconds
        ),
    }
    if app_capacity > 0:
        buckets[APP_BUCKET] = _bucket(APP_BUCKET, app_capacity, app_refill_seconds)
    return buckets
