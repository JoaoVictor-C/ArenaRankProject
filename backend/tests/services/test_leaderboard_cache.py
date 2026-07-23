"""LeaderboardService read-through — T0.2 do workaround_readpath.

Aceite: com Redis presente, a 1ª página vem do Postgres e aquece o ZSET
(``arena:lb:z:*``); a 2ª chamada idêntica é servida do ZSET **sem** tocar o
banco. Redis quebrando no meio degrada para o caminho Postgres (nunca 500).
O Redis é um stub in-memory mínimo (mesma superfície usada pelo service);
a sessão é um fake que serve as 3 queries do fallback e explode se for
consultada quando o cache deveria responder.
"""

from __future__ import annotations

from typing import Any

import pytest

from arena.services.leaderboard_service import LeaderboardService

SEASON = "11111111-1111-1111-1111-111111111111"


class _Rows:
    """Resultado fake de ``session.execute`` (superfície .all()/.scalar_one())."""

    def __init__(self, rows: list[Any] | None = None, scalar: Any = None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def all(self) -> list[Any]:
        return self._rows

    def scalar_one(self) -> Any:
        return self._scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar


class FakeSession:
    """Serve, em ordem, as queries do caminho Postgres do ``get_page``:
    página → count → warm top-1000. Conta execuções para o aceite."""

    def __init__(self, players: list[tuple[str, float]]) -> None:
        self._players = players
        self.executed = 0

    async def execute(self, _query: Any) -> _Rows:
        self.executed += 1
        if self.executed == 1:  # página
            return _Rows(rows=list(self._players))
        if self.executed == 2:  # count
            return _Rows(scalar=len(self._players))
        return _Rows(rows=list(self._players))  # warm top-N


class ExplodingSession:
    """Qualquer query = falha do teste: o cache deveria ter respondido."""

    async def execute(self, _query: Any) -> _Rows:
        raise AssertionError("2ª chamada tocou o Postgres — ZSET não foi usado")


class FakeRedis:
    """ZSET/GET/SET mínimos, ordenação por score como o Redis real."""

    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, float]] = {}
        self.kv: dict[str, str] = {}

    async def exists(self, key: str) -> int:
        return 1 if key in self.zsets or key in self.kv else 0

    async def zcard(self, key: str) -> int:
        return len(self.zsets.get(key, {}))

    async def zadd(self, key: str, mapping: dict[str, float]) -> None:
        self.zsets.setdefault(key, {}).update(mapping)

    async def zrevrange(
        self, key: str, start: int, stop: int, withscores: bool = False
    ) -> list[tuple[str, float]]:
        ordered = sorted(self.zsets.get(key, {}).items(), key=lambda kv: -kv[1])
        return ordered[start : stop + 1]

    async def zrevrank(self, key: str, member: str) -> int | None:
        ordered = sorted(self.zsets.get(key, {}).items(), key=lambda kv: -kv[1])
        for i, (m, _s) in enumerate(ordered):
            if m == member:
                return i
        return None

    async def expire(self, key: str, _ttl: int) -> None:
        pass

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.zsets.pop(key, None)
            self.kv.pop(key, None)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.kv[key] = value

    async def get(self, key: str) -> str | None:
        return self.kv.get(key)


class BrokenRedis(FakeRedis):
    """Conexão que morre em qualquer comando (pós-healthcheck)."""

    async def exists(self, key: str) -> int:
        raise ConnectionError("redis caiu")


PLAYERS = [("p-alta", 900.0), ("p-media", 700.0), ("p-baixa", 500.0)]


@pytest.mark.asyncio
async def test_second_read_is_served_from_zset_without_db() -> None:
    redis = FakeRedis()
    service = LeaderboardService(redis=redis)  # type: ignore[arg-type]

    db = FakeSession(PLAYERS)
    first = await service.get_page(db, season_id=SEASON, fmt="3v3", offset=0, limit=10)  # type: ignore[arg-type]
    assert [r.player_id for r in first.rows] == ["p-alta", "p-media", "p-baixa"]
    assert db.executed == 3  # página + count + warm
    assert any(k.startswith("arena:lb:z:") for k in redis.zsets)  # ZSET aquecido

    second = await service.get_page(
        ExplodingSession(),  # type: ignore[arg-type]
        season_id=SEASON,
        fmt="3v3",
        offset=0,
        limit=10,
    )
    assert [r.player_id for r in second.rows] == ["p-alta", "p-media", "p-baixa"]
    assert [r.cr for r in second.rows] == [900, 700, 500]
    assert second.total == 3
    assert [r.rank for r in second.rows] == [1, 2, 3]


@pytest.mark.asyncio
async def test_redis_none_falls_back_to_postgres() -> None:
    service = LeaderboardService(redis=None)
    db = FakeSession(PLAYERS)
    page = await service.get_page(db, season_id=SEASON, fmt="3v3", offset=0, limit=10)  # type: ignore[arg-type]
    assert page.total == 3
    assert db.executed == 2  # página + count (sem warm: não há Redis)


@pytest.mark.asyncio
async def test_redis_dying_mid_request_degrades_to_postgres() -> None:
    service = LeaderboardService(redis=BrokenRedis())  # type: ignore[arg-type]
    db = FakeSession(PLAYERS)
    page = await service.get_page(db, season_id=SEASON, fmt="3v3", offset=0, limit=10)  # type: ignore[arg-type]
    assert page.total == 3  # degradou, não explodiu


@pytest.mark.asyncio
async def test_player_rank_uses_warm_zset() -> None:
    redis = FakeRedis()
    service = LeaderboardService(redis=redis)  # type: ignore[arg-type]
    await service.get_page(FakeSession(PLAYERS), season_id=SEASON, fmt="3v3")  # type: ignore[arg-type]

    rank = await service.get_player_rank(
        ExplodingSession(),  # type: ignore[arg-type]
        season_id=SEASON,
        fmt="3v3",
        player_id="p-media",
    )
    assert rank == 2
