"""Async Riot API client — the package's public entry point.

Wraps ``httpx.AsyncClient`` with the full resilience stack from proposal §9.3:

    rate limit (Redis token bucket) -> circuit breaker -> retry/backoff -> HTTP

and request coalescing + a 24h cache on the match-fetch path. Methods:

- :meth:`get_account_by_riot_id` — resolve a Riot ID to a PUUID (account-v1).
- :meth:`get_match_ids_by_puuid` — list recent MatchIDs (match-v5).
- :meth:`get_match` — fetch one match, cache-first + coalesced (match-v5).

Regional routing (americas/europe/asia) is chosen per call; a default region is
configured at construction. Errors surface as the package's typed exceptions
(:mod:`arena.riot.errors`) — callers translate to PT-BR API responses upstream;
no raw Riot payloads, mu/sigma, or winrate internals leak from here.
"""

from __future__ import annotations

from typing import Any

import httpx
from redis.asyncio import Redis

from ..core.logging import get_logger
from .cache import DEFAULT_TTL_SECONDS, MatchCache, OverflowStore
from .circuit_breaker import CircuitBreaker, CircuitConfig
from .coalesce import RequestCoalescer
from .errors import (
    CircuitOpenError,
    RiotHTTPError,
    RiotNotFoundError,
    RiotRateLimitError,
    RiotServerError,
)
from .rate_limit import (
    ACCOUNT_V1_BUCKET,
    APP_BUCKET,
    MATCH_V5_IDS_BUCKET,
    MATCH_V5_MATCH_BUCKET,
    RedisTokenBucketLimiter,
    default_arena_buckets,
)
from .retry import (
    RETRYABLE_STATUSES,
    RetryAction,
    RetryDecision,
    RetryPolicy,
    parse_retry_after,
    run_with_retry,
)
from .routing import Region, account_by_riot_id_url, match_detail_url, match_ids_by_puuid_url

_log = get_logger(__name__)


