"""LeaderboardService — Redis read-through with Postgres fallback (Trinity #6).

Per the Trinity finding, the leaderboard is **not** a 30-second materialized
view. The hot Top-N is served from a Redis sorted set kept warm by the write
path (the rating service invalidates / the cache-warmer refreshes), with a
Postgres fallback that reads ``player_seasons`` ordered by ``cr DESC`` (the
``(season_id, cr DESC)`` index) on a cache miss, then back-fills Redis.

Two Redis structures per ``(season_id, format)`` scope:

* a **ZSET** ``arena:lb:{scope}`` ``member=player_id score=cr`` — gives O(log N)
  rank and range slicing for pagination and a player's own rank.
* a **HASH/JSON** row cache ``arena:lb:row:{scope}`` (optional) — denormalized
  display fields; on miss we hydrate from Postgres.

Reads return **CR/Pontos only** (never mu/sigma). ``rank`` is 1-based within the
scope. User-facing strings PT-BR. Ranking is by CR within format (contract).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from arena.core.logging import get_logger
from arena.db import models as m

_log = get_logger("arena.services.leaderboard")

_DEFAULT_TTL_S = 300  # 5 min — Top-1000 lane target (<5 min latency)
_KEY_PREFIX = "arena:lb:"


@dataclass(slots=True)
class LeaderboardEntry:
    """One ranked row (UI-safe; CR only — never mu/sigma)."""

    rank: int
    player_id: str
    cr: int


@dataclass(slots=True)
class LeaderboardPage:
    scope: str
    season_id: str
    format: str
    total: int
    updated_at: str  # ISO-8601
    rows: list[LeaderboardEntry]


class LeaderboardService:
    """Read-through cache over ``player_seasons`` ordered by CR.

    ``redis`` may be ``None`` (e.g. local/dev or a degraded mode) — every method
    then falls straight through to Postgres. This keeps the read path resilient:
    Redis is an accelerator, Postgres is the source of truth.
    """

    def __init__(self, redis: Redis | None, *, ttl_s: int = _DEFAULT_TTL_S) -> None:
        self._redis = redis
        self._ttl_s = ttl_s

    # -- keys --------------------------------------------------------------

    @staticmethod
    def _scope(season_id: str, fmt: str) -> str:
        return f"{season_id}:{fmt}"

    def _zset_key(self, scope: str) -> str:
        return f"{_KEY_PREFIX}z:{scope}"

    def _meta_key(self, scope: str) -> str:
        return f"{_KEY_PREFIX}meta:{scope}"

    # -- public read API ---------------------------------------------------

    async def get_page(
        self,
        session: AsyncSession,
        *,
        season_id: str,
        fmt: str,
        offset: int = 0,
        limit: int = 100,
    ) -> LeaderboardPage:
        """Return a ranked page. Redis ZSET first; Postgres fallback on miss.

        On a cache miss the relevant Top-N is rebuilt from Postgres and written
        back to Redis so subsequent reads in the window are served warm.
        """
        scope = self._scope(season_id, fmt)
        cached = await self._read_through_zset(scope, offset, limit)
        if cached is not None:
            rows, total, updated_at = cached
            return LeaderboardPage(
                scope=scope,
                season_id=season_id,
                format=fmt,
                total=total,
                updated_at=updated_at,
                rows=rows,
            )

        rows, total = await self._page_from_db(session, season_id, fmt, offset, limit)
        updated_at = datetime.now(UTC).isoformat()
        # Best-effort warm-up of the Top-N window (does not block correctness).
        await self._warm_from_db(session, scope, season_id, fmt)
        return LeaderboardPage(
            scope=scope,
            season_id=season_id,
            format=fmt,
            total=total,
            updated_at=updated_at,
            rows=rows,
        )

    async def get_player_rank(
        self,
        session: AsyncSession,
        *,
        season_id: str,
        fmt: str,
        player_id: str,
    ) -> int | None:
        """1-based rank of a player within the scope, or ``None`` if unranked.

        Uses ``ZREVRANK`` when the ZSET is warm; otherwise a single COUNT of
        players with strictly higher CR (the ``cr DESC`` index path).
        """
        scope = self._scope(season_id, fmt)
        if self._redis is not None:
            try:
                zkey = self._zset_key(scope)
                if await self._redis.exists(zkey):
                    pos = await self._redis.zrevrank(zkey, player_id)
                    return None if pos is None else int(pos) + 1
            except Exception:
                # Redis morreu depois do healthcheck da dependency: cai para o
                # caminho Postgres em vez de derrubar a requisição.
                _log.warning("leaderboard.redis.rank_failed", exc_info=True)

        own_cr = await session.execute(
            select(m.PlayerSeason.cr).where(
                m.PlayerSeason.season_id == season_id,
                m.PlayerSeason.player_id == player_id,
            )
        )
        cr = own_cr.scalar_one_or_none()
        if cr is None:
            return None
        higher = await session.execute(
            select(func.count())
            .select_from(m.PlayerSeason)
            .where(
                m.PlayerSeason.season_id == season_id,
                m.PlayerSeason.cr > cr,
            )
        )
        return int(higher.scalar_one()) + 1

    # -- write-path hooks (invalidation / warm) ----------------------------

    async def update_players(self, *, season_id: str, fmt: str, scores: dict[str, float]) -> None:
        """Upsert player CRs into the ZSET (called after a match commit).

        No-op when Redis is absent. This is the read-through "write side": the
        rating service hands the new CRs of the affected players so the hot set
        stays correct without a periodic MV refresh.
        """
        if self._redis is None or not scores:
            return
        scope = self._scope(season_id, fmt)
        zkey = self._zset_key(scope)
        try:
            await self._redis.zadd(zkey, {pid: float(cr) for pid, cr in scores.items()})
            await self._redis.expire(zkey, self._ttl_s)
            await self._touch_meta(scope)
        except Exception:
            _log.warning("leaderboard.redis.update_failed", exc_info=True)

    async def invalidate(self, *, season_id: str, fmt: str) -> None:
        """Drop the cached scope (forces a Postgres rebuild on next read)."""
        if self._redis is None:
            return
        scope = self._scope(season_id, fmt)
        try:
            await self._redis.delete(self._zset_key(scope), self._meta_key(scope))
        except Exception:
            _log.warning("leaderboard.redis.invalidate_failed", exc_info=True)

    # -- internals ---------------------------------------------------------

    async def _read_through_zset(
        self, scope: str, offset: int, limit: int
    ) -> tuple[list[LeaderboardEntry], int, str] | None:
        if self._redis is None:
            return None
        try:
            zkey = self._zset_key(scope)
            if not await self._redis.exists(zkey):
                return None
            total = int(await self._redis.zcard(zkey))
            # ZREVRANGE high->low CR, with scores; decode bytes defensively.
            raw = await self._redis.zrevrange(zkey, offset, offset + limit - 1, withscores=True)
        except Exception:
            # Falha de Redis vira cache miss (fallback Postgres), nunca 500.
            _log.warning("leaderboard.redis.read_failed", exc_info=True)
            return None
        rows = [
            LeaderboardEntry(
                rank=offset + i + 1,
                player_id=_decode(member),
                cr=round(score),
            )
            for i, (member, score) in enumerate(raw)
        ]
        updated_at = await self._read_meta(scope)
        return rows, total, updated_at

    async def _page_from_db(
        self,
        session: AsyncSession,
        season_id: str,
        fmt: str,
        offset: int,
        limit: int,
    ) -> tuple[list[LeaderboardEntry], int]:
        # NOTE: format scoping is logical here; player_seasons rows are per
        # season. When formats become distinct season rows this WHERE gains a
        # format predicate. Order by the (season_id, cr DESC) index.
        result = await session.execute(
            select(m.PlayerSeason.player_id, m.PlayerSeason.cr)
            .where(m.PlayerSeason.season_id == season_id)
            .order_by(m.PlayerSeason.cr.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = [
            LeaderboardEntry(rank=offset + i + 1, player_id=str(pid), cr=round(cr))
            for i, (pid, cr) in enumerate(result.all())
        ]
        total_q = await session.execute(
            select(func.count())
            .select_from(m.PlayerSeason)
            .where(m.PlayerSeason.season_id == season_id)
        )
        return rows, int(total_q.scalar_one())

    async def _warm_from_db(
        self, session: AsyncSession, scope: str, season_id: str, fmt: str
    ) -> None:
        """Load the Top-N into the ZSET so the next read is served from Redis."""
        if self._redis is None:
            return
        top = await session.execute(
            select(m.PlayerSeason.player_id, m.PlayerSeason.cr)
            .where(m.PlayerSeason.season_id == season_id)
            .order_by(m.PlayerSeason.cr.desc())
            .limit(1000)
        )
        mapping = {str(pid): float(cr) for pid, cr in top.all()}
        if not mapping:
            return
        zkey = self._zset_key(scope)
        try:
            await self._redis.delete(zkey)
            await self._redis.zadd(zkey, mapping)
            await self._redis.expire(zkey, self._ttl_s)
            await self._touch_meta(scope)
        except Exception:
            # Warm-up é best-effort: a página desta requisição já veio do DB.
            _log.warning("leaderboard.redis.warm_failed", exc_info=True)

    async def _touch_meta(self, scope: str) -> None:
        if self._redis is None:
            return
        meta = {"updatedAt": datetime.now(UTC).isoformat()}
        await self._redis.set(self._meta_key(scope), json.dumps(meta), ex=self._ttl_s)

    async def _read_meta(self, scope: str) -> str:
        if self._redis is None:
            return datetime.now(UTC).isoformat()
        try:
            raw = await self._redis.get(self._meta_key(scope))
        except Exception:
            _log.warning("leaderboard.redis.meta_failed", exc_info=True)
            return datetime.now(UTC).isoformat()
        if not raw:
            return datetime.now(UTC).isoformat()
        try:
            return json.loads(_decode(raw)).get("updatedAt") or datetime.now(UTC).isoformat()
        except (ValueError, TypeError):
            return datetime.now(UTC).isoformat()


def _decode(value: object) -> str:
    return value.decode() if isinstance(value, bytes | bytearray) else str(value)


__all__ = ["LeaderboardService", "LeaderboardEntry", "LeaderboardPage"]
