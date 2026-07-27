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

from collections.abc import Mapping
from typing import Any

import httpx
from redis.asyncio import Redis

from ..core.config import settings
from ..core.logging import get_logger
from .cache import DEFAULT_TTL_SECONDS, MatchCache, OverflowStore
from .circuit_breaker import CircuitBreaker, CircuitConfig
from .coalesce import RequestCoalescer
from .limit_headers import parse_rate_limit_headers, record_observed
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

#: Fallback penalty when a 429 arrives without ``Retry-After``. One match-v5
#: window: the shortest wait that can actually clear a per-method limit.
_DEFAULT_429_PENALTY_SECONDS = 10.0


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
        metrics_redis: Any | None = None,
    ) -> None:
        self._key = api_key
        self._limiter = limiter
        self._coalescer = coalescer
        self._cache = cache
        self._circuit = circuit or CircuitBreaker(CircuitConfig())
        self._retry = retry_policy or RetryPolicy()
        self._default_region = default_region
        self._http = http or httpx.AsyncClient(
            timeout=timeout,
            # Explicit pool sizing: httpx defaults to 100 total / 20 keepalive,
            # which silently serializes the client well below the Riot budget
            # once the sweep and bulk workers run at their configured widths.
            limits=httpx.Limits(
                max_connections=settings.riot_http_max_connections,
                max_keepalive_connections=settings.riot_http_max_keepalive,
            ),
        )
        self._worker_id = worker_id
        # Optional Redis for admin-console usage counters. None => no recording
        # (metrics are best-effort and must never gate a Riot call).
        self._metrics_redis = metrics_redis

    @property
    def _key_suffix(self) -> str:
        """Last 8 chars of the key — the same scoping the limiter uses."""
        return self._key[-8:] if self._key else "anon"

    async def _note_attempt(
        self,
        buckets: list[str],
        status: int | None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """Count one outbound Riot call (and its failure kind) for /admin/riot/usage.

        ``status is None`` means the request never got an HTTP response
        (transport error). Recorded per rate-limit bucket as well as in total,
        so the console can attribute usage to the limit it actually consumes.

        When Riot sent its rate-limit headers we also snapshot them: those are
        the *authoritative* limits, against which our configured buckets are
        only a model (see :mod:`arena.riot.limit_headers`).
        """
        from arena.core import metrics

        counts: dict[str, int] = {metrics.EVENT_RIOT_REQUEST: 1}
        # The most specific configured bucket is the meaningful one (APP_BUCKET
        # leads the list and is usually disabled for this key).
        scope = next((b for b in buckets if b != APP_BUCKET), None)
        if scope is not None:
            counts[f"{metrics.EVENT_RIOT_REQUEST}:{scope}"] = 1
        if status == 429:
            counts[metrics.EVENT_RIOT_429] = 1
        elif status is None or status >= 400:
            counts[metrics.EVENT_RIOT_ERROR] = 1
        await metrics.record_many(self._metrics_redis, counts)

        if headers is not None and scope is not None:
            observed = parse_rate_limit_headers(headers)
            await record_observed(self._metrics_redis, self._key_suffix, scope, observed)

    async def __aenter__(self) -> RiotClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.aclose()

    # -- core request path --------------------------------------------------

    def _penalty_targets(self, buckets: list[str], limit_type: str | None) -> list[str]:
        """Which buckets a 429 should freeze, per Riot's ``X-Rate-Limit-Type``.

        - ``service``: a downstream capacity problem, not our key's budget —
          penalizing would throttle us for someone else's outage, so we don't.
        - ``application``: the app-wide bucket, when we model one. This key
          publishes no app-wide limit, so if Riot ever enforces one anyway the
          method bucket is the only lever we have to slow the client down.
        - ``method`` or absent: the method bucket (the common case).
        """
        if limit_type == "service":
            return []
        method = [b for b in buckets if b != APP_BUCKET]
        if limit_type == "application":
            return [APP_BUCKET] if self._limiter.configured(APP_BUCKET) else method
        return method

    async def _apply_429_penalty(
        self, buckets: list[str], headers: Mapping[str, str], retry_after: float | None
    ) -> None:
        """Freeze the offending bucket for ``Retry-After`` after a 429.

        Without this the retry only slows down the coroutine that got rejected;
        every other in-flight caller keeps spending tokens the model still
        thinks exist, turning one 429 into a burst of them.
        """
        if not settings.riot_penalty_enabled:
            return
        limit_type = parse_rate_limit_headers(headers).limit_type
        targets = self._penalty_targets(buckets, limit_type)
        if not targets:
            return
        # No Retry-After (Riot usually sends one) -> fall back to a single
        # refill window, which is the shortest wait that can clear the limit.
        seconds = retry_after if retry_after is not None else _DEFAULT_429_PENALTY_SECONDS
        applied = await self._limiter.penalize(self._key, targets, seconds=seconds)
        if applied > 0:
            _log.warning(
                "riot.client.rate_limited",
                limitType=limit_type or "unknown",
                buckets=targets,
                penaltySeconds=round(applied, 2),
            )

    async def _perform(self, url: str, buckets: list[str]) -> object:
        """One fully-protected GET: rate limit -> circuit -> retry -> HTTP.

        Returns the parsed JSON body (object or array — the caller asserts the
        shape it expects) or raises a typed :mod:`arena.riot.errors` error.
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
                await self._note_attempt(buckets, None)
                return RetryDecision(
                    action=RetryAction.RETRY,
                    error=RiotServerError(503, url, str(exc)),
                )

            status = resp.status_code
            await self._note_attempt(buckets, status, resp.headers)
            if status == 200:
                return RetryDecision(action=RetryAction.RETURN, value=resp.json())
            if status == 404:
                return RetryDecision(action=RetryAction.RAISE, error=RiotNotFoundError(url))
            if status in RETRYABLE_STATUSES:
                retry_after = parse_retry_after(resp.headers)
                if status == 429:
                    await self._apply_429_penalty(buckets, resp.headers, retry_after)
                    err: Exception = RiotRateLimitError(retry_after)
                else:
                    err = RiotServerError(status, url)
                return RetryDecision(action=RetryAction.RETRY, retry_after=retry_after, error=err)
            # Other 4xx/5xx -> non-retryable.
            return RetryDecision(action=RetryAction.RAISE, error=RiotHTTPError(status, url))

        try:
            return await run_with_retry(attempt, self._retry)
        except CircuitOpenError:
            _log.warning("riot.client.circuit_open", url=_redact(url))
            raise

    async def _request_json(self, url: str, buckets: list[str]) -> dict[str, Any]:
        """GET an endpoint whose body is a JSON object."""
        result = await self._perform(url, buckets)
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
        """GET an endpoint whose body is a top-level JSON array (match-v5 ids)."""
        result = await self._perform(url, buckets)
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
    limiter = RedisTokenBucketLimiter(
        redis,
        default_arena_buckets(
            app_capacity=settings.riot_app_bucket_capacity,
            app_refill_seconds=settings.riot_app_bucket_refill_seconds,
            match_v5_capacity=settings.riot_match_v5_bucket_capacity,
            match_v5_refill_seconds=settings.riot_match_v5_bucket_refill_seconds,
            headroom=settings.riot_bucket_headroom,
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
        # Same Redis the limiter uses — feeds /admin/riot/usage counters.
        metrics_redis=redis,
    )