class RiotClient:
    """Resilient async Riot API client. Use as an async context manager."""

    def __init__(
        self,
        api_key: str,
        *,
        limiter: RedisTokenBucketLimiter,
        coalescer: RequestCoalescer[dict[str, Any]],
        cache: MatchCache,
        circuit: CircuitBreaker | None = None,
        retry_policy: RetryPolicy | None = None,
        default_region: Region = Region.AMERICAS,
        http: httpx.AsyncClient | None = None,
        worker_id: str = "riot-client",
        timeout: float = 10.0,
    ) -> None:
        self._key = api_key
        self._limiter = limiter
        self._coalescer = coalescer
        self._cache = cache
        self._circuit = circuit or CircuitBreaker(CircuitConfig())
        self._retry = retry_policy or RetryPolicy()
        self._default_region = default_region
        self._http = http or httpx.AsyncClient(timeout=timeout)
        self._worker_id = worker_id

    async def __aenter__(self) -> RiotClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.aclose()

    # -- core request path --------------------------------------------------

    async def _request_json(self, url: str, buckets: list[str]) -> dict[str, Any]:
        """One fully-protected GET: rate limit -> circuit -> retry -> HTTP.

        Returns parsed JSON or raises a typed :mod:`arena.riot.errors` error.
        """

        async def attempt() -> RetryDecision:
            # Rate limit gate (blocks until tokens are available across buckets).
            await self._limiter.acquire(self._key, buckets)

            async def do_get() -> httpx.Response:
                return await self._http.get(url, headers={"X-Riot-Token": self._key})

            try:
                resp = await self._circuit.call(do_get)
            except httpx.TransportError as exc:
                # Network-level failure: counts toward the breaker, retryable.
                return RetryDecision(
                    action=RetryAction.RETRY,
                    error=RiotServerError(503, url, str(exc)),
                )

            status = resp.status_code
            if status == 200:
                return RetryDecision(action=RetryAction.RETURN, value=resp.json())
            if status == 404:
                return RetryDecision(action=RetryAction.RAISE, error=RiotNotFoundError(url))
            if status in RETRYABLE_STATUSES:
                retry_after = parse_retry_after(resp.headers)
                err: Exception = (
                    RiotRateLimitError(retry_after)
                    if status == 429
                    else RiotServerError(status, url)
                )
                return RetryDecision(action=RetryAction.RETRY, retry_after=retry_after, error=err)
            # Other 4xx/5xx -> non-retryable.
            return RetryDecision(action=RetryAction.RAISE, error=RiotHTTPError(status, url))

        try:
            result = await run_with_retry(attempt, self._retry)
        except CircuitOpenError:
            _log.warning("riot.client.circuit_open", url=_redact(url))
            raise
        assert isinstance(result, dict)
        return result

    # -- public endpoints ---------------------------------------------------

    async def get_account_by_riot_id(
        self, game_name: str, tag_line: str, *, region: Region | None = None
    ) -> dict[str, Any]:
        """Resolve a Riot ID (gameName#tagLine) to an account (PUUID)."""
        reg = region or self._default_region
        url = account_by_riot_id_url(game_name, tag_line, reg)
        return await self._request_json(url, [APP_BUCKET, ACCOUNT_V1_BUCKET])

    async def get_match_ids_by_puuid(
        self,
        puuid: str,
        *,
        region: Region | None = None,
        start: int = 0,
        count: int = 20,
        queue: int | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[str]:
        """List recent MatchIDs for a PUUID (match-v5)."""
        reg = region or self._default_region
        url = match_ids_by_puuid_url(
            puuid,
            reg,
            start=start,
            count=count,
            queue=queue,
            start_time=start_time,
            end_time=end_time,
        )
        # match-v5 ids returns a JSON array, not an object: fetch raw.
        result = await self._request_array(url, [APP_BUCKET, MATCH_V5_IDS_BUCKET])
        return [str(m) for m in result]

    async def get_match(self, match_id: str, *, region: Region | None = None) -> dict[str, Any]:
        """Fetch one match, cache-first and coalesced across workers (match-v5).

        Identical concurrent fetches collapse to a single Riot call; the result
        is cached for 24h (with optional S3 overflow).
        """
        reg = region or self._default_region

        async def loader() -> dict[str, Any]:
            url = match_detail_url(match_id, reg)
            payload = await self._request_json(url, [APP_BUCKET, MATCH_V5_MATCH_BUCKET])
            await self._cache.set(match_id, payload)
            return payload

        return await self._coalescer.fetch(
            match_id,
            loader=loader,
            read_result=lambda: self._cache.get(match_id),
            owner_id=self._worker_id,
        )

    # -- array variant for endpoints returning a top-level JSON list --------

    async def _request_array(self, url: str, buckets: list[str]) -> list[Any]:
        async def attempt() -> RetryDecision:
            await self._limiter.acquire(self._key, buckets)

            async def do_get() -> httpx.Response:
                return await self._http.get(url, headers={"X-Riot-Token": self._key})

            try:
                resp = await self._circuit.call(do_get)
            except httpx.TransportError as exc:
                return RetryDecision(
                    action=RetryAction.RETRY,
                    error=RiotServerError(503, url, str(exc)),
                )

            status = resp.status_code
            if status == 200:
                return RetryDecision(action=RetryAction.RETURN, value=resp.json())
            if status == 404:
                return RetryDecision(action=RetryAction.RAISE, error=RiotNotFoundError(url))
            if status in RETRYABLE_STATUSES:
                retry_after = parse_retry_after(resp.headers)
                err: Exception = (
                    RiotRateLimitError(retry_after)
                    if status == 429
                    else RiotServerError(status, url)
                )
                return RetryDecision(action=RetryAction.RETRY, retry_after=retry_after, error=err)
            return RetryDecision(action=RetryAction.RAISE, error=RiotHTTPError(status, url))

        result = await run_with_retry(attempt, self._retry)
        assert isinstance(result, list)
        return result


def _redact(url: str) -> str:
    """Trim a URL to host+path for logs (query may carry a PUUID)."""
    return url.split("?", 1)[0]


def build_default_client(
    api_key: str,
    *,
    redis: Redis,
    overflow: OverflowStore | None = None,
    default_region: Region = Region.AMERICAS,
    worker_id: str = "riot-client",
    cache_ttl_seconds: int | None = None,
) -> RiotClient:
    """Convenience factory wiring the standard Arena resilience stack.

    Builds the Redis token-bucket limiter (Riot production-key limits), the
    request coalescer, the match cache (with optional S3 overflow), a fresh
    circuit breaker, and a default retry policy. ``cache_ttl_seconds`` overrides
    the match-cache TTL (``None`` keeps the 24h default) — production sets it low
    so the ~135KB payloads don't saturate a small Redis.
    """
    from ..core.config import settings

    limiter = RedisTokenBucketLimiter(
        redis,
        default_arena_buckets(
            app_capacity=settings.riot_app_bucket_capacity,
            app_refill_seconds=settings.riot_app_bucket_refill_seconds,
            match_v5_capacity=settings.riot_match_v5_bucket_capacity,
            match_v5_refill_seconds=settings.riot_match_v5_bucket_refill_seconds,
        ),
    )
    coalescer: RequestCoalescer[dict[str, Any]] = RequestCoalescer(redis)
    cache = MatchCache(
        redis,
        overflow=overflow,
        ttl_seconds=cache_ttl_seconds if cache_ttl_seconds is not None else DEFAULT_TTL_SECONDS,
    )
    return RiotClient(
        api_key,
        limiter=limiter,
        coalescer=coalescer,
        cache=cache,
        default_region=default_region,
        worker_id=worker_id,
    )
