"""Riot client exception hierarchy.

These are internal/operational errors (never user-facing), so plain English is
fine. Callers map them to PT-BR API responses at the service/router layer; raw
Riot payloads, mu/sigma and winrate internals must never leak past that boundary.
"""

from __future__ import annotations


class RiotError(Exception):
    """Base class for every error raised by the Riot client package."""


class RiotHTTPError(RiotError):
    """A non-retryable HTTP error response from the Riot API.

    ``status`` is the HTTP status code; ``url`` is included for log correlation
    only (it may contain a PUUID, so it is never surfaced to the UI).
    """

    def __init__(self, status: int, url: str, message: str | None = None) -> None:
        self.status = status
        self.url = url
        super().__init__(message or f"Riot API returned HTTP {status}")


class RiotNotFoundError(RiotHTTPError):
    """HTTP 404 — account / match not found upstream."""

    def __init__(self, url: str, message: str | None = None) -> None:
        super().__init__(404, url, message or "Riot resource not found")


class RiotRateLimitError(RiotError):
    """HTTP 429 exhausted all retries (or a hard local bucket failure)."""

    def __init__(self, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(
            "Riot API rate limit exceeded"
            + (f" (retry after {retry_after}s)" if retry_after is not None else "")
        )


class RiotServerError(RiotHTTPError):
    """HTTP 5xx from Riot after retries were exhausted."""


class CircuitOpenError(RiotError):
    """The circuit breaker is open; the call was rejected before any I/O."""

    def __init__(self, name: str, retry_after: float) -> None:
        self.name = name
        self.retry_after = retry_after
        super().__init__(f"Circuit '{name}' is open; retry in ~{retry_after:.1f}s")
