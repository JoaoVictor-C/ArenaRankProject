"""Minute-bucketed counters (arena/core/metrics.py).

The contract that matters for the admin console: a series is always exactly
`minutes` long, newest last, zero-filled — and nothing here may ever raise into
the path being measured.
"""

from __future__ import annotations

from typing import Any

import pytest

from arena.core import metrics


class _FakePipe:
    def __init__(self, store: dict[str, int], ttls: dict[str, int]) -> None:
        self._store = store
        self._ttls = ttls
        self._ops: list[tuple[str, Any, Any]] = []

    def incrby(self, key: str, n: int) -> None:
        self._ops.append(("incrby", key, n))

    def expire(self, key: str, ttl: int) -> None:
        self._ops.append(("expire", key, ttl))

    async def execute(self) -> list[Any]:
        for op, key, val in self._ops:
            if op == "incrby":
                self._store[key] = self._store.get(key, 0) + val
            else:
                self._ttls[key] = val
        self._ops.clear()
        return []


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def pipeline(self, transaction: bool = True) -> _FakePipe:
        return _FakePipe(self.store, self.ttls)

    async def mget(self, keys: list[str]) -> list[Any]:
        # redis-py returns bytes for present keys, None for absent ones.
        return [str(self.store[k]).encode() if k in self.store else None for k in keys]


class _BrokenRedis:
    def pipeline(self, transaction: bool = True) -> Any:
        raise ConnectionError("redis down")

    async def mget(self, keys: list[str]) -> list[Any]:
        raise ConnectionError("redis down")


NOW = 1_700_000_000.0  # fixed clock so minute bucketing is deterministic


@pytest.mark.asyncio
async def test_record_increments_current_minute_with_ttl() -> None:
    r = _FakeRedis()
    await metrics.record(r, metrics.EVENT_MATCH_PROCESSED, 5, now=NOW)
    k = metrics.key(metrics.EVENT_MATCH_PROCESSED, metrics.current_minute(NOW))
    assert r.store[k] == 5
    assert r.ttls[k] == metrics.RETENTION_SECONDS


@pytest.mark.asyncio
async def test_record_accumulates_within_a_minute() -> None:
    r = _FakeRedis()
    await metrics.record(r, metrics.EVENT_MATCH_PROCESSED, 2, now=NOW)
    await metrics.record(r, metrics.EVENT_MATCH_PROCESSED, 3, now=NOW + 10)
    k = metrics.key(metrics.EVENT_MATCH_PROCESSED, metrics.current_minute(NOW))
    assert r.store[k] == 5


@pytest.mark.asyncio
async def test_record_many_skips_zero_counts() -> None:
    r = _FakeRedis()
    await metrics.record_many(r, {"a": 0, "b": 4}, now=NOW)
    minute = metrics.current_minute(NOW)
    assert metrics.key("a", minute) not in r.store
    assert r.store[metrics.key("b", minute)] == 4


@pytest.mark.asyncio
async def test_series_is_zero_filled_and_newest_last() -> None:
    r = _FakeRedis()
    # 3 minutes ago = 7, now = 1; the two minutes between stay empty.
    await metrics.record(r, "e", 7, now=NOW - 180)
    await metrics.record(r, "e", 1, now=NOW)
    got = await metrics.series(r, ["e"], 4, now=NOW)
    assert got["e"] == [7, 0, 0, 1]


@pytest.mark.asyncio
async def test_series_window_is_clamped() -> None:
    r = _FakeRedis()
    got = await metrics.series(r, ["e"], metrics.MAX_WINDOW_MINUTES + 500, now=NOW)
    assert len(got["e"]) == metrics.MAX_WINDOW_MINUTES


@pytest.mark.asyncio
async def test_series_separates_events() -> None:
    r = _FakeRedis()
    await metrics.record(r, "a", 1, now=NOW)
    await metrics.record(r, "b", 9, now=NOW)
    got = await metrics.series(r, ["a", "b"], 2, now=NOW)
    assert got == {"a": [0, 1], "b": [0, 9]}


# --- best-effort guarantees ------------------------------------------------


@pytest.mark.asyncio
async def test_record_swallows_redis_failure() -> None:
    """A metrics failure must never propagate into the measured path."""
    await metrics.record(_BrokenRedis(), "e", 1, now=NOW)


@pytest.mark.asyncio
async def test_series_returns_zeros_when_redis_down() -> None:
    got = await metrics.series(_BrokenRedis(), ["e"], 3, now=NOW)
    assert got == {"e": [0, 0, 0]}


@pytest.mark.asyncio
async def test_none_redis_is_a_noop() -> None:
    await metrics.record(None, "e", 1, now=NOW)
    assert await metrics.series(None, ["e"], 2, now=NOW) == {"e": [0, 0]}
