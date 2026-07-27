"""process_match retry/DLQ classification (no DB — Riot client is faked).

Regression coverage for a real incident: a batch of matches were dead-lettered
with "Circuit 'riot' is open" after exactly 0 useful attempts, because the
fixed retry backoff (0s/2s/5s) is far shorter than the circuit breaker's own
30s cooldown — every retry landed inside the SAME open window and the job
burned all MAX_TRIES before the breaker ever had a chance to close.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from arq.worker import Retry

from arena.riot.errors import CircuitOpenError, RiotRateLimitError
from arena.workers import processor
from arena.workers import queues as Q
from tests.workers.conftest import FakeRedis


class _RaisingClient:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def get_match(self, match_id: str) -> dict[str, Any]:
        raise self._exc


def test_retry_after_hint_uses_circuit_open_retry_after() -> None:
    hint = processor._retry_after_hint(CircuitOpenError("riot", 22.5))
    assert hint == 22.5


def test_retry_after_hint_uses_rate_limit_retry_after() -> None:
    hint = processor._retry_after_hint(RiotRateLimitError(retry_after=4.0))
    assert hint == 4.0


def test_retry_after_hint_caps_pathological_values() -> None:
    hint = processor._retry_after_hint(CircuitOpenError("riot", 999.0))
    assert hint == processor._MAX_HINTED_DEFER_SECONDS


def test_retry_after_hint_none_for_unrelated_errors() -> None:
    assert processor._retry_after_hint(RuntimeError("boom")) is None
    assert processor._retry_after_hint(RiotRateLimitError(retry_after=None)) is None


async def test_process_match_defers_by_the_circuit_s_own_cooldown(
    fake_redis: FakeRedis, monkeypatch: Any
) -> None:
    """A CircuitOpenError on try 1 must defer ~its own retry_after, not the
    generic 2s table entry — giving the retry a real chance to land after the
    breaker's cooldown instead of firing blind into the same open window."""
    monkeypatch.setattr(processor, "get_riot_client", lambda: _RaisingClient(CircuitOpenError("riot", 22.5)))

    with pytest.raises(Retry) as exc_info:
        await processor.process_match({"redis": fake_redis, "job_try": 1}, "BR1_TEST")

    assert exc_info.value.defer_score == pytest.approx(22_500, abs=50)
    # The in-flight idempotency flag must be released so the deferred retry
    # is not short-circuited by its own prior SET NX.
    assert await fake_redis.get(Q.processed_flag_key("BR1_TEST")) is None


async def test_process_match_falls_back_to_generic_backoff_for_other_errors(
    fake_redis: FakeRedis, monkeypatch: Any
) -> None:
    """An ordinary error (no retry_after of its own) keeps using the fixed
    backoff table — this fix only changes behavior for errors that actually
    carry a wait-time hint."""
    monkeypatch.setattr(processor, "get_riot_client", lambda: _RaisingClient(RuntimeError("db blip")))

    with pytest.raises(Retry) as exc_info:
        await processor.process_match({"redis": fake_redis, "job_try": 1}, "BR1_TEST2")

    assert exc_info.value.defer_score == pytest.approx(int(processor._backoff_for(2) * 1000), abs=5)


async def test_process_match_dead_letters_with_the_fields_admin_reads(
    fake_redis: FakeRedis, monkeypatch: Any
) -> None:
    """On the final attempt the DLQ entry must carry the exact keys the admin
    API's `_live_dlq_items` reads (`tries`, `error`, `deadLetteredAt`,
    `matchId`) — a prior key-name mismatch (`attempts`/`ts`) made every DLQ
    row read back as "0×" / "just now" regardless of the real values."""
    monkeypatch.setattr(processor, "get_riot_client", lambda: _RaisingClient(CircuitOpenError("riot", 22.5)))

    result = await processor.process_match({"redis": fake_redis, "job_try": processor.MAX_TRIES}, "BR1_TEST3")

    assert result["status"] == "dead_lettered"
    raw = fake_redis._lists[Q.DLQ_KEY]
    assert len(raw) == 1
    entry = json.loads(raw[0])
    assert entry["matchId"] == "BR1_TEST3"
    assert entry["tries"] == processor.MAX_TRIES
    assert "Circuit 'riot' is open" in entry["error"]
    assert isinstance(entry["deadLetteredAt"], (int, float))
