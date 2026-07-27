"""Headroom + 429 penalty on the Riot limiter (arena/riot/rate_limit.py).

The Lua bodies themselves need a real Redis (they are exercised by the
integration stack); what is unit-testable — and what actually bit us before —
is the Python around them: which buckets a penalty targets, the TTL that has to
outlive the penalty, and the guarantee that a Redis hiccup during a 429 never
escalates into a hard failure.
"""

from __future__ import annotations

from typing import Any

import pytest

from arena.riot.rate_limit import (
    ACCOUNT_V1_BUCKET,
    APP_BUCKET,
    MATCH_V5_IDS_BUCKET,
    MATCH_V5_MATCH_BUCKET,
    RedisTokenBucketLimiter,
    TokenBucketConfig,
    apply_headroom,
    default_arena_buckets,
)


class _FakeScriptRedis:
    """Records script invocations. First registered script = acquire, second =
    penalize (matching the limiter's constructor order)."""

    def __init__(self, *, result: Any = 0, raises: bool = False) -> None:
        self.calls: list[tuple[int, list[str], list[Any]]] = []
        self._registered = 0
        self._result = result
        self._raises = raises

    def register_script(self, source: str) -> Any:
        index = self._registered
        self._registered += 1

        async def run(keys: list[str], args: list[Any]) -> Any:
            self.calls.append((index, keys, args))
            if self._raises:
                raise ConnectionError("redis down")
            return self._result

        return run

    @property
    def penalize_calls(self) -> list[tuple[int, list[str], list[Any]]]:
        return [c for c in self.calls if c[0] == 1]


def _limiter(redis: Any, **kwargs: Any) -> RedisTokenBucketLimiter:
    return RedisTokenBucketLimiter(redis, default_arena_buckets(), **kwargs)


# --- headroom --------------------------------------------------------------


def test_headroom_scales_capacity_but_preserves_the_advertised_limit() -> None:
    buckets = default_arena_buckets(match_v5_capacity=2000, headroom=0.9)
    match = buckets[MATCH_V5_MATCH_BUCKET]
    assert match.capacity == 1800  # what the limiter enforces
    assert match.nominal == 2000  # what Riot publishes
    assert match.advertised == 2000
    # The refill rate must follow the EFFECTIVE capacity, or headroom would be
    # cosmetic: the bucket would refill back up to Riot's full rate.
    assert match.rate == pytest.approx(180.0)


def test_default_headroom_is_a_no_op_for_callers_that_do_not_opt_in() -> None:
    match = default_arena_buckets(match_v5_capacity=2000)[MATCH_V5_MATCH_BUCKET]
    assert match.capacity == 2000
    assert match.advertised == 2000


def test_apply_headroom_never_rounds_a_real_limit_down_to_zero() -> None:
    """A zero-capacity bucket can never grant a token — that is a deadlock, not
    a throttle."""
    assert apply_headroom(5, 0.05) == 1
    assert apply_headroom(2000, 0.9) == 1800
    # A bucket that is genuinely disabled stays disabled.
    assert apply_headroom(0, 0.9) == 0


def test_both_match_v5_buckets_get_the_full_capacity_each() -> None:
    """Riot enforces ids-list and match-detail as independent 2000/10s limits;
    sharing one budget between them would halve the real throughput."""
    buckets = default_arena_buckets(match_v5_capacity=2000, headroom=0.9)
    assert buckets[MATCH_V5_IDS_BUCKET].capacity == 1800
    assert buckets[MATCH_V5_MATCH_BUCKET].capacity == 1800


def test_app_bucket_is_omitted_when_the_key_has_no_app_wide_limit() -> None:
    assert APP_BUCKET not in default_arena_buckets(app_capacity=0)
    assert APP_BUCKET in default_arena_buckets(app_capacity=500)


def test_configured_reports_which_buckets_are_modelled() -> None:
    limiter = RedisTokenBucketLimiter(
        _FakeScriptRedis(), default_arena_buckets(app_capacity=0)
    )
    assert limiter.configured(MATCH_V5_MATCH_BUCKET)
    assert not limiter.configured(APP_BUCKET)


