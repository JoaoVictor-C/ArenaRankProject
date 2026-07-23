"""Unit tests for the pipelined per-player lock manager (no real Redis).

The fake models the only two Redis ops the manager uses: ``SET key val NX PX``
and the compare-and-delete release Lua script, both issued through a pipeline.
These tests pin the behaviour the pipelining must preserve: every lock taken in
ONE round-trip, all-or-nothing acquisition, release-on-partial (deadlock-free),
and clean release on exit.
"""

from __future__ import annotations

import pytest

from arena.services.locks import LockAcquireTimeout, RedisLockManager


class _FakePipeline:
    def __init__(self, redis: "_FakeRedis") -> None:
        self._redis = redis
        self.ops: list[tuple] = []

    def set(self, key: str, value: str, nx: bool = False, px: int | None = None) -> None:
        self.ops.append(("set", key, value, nx))

    def eval(self, _script: str, _numkeys: int, key: str, token: str) -> None:
        # Models the compare-and-delete release Lua queued onto the pipeline.
        self.ops.append(("release", key, token))

    async def execute(self) -> list:
        self._redis.executes += 1
        results = [self._redis._apply(op) for op in self.ops]
        self.ops.clear()
        return results


class _FakeRedis:
    """In-memory lock store. ``preheld`` simulates locks owned by other matches."""

    def __init__(self, preheld: dict[str, str] | None = None) -> None:
        self.store: dict[str, str] = dict(preheld or {})
        self.executes = 0

    def pipeline(self, transaction: bool = False) -> _FakePipeline:
        return _FakePipeline(self)

    def _apply(self, op: tuple):
        kind = op[0]
        if kind == "set":
            _, key, value, nx = op
            if nx and key in self.store:
                return None
            self.store[key] = value
            return True
        if kind == "release":
            _, key, token = op
            if self.store.get(key) == token:
                del self.store[key]
                return 1
            return 0
        raise AssertionError(op)


async def test_uncontended_acquires_all_and_releases() -> None:
    redis = _FakeRedis()
    mgr = RedisLockManager(redis, retry_delay_s=0.001, max_wait_s=0.05)

    async with mgr.lock_players(["c", "a", "b"]):
        # All three held inside the block (sorted keys, one pipeline acquire).
        assert set(redis.store) == {
            "arena:lock:player:a",
            "arena:lock:player:b",
            "arena:lock:player:c",
        }

    # Released on exit, and the whole thing cost just 2 round-trips.
    assert redis.store == {}
    assert redis.executes == 2  # 1 acquire pipeline + 1 release pipeline


async def test_partial_acquire_releases_and_times_out() -> None:
    # A foreign match permanently holds "b" -> we can never get the full set.
    redis = _FakeRedis(preheld={"arena:lock:player:b": "foreign-token"})
    mgr = RedisLockManager(redis, retry_delay_s=0.001, max_wait_s=0.01)

    with pytest.raises(LockAcquireTimeout) as exc:
        async with mgr.lock_players(["a", "b"]):
            pytest.fail("should never enter the critical section")  # pragma: no cover

    # We never hold "a" while waiting on "b": the partial grab was released, so
    # only the foreign lock remains (deadlock-free, no leaked partial lock).
    assert redis.store == {"arena:lock:player:b": "foreign-token"}
    assert "'b'" in str(exc.value)  # the error names the contended key


async def test_retries_until_contended_key_frees() -> None:
    redis = _FakeRedis(preheld={"arena:lock:player:b": "foreign-token"})

    # Free "b" on the second acquire attempt to exercise the retry path.
    state = {"attempts": 0}
    orig_apply = redis._apply

    def apply_with_release(op):
        if op[0] == "set" and op[1] == "arena:lock:player:a":
            state["attempts"] += 1
            if state["attempts"] == 2:
                redis.store.pop("arena:lock:player:b", None)
        return orig_apply(op)

    redis._apply = apply_with_release
    mgr = RedisLockManager(redis, retry_delay_s=0.001, max_wait_s=1.0)

    async with mgr.lock_players(["a", "b"]):
        assert "arena:lock:player:a" in redis.store
        assert redis.store["arena:lock:player:b"] != "foreign-token"

    assert redis.store == {}
    assert state["attempts"] >= 2  # retried at least once
