"""Riot rate-limit header capture (arena/riot/limit_headers.py).

Two contracts matter here:

1. the parser is **total** — Riot changing or omitting a header must degrade to
   "no data", never raise into an in-flight API call;
2. ``detect_drift`` only complains when the configuration would let us exceed
   Riot's real limit, since configuring *below* the ceiling is the whole point
   of the headroom factor.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from arena.riot import limit_headers as lh


class _FakePipe:
    def __init__(self, store: dict[str, str], ttls: dict[str, int]) -> None:
        self._store = store
        self._ttls = ttls
        self._ops: list[tuple[str, str, int]] = []

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._ops.append((key, value, ex or 0))

    async def execute(self) -> list[Any]:
        for key, value, ttl in self._ops:
            self._store[key] = value
            self._ttls[key] = ttl
        self._ops.clear()
        return []


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def pipeline(self, transaction: bool = True) -> _FakePipe:
        return _FakePipe(self.store, self.ttls)

    async def mget(self, keys: list[str]) -> list[Any]:
        return [self.store[k].encode() if k in self.store else None for k in keys]


class _BrokenRedis:
    def pipeline(self, transaction: bool = True) -> Any:
        raise ConnectionError("redis down")

    async def mget(self, keys: list[str]) -> list[Any]:
        raise ConnectionError("redis down")


# --- parse_limit_pairs -----------------------------------------------------


def test_parses_riot_pair_syntax_sorted_by_window() -> None:
    assert lh.parse_limit_pairs("100:120,20:1") == ((20, 1), (100, 120))


@pytest.mark.parametrize(
    "raw",
    ["", None, "garbage", "20", "20:", ":1", "abc:def", "20:0", "20:-5"],
)
def test_malformed_pairs_degrade_to_empty(raw: str | None) -> None:
    assert lh.parse_limit_pairs(raw) == ()


def test_partial_garbage_keeps_the_usable_pairs() -> None:
    assert lh.parse_limit_pairs("20:1,broken,2000:10") == ((20, 1), (2000, 10))


# --- parse_rate_limit_headers ---------------------------------------------


def test_counts_are_joined_on_window_length_not_position() -> None:
    """Riot lists both headers in the same order today; joining on the window
    is what makes the pairing correct if it ever stops doing so."""
    observed = lh.parse_rate_limit_headers(
        {
            "X-App-Rate-Limit": "20:1,100:120",
            # Deliberately reversed relative to the limit header.
            "X-App-Rate-Limit-Count": "37:120,7:1",
        }
    )
    assert [(w.limit, w.seconds, w.count) for w in observed.app] == [
        (20, 1, 7),
        (100, 120, 37),
    ]


def test_method_window_and_429_type_are_captured() -> None:
    observed = lh.parse_rate_limit_headers(
        {
            "X-Method-Rate-Limit": "2000:10",
            "X-Method-Rate-Limit-Count": "1500:10",
            "X-Rate-Limit-Type": "Method",
        }
    )
    assert observed.method[0].limit == 2000
    assert observed.method[0].count == 1500
    assert observed.method[0].utilization == 0.75
    assert observed.limit_type == "method"  # normalized to lowercase


def test_lowercase_headers_are_found() -> None:
    observed = lh.parse_rate_limit_headers({"x-method-rate-limit": "2000:10"})
    assert observed.method[0].limit == 2000


def test_response_without_limit_headers_is_empty() -> None:
    assert lh.parse_rate_limit_headers({"Content-Type": "application/json"}).is_empty


def test_count_without_a_matching_limit_window_reads_as_zero() -> None:
    observed = lh.parse_rate_limit_headers(
        {"X-Method-Rate-Limit": "2000:10", "X-Method-Rate-Limit-Count": "5:600"}
    )
    assert observed.method[0].count == 0


def test_utilization_is_clamped() -> None:
    assert lh.LimitWindow(limit=0, seconds=10, count=5).utilization == 0.0
    assert lh.LimitWindow(limit=10, seconds=10, count=99).utilization == 1.0


# --- detect_drift ----------------------------------------------------------


def test_drift_flags_configuration_above_riots_real_limit() -> None:
    msg = lh.detect_drift(
        (lh.LimitWindow(limit=500, seconds=10),), capacity=2000, refill_seconds=10.0
    )
    assert msg is not None
    assert "500" in msg and "2000" in msg


def test_no_drift_when_configured_at_or_below_the_ceiling() -> None:
    windows = (lh.LimitWindow(limit=2000, seconds=10),)
    assert lh.detect_drift(windows, capacity=2000, refill_seconds=10.0) is None
    # Below the ceiling is the headroom factor working as intended.
    assert lh.detect_drift(windows, capacity=1700, refill_seconds=10.0) is None


def test_drift_flags_a_window_riot_never_advertises() -> None:
    msg = lh.detect_drift(
        (lh.LimitWindow(limit=2000, seconds=10),), capacity=2000, refill_seconds=60.0
    )
    assert msg is not None
    assert "60s" in msg


def test_no_observed_windows_means_no_verdict() -> None:
    assert lh.detect_drift((), capacity=2000, refill_seconds=10.0) is None


# --- store round-trip ------------------------------------------------------


@pytest.mark.asyncio
async def test_app_and_method_windows_are_stored_under_separate_scopes() -> None:
    r = _FakeRedis()
    observed = lh.parse_rate_limit_headers(
        {
            "X-App-Rate-Limit": "100:120",
            "X-App-Rate-Limit-Count": "40:120",
            "X-Method-Rate-Limit": "2000:10",
            "X-Method-Rate-Limit-Count": "12:10",
        }
    )
    await lh.record_observed(r, "abcd1234", "match-v5:match", observed)

    method_blob = json.loads(r.store[lh.key("abcd1234", "match-v5:match")])
    app_blob = json.loads(r.store[lh.key("abcd1234", lh.APP_SCOPE)])
    # The method scope must not duplicate the app window, and vice versa.
    assert method_blob["app"] == [] and method_blob["method"][0]["limit"] == 2000
    assert app_blob["method"] == [] and app_blob["app"][0]["limit"] == 100
    assert r.ttls[lh.key("abcd1234", lh.APP_SCOPE)] == lh.TTL_SECONDS


@pytest.mark.asyncio
async def test_read_observed_round_trips_and_skips_absent_scopes() -> None:
    r = _FakeRedis()
    await lh.record_observed(
        r,
        "abcd1234",
        "match-v5:match",
        lh.parse_rate_limit_headers(
            {"X-Method-Rate-Limit": "2000:10", "X-Method-Rate-Limit-Count": "12:10"}
        ),
    )
    out = await lh.read_observed(r, "abcd1234", ["match-v5:match", "account-v1"])
    assert set(out) == {"match-v5:match"}
    assert out["match-v5:match"].method[0].count == 12


@pytest.mark.asyncio
async def test_empty_observation_is_not_written() -> None:
    r = _FakeRedis()
    await lh.record_observed(r, "abcd1234", "match-v5:match", lh.parse_rate_limit_headers({}))
    assert r.store == {}


@pytest.mark.asyncio
async def test_redis_failures_never_propagate() -> None:
    observed = lh.parse_rate_limit_headers({"X-Method-Rate-Limit": "2000:10"})
    await lh.record_observed(_BrokenRedis(), "abcd1234", "match-v5:match", observed)
    assert await lh.read_observed(_BrokenRedis(), "abcd1234", ["match-v5:match"]) == {}
    # A client constructed without metrics Redis passes None through.
    await lh.record_observed(None, "abcd1234", "match-v5:match", observed)
    assert await lh.read_observed(None, "abcd1234", ["match-v5:match"]) == {}


@pytest.mark.asyncio
async def test_corrupt_stored_payload_is_skipped_not_raised() -> None:
    r = _FakeRedis()
    r.store[lh.key("abcd1234", "match-v5:match")] = "{not json"
    assert await lh.read_observed(r, "abcd1234", ["match-v5:match"]) == {}
