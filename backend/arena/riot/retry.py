"""Exponential backoff with jitter for transient Riot failures.

Retries are attempted only on HTTP 429 (rate limited) and 503 (service
unavailable). On 429/503 Riot usually sends a ``Retry-After`` header; when
present it is authoritative and we wait at least that long. Otherwise we fall
back to capped exponential backoff with full jitter (AWS-style), which spreads
retries from many workers so they do not synchronize into a thundering herd.

This module is transport-agnostic: it exposes the policy + a small async runner
that the client wraps around a single attempt callable. The runner does not know
about httpx — it works on ``RetryDecision`` values the caller produces.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from typing import TypeVar

T = TypeVar("T")

# Status codes worth retrying. 429 = rate limited, 503 = service unavailable.
RETRYABLE_STATUSES = frozenset({429, 503})


def parse_retry_after(headers: Mapping[str, str]) -> float | None:
    """Parse ``Retry-After`` as seconds.

    Riot sends an integer number of seconds. We accept a bare float too. A
    missing or unparseable header returns ``None`` so the caller uses backoff.
    """
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Capped exponential backoff with full jitter."""

    max_retries: int = 4
    base_delay: float = 0.5  # seconds for the first backoff
    max_delay: float = 20.0  # cap on any single backoff
    multiplier: float = 2.0

    def backoff(self, attempt: int, *, rng: random.Random | None = None) -> float:
        """Full-jitter backoff for a 0-indexed retry ``attempt``.

        ``delay = random_uniform(0, min(max_delay, base * multiplier**attempt))``.
        """
        ceiling = min(self.max_delay, self.base_delay * (self.multiplier**attempt))
        r = rng or random
        return r.uniform(0.0, ceiling)

    def delay_for(
        self,
        attempt: int,
        retry_after: float | None,
        *,
        rng: random.Random | None = None,
    ) -> float:
        """Resolve the wait before the next attempt.

        ``Retry-After`` is honored as a floor; we still add jittered backoff on
        top so concurrent workers do not all wake at the exact same instant.
        """
        jitter = self.backoff(attempt, rng=rng)
        if retry_after is not None:
            return retry_after + min(jitter, self.base_delay)
        return jitter


class RetryAction(Enum):
    """What the runner should do after one attempt."""

    RETURN = auto()  # success — return the value
    RETRY = auto()  # transient — wait then retry
    RAISE = auto()  # permanent — propagate the error


@dataclass(slots=True)
class RetryDecision:
    """Outcome of evaluating a single attempt.

    ``value`` carries the success result on RETURN; ``retry_after`` carries the
    parsed header (if any) on RETRY; ``error`` carries the exception to raise on
    RAISE (or the last error to surface when retries are exhausted).
    """

    action: RetryAction
    value: object = None
    retry_after: float | None = None
    error: BaseException | None = None


async def run_with_retry(
    attempt: Callable[[], Awaitable[RetryDecision]],
    policy: RetryPolicy,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rng: random.Random | None = None,
) -> object:
    """Drive ``attempt`` under ``policy`` until success, exhaustion, or RAISE.

    ``attempt`` is called once per try and must classify its own result into a
    :class:`RetryDecision`. Exhausting retries re-raises the last RETRY's
    ``error`` (set by the caller) so the failure surfaces with context.
    """
    last_error: BaseException | None = None
    for i in range(policy.max_retries + 1):
        decision = await attempt()
        if decision.action is RetryAction.RETURN:
            return decision.value
        if decision.action is RetryAction.RAISE:
            assert decision.error is not None
            raise decision.error
        # RETRY
        last_error = decision.error
        if i >= policy.max_retries:
            break
        await sleep(policy.delay_for(i, decision.retry_after, rng=rng))
    if last_error is not None:
        raise last_error
    raise RuntimeError("retry loop exhausted without an error")