# --- penalize --------------------------------------------------------------


@pytest.mark.asyncio
async def test_penalize_freezes_only_the_named_configured_buckets() -> None:
    redis = _FakeScriptRedis(result=5000)
    limiter = _limiter(redis)
    applied = await limiter.penalize("key-abcd1234", [APP_BUCKET, MATCH_V5_MATCH_BUCKET], seconds=5)

    # APP_BUCKET is unconfigured by default -> silently skipped, not an error.
    assert len(redis.penalize_calls) == 1
    _, keys, _ = redis.penalize_calls[0]
    assert keys == ["riot:ratelimit:abcd1234:match-v5:match"]
    assert applied == 5.0


@pytest.mark.asyncio
async def test_penalty_ttl_outlives_the_penalty_itself() -> None:
    """If the bucket key expired mid-penalty, the next acquire would read an
    absent hash as a FULL bucket and silently undo the backoff."""
    redis = _FakeScriptRedis(result=0)
    limiter = _limiter(redis, key_ttl_seconds=120)
    await limiter.penalize("key-abcd1234", [MATCH_V5_MATCH_BUCKET], seconds=300)

    _, _, args = redis.penalize_calls[0]
    ttl, seconds = args
    assert seconds == 300
    assert ttl > 300


@pytest.mark.asyncio
async def test_short_penalty_keeps_the_default_key_ttl() -> None:
    redis = _FakeScriptRedis(result=0)
    limiter = _limiter(redis, key_ttl_seconds=120)
    await limiter.penalize("key-abcd1234", [MATCH_V5_MATCH_BUCKET], seconds=5)
    assert redis.penalize_calls[0][2][0] == 120


@pytest.mark.asyncio
async def test_penalize_returns_the_longest_penalty_across_buckets() -> None:
    redis = _FakeScriptRedis(result=12_000)
    limiter = _limiter(redis)
    applied = await limiter.penalize(
        "key-abcd1234", [MATCH_V5_MATCH_BUCKET, ACCOUNT_V1_BUCKET], seconds=5
    )
    assert applied == 12.0


@pytest.mark.asyncio
@pytest.mark.parametrize("seconds", [0, -1])
async def test_non_positive_penalty_is_a_no_op(seconds: float) -> None:
    redis = _FakeScriptRedis()
    limiter = _limiter(redis)
    assert await limiter.penalize("key-abcd1234", [MATCH_V5_MATCH_BUCKET], seconds=seconds) == 0.0
    assert redis.penalize_calls == []


@pytest.mark.asyncio
async def test_unknown_bucket_names_are_ignored() -> None:
    redis = _FakeScriptRedis()
    limiter = _limiter(redis)
    assert await limiter.penalize("key-abcd1234", ["not-a-bucket"], seconds=5) == 0.0
    assert redis.penalize_calls == []


@pytest.mark.asyncio
async def test_redis_failure_during_a_429_never_propagates() -> None:
    """The caller's Retry-After backoff is the backstop; a broken penalty must
    not convert a recoverable 429 into a hard error."""
    limiter = _limiter(_FakeScriptRedis(raises=True))
    assert await limiter.penalize("key-abcd1234", [MATCH_V5_MATCH_BUCKET], seconds=5) == 0.0


def test_bucket_key_is_scoped_per_api_key() -> None:
    """Two keys must not share bucket state — otherwise rotating a key inherits
    the old key's spend."""
    limiter = _limiter(_FakeScriptRedis())
    a = limiter._key("aaaaaaaa11111111", MATCH_V5_MATCH_BUCKET)
    b = limiter._key("bbbbbbbb22222222", MATCH_V5_MATCH_BUCKET)
    assert a != b


def test_rate_is_derived_from_capacity_and_window() -> None:
    cfg = TokenBucketConfig("x", capacity=100, refill_seconds=10.0)
    assert cfg.rate == 10.0
    assert cfg.advertised == 100  # nominal defaults to capacity
