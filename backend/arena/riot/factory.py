"""Process-wide Riot client factory for the workers (Wave-2 seam closer).

``arena.workers.deps.get_riot_client`` resolves the client via
``from arena.riot import get_client``. This module provides that ``get_client``:
it builds the real resilient :class:`~arena.riot.client.RiotClient` from settings
and wraps it in a thin adapter exposing the exact surface the workers program
against (:class:`arena.workers.deps.RiotClient`): ``list_match_ids`` plus a
``get_match`` that returns ``None`` (not a raised error) on a 404, per that
protocol's ``dict | None`` contract.

The adapter exists because the worker protocol's method names / return shapes
differ from the real client (``list_match_ids`` vs ``get_match_ids_by_puuid``;
``get_match -> dict | None`` vs raising :class:`RiotNotFoundError`). Bridging
here keeps both the workers and the real client unchanged.
"""

from __future__ import annotations

from typing import Any

from redis.asyncio import Redis

from arena.core.config import settings
from arena.riot.client import RiotClient, build_default_client
from arena.riot.errors import RiotNotFoundError


class _WorkerRiotClient:
    """Adapter exposing the workers' minimal Riot surface over the real client."""

    __slots__ = ("_real",)

    def __init__(self, real: RiotClient) -> None:
        self._real = real

    async def list_match_ids(
        self,
        puuid: str,
        *,
        start: int = 0,
        count: int = 20,
        queue: int | None = None,
        start_time: int | None = None,
    ) -> list[str]:
        # match-v5 filters a single queue per call; callers that need several
        # queues iterate settings.live_queue_ids (one call per id — empty
        # results are cheap). queue=None preserves the unfiltered behavior
        # (used by the rotation-detection deep sample, bounded by start_time).
        # The processor's authoritative filter still drops anything ineligible.
        return await self._real.get_match_ids_by_puuid(
            puuid, start=start, count=count, queue=queue, start_time=start_time
        )

    async def get_match_ids_by_puuid(
        self,
        puuid: str,
        *,
        start: int = 0,
        count: int = 20,
        queue: int | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[str]:
        """MatchSource-compatible passthrough to the real client's canonical method."""
        return await self._real.get_match_ids_by_puuid(
            puuid,
            start=start,
            count=count,
            queue=queue,
            start_time=start_time,
            end_time=end_time,
        )

    async def get_match(self, riot_match_id: str) -> dict[str, Any] | None:
        try:
            return await self._real.get_match(riot_match_id)
        except RiotNotFoundError:
            # The worker protocol models "no such match" as None, not an error.
            return None


_client: _WorkerRiotClient | None = None


def get_client() -> _WorkerRiotClient:
    """Return the process-wide worker Riot client (built once, lazily).

    Construction is connection-free (Redis/httpx connect lazily), so this is safe
    to call from a synchronous context and from import-order-sensitive wiring.
    The Riot key comes from ``settings.riot_api_key`` (empty in dev; required for
    real ingestion).
    """
    global _client
    if _client is None:
        redis: Redis = Redis.from_url(settings.redis_url)
        real = build_default_client(
            settings.riot_api_key,
            redis=redis,
            cache_ttl_seconds=settings.riot_match_cache_ttl_seconds,
        )
        _client = _WorkerRiotClient(real)
    return _client


__all__ = ["get_client"]
