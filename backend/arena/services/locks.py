"""Redis-backed distributed locks for the match-processing critical section.

Two players in concurrently-processed matches must never interleave their
``player_seasons`` read-modify-write (CR/mu/sigma/streak). The processor takes a
**per-player** lock for every eligible participant of a match before the rating
transaction, in a stable order (sorted by ``player_id``) to avoid deadlocks.

The lock is a single ``SET key value NX PX ttl`` with a random token, released
by a compare-and-delete Lua script so we never delete a lock we no longer own
(classic Redlock single-instance safety). A small abstraction
(:class:`RedisLockManager`) yields an ``async with`` context that holds every
player lock for the match.

This module deliberately depends only on ``redis.asyncio`` and the stdlib; it is
self-contained so the rating service can be tested with a fake manager.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager

from redis.asyncio import Redis

# Compare-and-delete: only release if we still own the token (idempotent, safe
# under TTL expiry races). KEYS[1]=lock key, ARGV[1]=our token.
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""

_DEFAULT_TTL_MS = 30_000  # generous vs. a sub-second rating tx
_DEFAULT_RETRY_DELAY_S = 0.05
_DEFAULT_MAX_WAIT_S = 10.0


class LockAcquireTimeout(RuntimeError):
    """Raised when a player lock cannot be acquired within the wait budget."""


class RedisLockManager:
    """Acquires/releases per-player locks against a Redis connection.

    Parameters mirror a single-instance Redlock. ``key_prefix`` namespaces the
    locks (``arena:lock:player:{id}``) so they never collide with cache keys.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        key_prefix: str = "arena:lock:player:",
        ttl_ms: int = _DEFAULT_TTL_MS,
        retry_delay_s: float = _DEFAULT_RETRY_DELAY_S,
        max_wait_s: float = _DEFAULT_MAX_WAIT_S,
    ) -> None:
        self._redis = redis
        self._prefix = key_prefix
        self._ttl_ms = ttl_ms
        self._retry_delay_s = retry_delay_s
        self._max_wait_s = max_wait_s

    def _key(self, player_id: str) -> str:
        return f"{self._prefix}{player_id}"

    async def _acquire_all(self, ordered: Sequence[str]) -> list[tuple[str, str]]:
        """Acquire every lock in one pipelined round-trip; retry the whole set.

        All ``SET NX`` go out in a single pipeline (1 RTT vs. N). If any key is
        already held, we release the subset we just grabbed and retry the entire
        batch after a short back-off. Releasing-on-partial (rather than holding a
        non-contiguous subset while waiting) is what keeps this deadlock-free with
        pipelining — no match ever holds one player's lock while waiting on
        another's.
        """
        if not ordered:
            return []
        waited = 0.0
        while True:
            tokens = [secrets.token_hex(16) for _ in ordered]
            pipe = self._redis.pipeline(transaction=False)
            for pid, token in zip(ordered, tokens):
                pipe.set(self._key(pid), token, nx=True, px=self._ttl_ms)
            results = await pipe.execute()
            held = [
                (pid, token)
                for pid, token, ok in zip(ordered, tokens, results)
                if ok
            ]
            if len(held) == len(ordered):
                return held
            # Partial: drop what we took so other matches can progress, then retry.
            await self._release_all(held)
            if waited >= self._max_wait_s:
                contended = [pid for pid, _, ok in zip(ordered, tokens, results) if not ok]
                raise LockAcquireTimeout(
                    f"timed out acquiring player lock(s) for {contended!r}"
                )
            await asyncio.sleep(self._retry_delay_s)
            waited += self._retry_delay_s

    async def _release_all(self, held: Sequence[tuple[str, str]]) -> None:
        """Compare-and-delete every held lock in one pipelined round-trip.

        Uses ``pipe.eval`` (not a registered Script) because redis-py's async
        ``Script`` is a coroutine and cannot be queued onto a pipeline; ``eval``
        queues the EVAL command directly.
        """
        if not held:
            return
        pipe = self._redis.pipeline(transaction=False)
        for pid, token in held:
            pipe.eval(_RELEASE_LUA, 1, self._key(pid), token)
        try:
            await pipe.execute()
        except Exception:  # pragma: no cover - release is best-effort (TTL backstop)
            pass

    @asynccontextmanager
    async def lock_players(self, player_ids: Iterable[str]) -> AsyncIterator[None]:
        """Hold a lock on every player for the duration of the ``with`` block.

        Acquisition order is sorted+deduplicated to guarantee a global lock
        ordering; the pipelined all-or-nothing acquire keeps it deadlock-free.
        Locks are released (best-effort; TTL is the backstop) on exit.
        """
        ordered: Sequence[str] = sorted(set(player_ids))
        held = await self._acquire_all(ordered)
        try:
            yield
        finally:
            await self._release_all(held)


__all__ = ["RedisLockManager", "LockAcquireTimeout"]
