"""Request coalescing for identical match fetches.

When many ingestion workers race to fetch the same MatchID, only one should hit
Riot; the rest should wait on that single result. We coalesce on two levels:

1. **In-process** (free, instant): an asyncio ``Future`` registry keyed by the
   request key. Concurrent coroutines in the same event loop await one Future.
2. **Cross-process** (Redis): a short-lived ``SET key worker_id NX EX`` lease
   marks "someone is fetching this". The leader fetches and writes the result to
   the shared cache; followers poll the cache (with a small budget) and return
   the leader's value, avoiding a duplicate Riot call.

Followers that time out waiting fall back to fetching themselves — correctness
over efficiency, since a coalesce miss is merely one extra (idempotent) call.

This module owns only the coordination; persisting the fetched value is the
cache layer's job. The leader is handed a ``store`` callback so the two stay
decoupled (and testable without Redis-as-cache assumptions).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

from redis.asyncio import Redis

T = TypeVar("T")

# Leader-election lease + follower poll. Lua keeps "read result, else try to
# claim leadership" atomic so exactly one follower-pass becomes leader.
_CLAIM_LUA = """
local lease = KEYS[1]
local owner = ARGV[1]
local ttl   = tonumber(ARGV[2])
local ok = redis.call('SET', lease, owner, 'NX', 'EX', ttl)
if ok then
  return 1   -- we are the leader
end
return 0     -- someone else holds the lease
"""


class RequestCoalescer(Generic[T]):
    """De-duplicates concurrent identical fetches across coroutines and workers."""

    def __init__(
        self,
        redis: Redis,
        *,
        key_prefix: str = "riot:coalesce",
        lease_ttl_seconds: int = 15,
        follower_poll_interval: float = 0.1,
        follower_timeout: float = 12.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._redis = redis
        self._key_prefix = key_prefix
        self._lease_ttl = lease_ttl_seconds
        self._poll = follower_poll_interval
        self._follower_timeout = follower_timeout
        self._sleep = sleep
        self._inflight: dict[str, asyncio.Future[T]] = {}
        self._claim = redis.register_script(_CLAIM_LUA)

    def _lease_key(self, key: str) -> str:
        return f"{self._key_prefix}:lease:{key}"

    async def fetch(
        self,
        key: str,
        *,
        loader: Callable[[], Awaitable[T]],
        read_result: Callable[[], Awaitable[T | None]],
        owner_id: str,
    ) -> T:
        """Return the value for ``key``, fetching at most once across the fleet.

        ``loader`` performs the real Riot fetch + stores the result so followers
        can read it. ``read_result`` reads the already-stored value (typically
        the cache), returning ``None`` on miss. ``owner_id`` identifies this
        worker for lease ownership/debugging.
        """
        # Level 1: in-process coalescing.
        existing = self._inflight.get(key)
        if existing is not None:
            return await existing

        loop = asyncio.get_event_loop()
        future: asyncio.Future[T] = loop.create_future()
        self._inflight[key] = future
        try:
            value = await self._fetch_coordinated(
                key, loader=loader, read_result=read_result, owner_id=owner_id
            )
            if not future.done():
                future.set_result(value)
            return value
        except BaseException as exc:  # noqa: BLE001 - propagate to in-proc waiters
            if not future.done():
                future.set_exception(exc)
            raise
        finally:
            self._inflight.pop(key, None)

    async def _fetch_coordinated(
        self,
        key: str,
        *,
        loader: Callable[[], Awaitable[T]],
        read_result: Callable[[], Awaitable[T | None]],
        owner_id: str,
    ) -> T:
        # Maybe it is already cached from a prior fetch.
        cached = await read_result()
        if cached is not None:
            return cached

        # Level 2: cross-process leader election.
        is_leader = bool(
            await self._claim(
                keys=[self._lease_key(key)],
                args=[owner_id, self._lease_ttl],
            )
        )
        if is_leader:
            try:
                return await loader()
            finally:
                # Release the lease promptly so a later fetch is not blocked the
                # full TTL (best-effort; TTL is the backstop).
                await self._redis.delete(self._lease_key(key))

        # Follower: poll for the leader's result.
        waited = 0.0
        while waited < self._follower_timeout:
            await self._sleep(self._poll)
            waited += self._poll
            value = await read_result()
            if value is not None:
                return value
            # Leader gone (lease expired) and still nothing -> contend ourselves.
            if not await self._redis.exists(self._lease_key(key)):
                if bool(
                    await self._claim(
                        keys=[self._lease_key(key)],
                        args=[owner_id, self._lease_ttl],
                    )
                ):
                    try:
                        return await loader()
                    finally:
                        await self._redis.delete(self._lease_key(key))
        # Timed out waiting on the leader: do it ourselves (idempotent fetch).
        return await loader()
