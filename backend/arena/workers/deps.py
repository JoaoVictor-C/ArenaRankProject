"""Shared worker dependencies: Redis settings, arq pool, and Wave-2 seams.

This module owns the *boundaries* between the workers and the rest of the
backend so the three worker modules stay thin:

* :func:`redis_settings` / :func:`create_redis_pool` — arq's Redis wiring,
  derived from :data:`arena.core.config.settings.redis_url`.
* :class:`RiotClient` / :class:`RatingService` — structural *protocols* the
  workers program against. The concrete implementations land in Wave 2
  (``arena.riot`` and ``arena.services.rating_service``); :func:`get_riot_client`
  and :func:`get_rating_service` resolve them lazily and defensively, returning
  ``None`` (logged once) when the W2 module is not yet importable. This mirrors
  the import-order tolerance already used in :mod:`arena.db.session` and keeps
  ``arena.workers`` importable / ruff-clean before W2 exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from arq.connections import RedisSettings, create_pool

from arena.core.config import settings
from arena.core.logging import get_logger

if TYPE_CHECKING:
    from arq.connections import ArqRedis

_log = get_logger("arena.workers.deps")


# ---------------------------------------------------------------------------
# Redis / arq wiring
# ---------------------------------------------------------------------------


def redis_settings() -> RedisSettings:
    """arq Redis settings parsed from ``settings.redis_url``.

    Centralized so every worker (and the ingestion producer) connects to the
    same instance with identical options.
    """
    return RedisSettings.from_dsn(settings.redis_url)


async def create_redis_pool() -> "ArqRedis":
    """Open a fresh arq Redis pool (caller is responsible for closing).

    Used by ingestion (which enqueues) and anywhere outside a worker context
    that needs to talk to Redis / arq. Inside a worker, prefer ``ctx['redis']``,
    which arq injects.
    """
    return await create_pool(redis_settings())


# ---------------------------------------------------------------------------
# Wave-2 seams (resolved lazily so workers import before W2 lands)
# ---------------------------------------------------------------------------


@runtime_checkable
class RiotClient(Protocol):
    """Minimal surface the workers need from the Wave-2 ``arena.riot`` client.

    The real client adds the token bucket, backoff, circuit breaker, coalescing
    and the 24h cache (proposal section 9.3); the workers only care about these
    two cache-first reads.
    """

    async def list_match_ids(
        self,
        puuid: str,
        *,
        start: int = 0,
        count: int = 20,
        queue: int | None = None,
        start_time: int | None = None,
    ) -> list[str]:
        """Recent Riot match ids for a puuid (newest first), optionally one
        queue and/or bounded to matches starting at/after ``start_time`` (epoch s)."""
        ...

    async def get_match(self, riot_match_id: str) -> dict[str, Any] | None:
        """Full match payload (Redis cache → Riot API), or ``None`` if absent."""


@runtime_checkable
class RatingService(Protocol):
    """The Wave-2 ``arena.services.rating_service`` transactional entrypoint.

    Owns the proposal section 13.2 write transaction: build the ``MatchInput``
    from the payload, run :func:`arena.rating.engine.rate`, and persist
    ``player_seasons`` / ``match_participants`` / ``champion_stats`` /
    ``cr_snapshots`` / ``integrity_events`` / ``matches.processed`` atomically
    under the per-player Redis lock. Returns a small JSON-serializable summary
    for the ``match.processed`` event.
    """

    async def process_match(
        self,
        riot_match_id: str,
        payload: dict[str, Any],
        *,
        redis: Any,
    ) -> dict[str, Any]:
        """Run + persist the full rating pipeline for one match."""


_RIOT_UNAVAILABLE_LOGGED = False
_RATING_UNAVAILABLE_LOGGED = False


def get_riot_client() -> RiotClient | None:
    """Resolve the Wave-2 Riot client, or ``None`` if not yet present.

    Logs the unavailability exactly once to avoid log spam on every poll tick.
    """
    global _RIOT_UNAVAILABLE_LOGGED
    try:
        from arena.riot import get_client
    except Exception:
        if not _RIOT_UNAVAILABLE_LOGGED:
            _log.warning("riot_client.unavailable", reason="arena.riot not importable (W2)")
            _RIOT_UNAVAILABLE_LOGGED = True
        return None
    client: RiotClient = get_client()
    return client


def get_rating_service() -> RatingService | None:
    """Resolve the Wave-2 rating service, or ``None`` if not yet present.

    Logs unavailability once. The processor treats ``None`` as a retryable
    condition (the dependency is expected to arrive), not a permanent failure.
    """
    global _RATING_UNAVAILABLE_LOGGED
    try:
        from arena.services.rating_service import get_rating_service as _factory
    except Exception:
        if not _RATING_UNAVAILABLE_LOGGED:
            _log.warning(
                "rating_service.unavailable",
                reason="arena.services.rating_service not importable (W2)",
            )
            _RATING_UNAVAILABLE_LOGGED = True
        return None
    service: RatingService = _factory()
    return service


__all__ = [
    "redis_settings",
    "create_redis_pool",
    "RiotClient",
    "RatingService",
    "get_riot_client",
    "get_rating_service",
]
