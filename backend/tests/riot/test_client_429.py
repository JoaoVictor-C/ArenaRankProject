"""How the Riot client reacts to a 429 (arena/riot/client.py).

A 429 is proof our token bucket drifted optimistic. The contract under test:
Riot's ``X-Rate-Limit-Type`` decides *which* bucket gets frozen, ``Retry-After``
decides for how long, and nothing in this path may raise — the caller's retry is
what actually recovers the request.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from arena.core.config import settings
from arena.riot.client import _DEFAULT_429_PENALTY_SECONDS, RiotClient
from arena.riot.rate_limit import APP_BUCKET, MATCH_V5_MATCH_BUCKET

BUCKETS = [APP_BUCKET, MATCH_V5_MATCH_BUCKET]


class _FakeLimiter:
    def __init__(self, *, app_configured: bool = False) -> None:
        self._app_configured = app_configured
        self.penalties: list[tuple[list[str], float]] = []

    def configured(self, bucket: str) -> bool:
        return bucket != APP_BUCKET or self._app_configured

    async def penalize(self, api_key: str, bucket_names: Any, *, seconds: float) -> float:
        self.penalties.append((list(bucket_names), seconds))
        return seconds


def _client(limiter: _FakeLimiter) -> RiotClient:
    return RiotClient(
        "key-abcd1234",
        limiter=cast(Any, limiter),
        coalescer=cast(Any, None),
        cache=cast(Any, None),
    )


@pytest.fixture(autouse=True)
def _penalty_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "riot_penalty_enabled", True)


# --- target selection ------------------------------------------------------


def test_method_limit_freezes_the_method_bucket() -> None:
    client = _client(_FakeLimiter())
    assert client._penalty_targets(BUCKETS, "method") == [MATCH_V5_MATCH_BUCKET]


def test_missing_limit_type_defaults_to_the_method_bucket() -> None:
    client = _client(_FakeLimiter())
    assert client._penalty_targets(BUCKETS, None) == [MATCH_V5_MATCH_BUCKET]


def test_service_limit_penalizes_nothing() -> None:
    """A service-level 429 is Riot's capacity problem, not our key's budget —
    throttling ourselves would extend someone else's outage into our pipeline."""
    client = _client(_FakeLimiter())
    assert client._penalty_targets(BUCKETS, "service") == []


def test_application_limit_freezes_the_app_bucket_when_modelled() -> None:
    client = _client(_FakeLimiter(app_configured=True))
    assert client._penalty_targets(BUCKETS, "application") == [APP_BUCKET]


def test_application_limit_falls_back_to_the_method_bucket_when_unmodelled() -> None:
    """This key publishes no app-wide limit. If Riot enforces one anyway, the
    method bucket is the only lever that can slow the client down."""
    client = _client(_FakeLimiter(app_configured=False))
    assert client._penalty_targets(BUCKETS, "application") == [MATCH_V5_MATCH_BUCKET]


# --- penalty application ---------------------------------------------------


@pytest.mark.asyncio
async def test_retry_after_is_used_as_the_penalty_duration() -> None:
    limiter = _FakeLimiter()
    await _client(limiter)._apply_429_penalty(
        BUCKETS, {"X-Rate-Limit-Type": "method"}, retry_after=7.0
    )
    assert limiter.penalties == [([MATCH_V5_MATCH_BUCKET], 7.0)]


@pytest.mark.asyncio
async def test_missing_retry_after_falls_back_to_one_window() -> None:
    limiter = _FakeLimiter()
    await _client(limiter)._apply_429_penalty(BUCKETS, {}, retry_after=None)
    assert limiter.penalties == [([MATCH_V5_MATCH_BUCKET], _DEFAULT_429_PENALTY_SECONDS)]


@pytest.mark.asyncio
async def test_service_429_applies_no_penalty(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = _FakeLimiter()
    await _client(limiter)._apply_429_penalty(
        BUCKETS, {"X-Rate-Limit-Type": "service"}, retry_after=7.0
    )
    assert limiter.penalties == []


@pytest.mark.asyncio
async def test_penalty_can_be_disabled_by_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "riot_penalty_enabled", False)
    limiter = _FakeLimiter()
    await _client(limiter)._apply_429_penalty(
        BUCKETS, {"X-Rate-Limit-Type": "method"}, retry_after=7.0
    )
    assert limiter.penalties == []


@pytest.mark.asyncio
async def test_limit_type_header_casing_is_normalized() -> None:
    """Riot sends 'Application'; matching it case-sensitively would silently
    route the penalty to the wrong bucket."""
    limiter = _FakeLimiter(app_configured=True)
    await _client(limiter)._apply_429_penalty(
        BUCKETS, {"X-Rate-Limit-Type": "Application"}, retry_after=3.0
    )
    assert limiter.penalties == [([APP_BUCKET], 3.0)]
