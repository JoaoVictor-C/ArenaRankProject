"""Riot API client package (proposal section 9.3).

A resilient async wrapper over ``httpx.AsyncClient`` for the endpoints the Arena
ingestion pipeline needs, plus the supporting resilience primitives:

- :mod:`~arena.riot.client`         — ``RiotClient`` (the public entry point)
- :mod:`~arena.riot.rate_limit`     — Redis + Lua atomic token-bucket limiter
- :mod:`~arena.riot.retry`          — exp backoff + jitter honoring Retry-After
- :mod:`~arena.riot.circuit_breaker`— open after 5 fails/10s, half-open after 30s
- :mod:`~arena.riot.coalesce`       — in-flight de-dup of identical match fetches
- :mod:`~arena.riot.cache`          — 24h Redis cache + injectable S3 overflow
- :mod:`~arena.riot.arena`          — Arena match-v5 parsing (queue 1700/1750)
- :mod:`~arena.riot.routing`        — regional + platform host routing
- :mod:`~arena.riot.errors`         — typed exception hierarchy

Boundary rule: nothing here surfaces raw Riot payloads, mu/sigma, or item
winrate to the UI — callers translate to CR/Pontos + PT-BR upstream.
"""

from __future__ import annotations

from .arena import (
    ARENA_GAME_MODE,
    ARENA_QUEUE_DUOS,
    ARENA_QUEUE_DUOS_S2,
    ARENA_QUEUE_IDS,
    ARENA_QUEUE_TRIOS,
    ArenaMode,
    NotAnArenaMatch,
    ParsedArenaMatch,
    ParsedParticipant,
    ParsedSubteam,
    is_arena_queue,
    mode_for_queue,
    parse_arena_match,
)
from .cache import DEFAULT_TTL_SECONDS, MatchCache, OverflowStore
from .circuit_breaker import CircuitBreaker, CircuitConfig, CircuitState
from .client import RiotClient, build_default_client
from .coalesce import RequestCoalescer
from .errors import (
    CircuitOpenError,
    RiotError,
    RiotHTTPError,
    RiotNotFoundError,
    RiotRateLimitError,
    RiotServerError,
)
from .rate_limit import (
    RedisTokenBucketLimiter,
    TokenBucketConfig,
    default_arena_buckets,
)
from .retry import RetryPolicy, parse_retry_after, run_with_retry
from .routing import Platform, Region

# NB: imported last — it depends on .client / .errors / ..core.config, all above.
from .factory import get_client

__all__ = [
    # client
    "RiotClient",
    "build_default_client",
    "get_client",
    # routing
    "Region",
    "Platform",
    # rate limit
    "RedisTokenBucketLimiter",
    "TokenBucketConfig",
    "default_arena_buckets",
    # retry
    "RetryPolicy",
    "run_with_retry",
    "parse_retry_after",
    # circuit breaker
    "CircuitBreaker",
    "CircuitConfig",
    "CircuitState",
    # coalesce
    "RequestCoalescer",
    # cache
    "MatchCache",
    "OverflowStore",
    "DEFAULT_TTL_SECONDS",
    # arena parsing
    "parse_arena_match",
    "ParsedArenaMatch",
    "ParsedSubteam",
    "ParsedParticipant",
    "ArenaMode",
    "NotAnArenaMatch",
    "is_arena_queue",
    "mode_for_queue",
    "ARENA_QUEUE_DUOS",
    "ARENA_QUEUE_DUOS_S2",
    "ARENA_QUEUE_TRIOS",
    "ARENA_QUEUE_IDS",
    "ARENA_GAME_MODE",
    # errors
    "RiotError",
    "RiotHTTPError",
    "RiotNotFoundError",
    "RiotRateLimitError",
    "RiotServerError",
    "CircuitOpenError",
]
