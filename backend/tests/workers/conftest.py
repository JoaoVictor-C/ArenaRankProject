"""Minimal async FakeRedis for worker tests — no fakeredis dependency.

Implements exactly the ops needed by the sweep, ingestion, and bulk-processor
workers. Values are stored as bytes (real redis-py asyncio behaviour).
"""
from __future__ import annotations

import pytest


def _to_bytes(v: str | bytes | int) -> bytes:
    if isinstance(v, bytes):
        return v
    if isinstance(v, int):
        return str(v).encode()
    return v.encode()


class EnqueuedJob:
    """One recorded ``enqueue_job`` call — enough to assert task/queue/job id."""

    def __init__(self, task: str, args: tuple, queue_name: str | None, job_id: str | None) -> None:  # type: ignore[type-arg]
        self.task = task
        self.args = args
        self.queue_name = queue_name
        self.job_id = job_id


class FakeRedis:
    """Hand-rolled async Redis mock for the ops our workers call.

    Storage is split by type so a key collision between, say, a string and a
    set is silently isolated (matching real Redis "WRONGTYPE" semantics at the
    type level — we just never mix in practice).
    """

    def __init__(self) -> None:
        self._strings: dict[str, bytes] = {}
        self._lists: dict[str, list[bytes]] = {}
        self._sets: dict[str, set[bytes]] = {}
        self._zsets: dict[str, dict[bytes, float]] = {}
        self._hashes: dict[str, dict[bytes, int]] = {}
        # TTLs stored but not enforced (time doesn't advance in unit tests).
        self._ttls: dict[str, int] = {}
        # arq's ArqRedis.enqueue_job — real jobs would land on a Redis-backed
        # queue; here we just record the call so tests can assert what would
        # have been enqueued (task, args, queue, job id) without a real arq
        # Worker in the loop. A duplicate job_id is dropped (arq's own dedup),
        # mirroring enqueue_job returning None for an id already queued.
        self.enqueued: list[EnqueuedJob] = []
        self._enqueued_ids: set[str] = set()

    # ------------------------------------------------------------------
    # String ops
    # ------------------------------------------------------------------

    async def get(self, key: str) -> bytes | None:
        return self._strings.get(key)

    async def set(
        self,
        key: str,
        value: str | bytes | int,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool | None:
        """SET key value [NX] [EX seconds].

        Returns True on success, None when NX is set and the key already
        exists — matching redis-py asyncio behaviour.
        """
        if nx and key in self._strings:
            return None
        self._strings[key] = _to_bytes(value)
        if ex is not None:
            self._ttls[key] = ex
        return True

    async def delete(self, *keys: str) -> int:
        removed = 0
        for k in keys:
            for store in (
                self._strings,
                self._lists,
                self._sets,
                self._zsets,
                self._hashes,
            ):
                if k in store:
                    del store[k]  # type: ignore[arg-type]
                    removed += 1
                    break
        return removed

    async def exists(self, *keys: str) -> int:
        count = 0
        for k in keys:
            for store in (
                self._strings,
                self._lists,
                self._sets,
                self._zsets,
                self._hashes,
            ):
                if k in store:
                    count += 1
                    break
        return count

    async def expire(self, key: str, ttl: int) -> bool:
        self._ttls[key] = ttl
        return True

    # ------------------------------------------------------------------
    # arq (ArqRedis.enqueue_job)
    # ------------------------------------------------------------------

    async def enqueue_job(
        self,
        function: str,
        *args: object,
        _queue_name: str | None = None,
        _job_id: str | None = None,
        **kwargs: object,
    ) -> EnqueuedJob | None:
        if _job_id is not None:
            if _job_id in self._enqueued_ids:
                return None  # arq collapses a duplicate job id
            self._enqueued_ids.add(_job_id)
        job = EnqueuedJob(function, args, _queue_name, _job_id)
        self.enqueued.append(job)
        return job

    # ------------------------------------------------------------------
    # List ops
    # ------------------------------------------------------------------

    async def lpush(self, key: str, *values: str | bytes) -> int:
        """LPUSH — prepend each value (left side). Returns new list length."""
        if key not in self._lists:
            self._lists[key] = []
        for v in values:
            self._lists[key].insert(0, _to_bytes(v))
        return len(self._lists[key])

    async def llen(self, key: str) -> int:
        return len(self._lists.get(key, []))

    async def rpush(self, key: str, *values: str | bytes) -> int:
        """RPUSH — append each value (right side). Returns new list length."""
        if key not in self._lists:
            self._lists[key] = []
        for v in values:
            self._lists[key].append(_to_bytes(v))
        return len(self._lists[key])

    async def rpop(
        self, key: str, count: int | None = None
    ) -> bytes | list[bytes] | None:
        """RPOP [count] — pop from the tail.

        * count=None  → bytes | None (single element or None when empty)
        * count given → list[bytes] of up to *count* elements, or None when
          the list is absent / empty (mirrors redis-py 4.x behaviour).
        """
        lst = self._lists.get(key)
        if not lst:
            return None
        if count is None:
            return lst.pop()
        n = min(count, len(lst))
        result = [lst.pop() for _ in range(n)]
        return result if result else None

    # ------------------------------------------------------------------
    # Set ops
    # ------------------------------------------------------------------

    async def sadd(self, key: str, *values: str | bytes) -> int:
        """SADD — return number of elements actually added (new members only)."""
        if key not in self._sets:
            self._sets[key] = set()
        added = 0
        for v in values:
            b = _to_bytes(v)
            if b not in self._sets[key]:
                self._sets[key].add(b)
                added += 1
        return added

    async def scard(self, key: str) -> int:
        return len(self._sets.get(key, set()))

    async def sismember(self, key: str, value: str | bytes) -> int:
        return 1 if _to_bytes(value) in self._sets.get(key, set()) else 0

    async def smembers(self, key: str) -> set[bytes]:
        return set(self._sets.get(key, set()))

    # ------------------------------------------------------------------
    # Sorted-set ops
    # ------------------------------------------------------------------

    async def zadd(
        self,
        key: str,
        mapping: dict,  # type: ignore[type-arg]
        *,
        nx: bool = False,
        lt: bool = False,
    ) -> int:
        """ZADD [NX] [LT] — return count of members added (not updated)."""
        if key not in self._zsets:
            self._zsets[key] = {}
        added = 0
        for member, score in mapping.items():
            b = _to_bytes(member)
            existing = self._zsets[key].get(b)
            if existing is None:
                self._zsets[key][b] = float(score)
                added += 1
                continue
            if nx:
                continue  # NX never updates an existing member
            if lt and float(score) >= existing:
                continue
            self._zsets[key][b] = float(score)
        return added

    async def zrem(self, key: str, *members: str | bytes) -> int:
        zset = self._zsets.get(key, {})
        removed = 0
        for member in members:
            if self._zsets.get(key) is not None and _to_bytes(member) in zset:
                del zset[_to_bytes(member)]
                removed += 1
        return removed

    async def zscore(self, key: str, member: str | bytes) -> float | None:
        return self._zsets.get(key, {}).get(_to_bytes(member))

    async def zremrangebyscore(
        self, key: str, min_score: float | str, max_score: float | str
    ) -> int:
        """ZREMRANGEBYSCORE — only the '-inf'/numeric forms our workers use."""
        zset = self._zsets.get(key)
        if not zset:
            return 0
        lo = float("-inf") if min_score == "-inf" else float(min_score)
        hi = float("inf") if max_score == "+inf" else float(max_score)
        doomed = [m for m, s in zset.items() if lo <= s <= hi]
        for m in doomed:
            del zset[m]
        return len(doomed)

    async def zrangebyscore(
        self,
        key: str,
        min_score: float | str,
        max_score: float | str,
        *,
        start: int = 0,
        num: int | None = None,
    ) -> list[bytes]:
        zset = self._zsets.get(key, {})
        lo = float("-inf") if min_score == "-inf" else float(min_score)
        hi = float("inf") if max_score == "+inf" else float(max_score)
        ordered = [m for m, s in sorted(zset.items(), key=lambda x: x[1]) if lo <= s <= hi]
        sliced = ordered[start:]
        return sliced if num is None else sliced[:num]

    async def zrange(self, key: str, start: int, stop: int) -> list[bytes]:
        """ZRANGE by index (ascending score order)."""
        zset = self._zsets.get(key, {})
        ordered = [m for m, _ in sorted(zset.items(), key=lambda x: x[1])]
        if stop == -1:
            return ordered[start:]
        return ordered[start : stop + 1]

    async def zcard(self, key: str) -> int:
        return len(self._zsets.get(key, {}))

    # ------------------------------------------------------------------
    # Hash ops
    # ------------------------------------------------------------------

    async def hincrby(self, key: str, field: str | bytes, amount: int) -> int:
        """HINCRBY — increment hash field by amount, return new integer value."""
        if key not in self._hashes:
            self._hashes[key] = {}
        bfield = _to_bytes(field)
        new_val = self._hashes[key].get(bfield, 0) + amount
        self._hashes[key][bfield] = new_val
        return new_val

    async def hdel(self, key: str, *fields: str | bytes) -> int:
        hsh = self._hashes.get(key, {})
        removed = 0
        for f in fields:
            b = _to_bytes(f)
            if b in hsh:
                del hsh[b]
                removed += 1
        return removed


# ---------------------------------------------------------------------------
# pytest fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_redis() -> FakeRedis:
    """Return a fresh FakeRedis instance for each test."""
    return FakeRedis()
