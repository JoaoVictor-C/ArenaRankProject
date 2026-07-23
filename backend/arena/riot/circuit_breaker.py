"""Async circuit breaker for the Riot transport.

Failure model (proposal section 9.3):

- **Closed** (normal): calls flow through. We count failures inside a sliding
  10-second window. When 5 failures land within any 10s window, we trip to
  **Open**.
- **Open**: every call is rejected immediately with :class:`CircuitOpenError`
  (no network I/O) for a 30-second cooldown. This sheds load off a struggling
  upstream and fails fast for callers.
- **Half-Open** (after cooldown): a single trial call is allowed through. If it
  succeeds the circuit closes and counters reset; if it fails we re-open for
  another cooldown.

The breaker is in-process and protects one logical dependency (the Riot API).
It is intentionally not distributed: each worker process trips independently,
which is the desired blast radius — a single bad pod stops hammering Riot
without needing cross-node coordination. ``clock`` is injectable for tests.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TypeVar

from .errors import CircuitOpenError

T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


@dataclass(frozen=True, slots=True)
class CircuitConfig:
    """Trip after ``failure_threshold`` failures within ``window_seconds``;
    stay open for ``cooldown_seconds`` before a half-open trial."""

    failure_threshold: int = 5
    window_seconds: float = 10.0
    cooldown_seconds: float = 30.0


@dataclass(slots=True)
class _CircuitInternals:
    state: CircuitState = CircuitState.CLOSED
    failures: deque[float] = field(default_factory=deque)
    opened_at: float = 0.0


class CircuitBreaker:
    """Trips open after repeated failures; rejects fast while open."""

    def __init__(
        self,
        config: CircuitConfig | None = None,
        *,
        name: str = "riot",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cfg = config or CircuitConfig()
        self._name = name
        self._clock = clock
        self._s = _CircuitInternals()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._s.state

    def _prune(self, now: float) -> None:
        cutoff = now - self._cfg.window_seconds
        failures = self._s.failures
        while failures and failures[0] < cutoff:
            failures.popleft()

    async def _before_call(self) -> None:
        """Gate entry; raise if open, transition to half-open after cooldown."""
        async with self._lock:
            now = self._clock()
            if self._s.state is CircuitState.OPEN:
                elapsed = now - self._s.opened_at
                if elapsed >= self._cfg.cooldown_seconds:
                    # Cooldown elapsed: allow exactly one trial through.
                    self._s.state = CircuitState.HALF_OPEN
                    return
                raise CircuitOpenError(self._name, self._cfg.cooldown_seconds - elapsed)
            # CLOSED or HALF_OPEN both permit the call.

    async def _on_success(self) -> None:
        async with self._lock:
            self._s.failures.clear()
            self._s.state = CircuitState.CLOSED

    async def _on_failure(self) -> None:
        async with self._lock:
            now = self._clock()
            if self._s.state is CircuitState.HALF_OPEN:
                # Trial failed -> straight back to open for a fresh cooldown.
                self._s.state = CircuitState.OPEN
                self._s.opened_at = now
                return
            self._s.failures.append(now)
            self._prune(now)
            if len(self._s.failures) >= self._cfg.failure_threshold:
                self._s.state = CircuitState.OPEN
                self._s.opened_at = now
                self._s.failures.clear()

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Run ``fn`` under the breaker.

        Raises :class:`CircuitOpenError` immediately if open. Any exception from
        ``fn`` is recorded as a failure and re-raised; success resets the breaker.
        """
        await self._before_call()
        try:
            result = await fn()
        except Exception:
            await self._on_failure()
            raise
        await self._on_success()
        return result
