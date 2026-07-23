"""ResponseCacheMiddleware — T0.3 do workaround_readpath.

Aceite: a 2ª requisição idêntica é servida do Redis sem executar a rota
(logo sem abrir sessão de DB — o contador da rota não anda), com o TTL
configurado por rota via SETEX; /admin, POSTs e erros nunca são cacheados;
Redis ausente/quebrado = bypass limpo.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from arena.api.cache import ResponseCacheMiddleware, build_rules, cache_key
from arena.core.config import Settings


class FakeRedis:
    """GET/SETEX mínimos; grava o TTL usado por chave para o aceite."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: bytes) -> None:
        self.store[key] = value
        self.ttls[key] = ttl


class BrokenRedis(FakeRedis):
    async def get(self, key: str) -> bytes | None:
        raise ConnectionError("redis caiu")

    async def setex(self, key: str, ttl: int, value: bytes) -> None:
        raise ConnectionError("redis caiu")


def make_app(redis: FakeRedis | None) -> tuple[TestClient, dict[str, int]]:
    hits = {"leaderboard": 0, "match": 0, "admin": 0, "post": 0, "erro": 0}
    router = APIRouter()

    @router.get("/leaderboard")
    async def leaderboard(page: int = 1, size: int = 50) -> dict[str, Any]:
        hits["leaderboard"] += 1
        return {"rows": [], "page": page, "size": size}

    @router.get("/match/{match_id}")
    async def match(match_id: str) -> dict[str, str]:
        hits["match"] += 1
        return {"id": match_id}

    @router.get("/admin/overview")
    async def admin() -> dict[str, int]:
        hits["admin"] += 1
        return {"ok": 1}

    @router.post("/leaderboard")
    async def post_lb() -> dict[str, int]:
        hits["post"] += 1
        return {"ok": 1}

    @router.get("/player/erro")
    async def erro() -> None:
        hits["erro"] += 1
        raise HTTPException(status_code=404, detail="Jogador não encontrado.")

    @router.get("/interno/fora-da-allowlist")
    async def interno() -> dict[str, int]:
        return {"ok": 1}

    app = FastAPI()

    async def provider() -> FakeRedis | None:
        return redis

    app.add_middleware(
        ResponseCacheMiddleware, rules=build_rules(Settings()), redis_provider=provider
    )
    app.include_router(router, prefix="/api/v1")
    return TestClient(app, raise_server_exceptions=False), hits


def test_second_identical_request_never_runs_the_route() -> None:
    redis = FakeRedis()
    client, hits = make_app(redis)

    r1 = client.get("/api/v1/leaderboard?page=1&size=50")
    assert r1.status_code == 200
    assert r1.headers["x-cache"] == "MISS"
    r2 = client.get("/api/v1/leaderboard?page=1&size=50")
    assert r2.status_code == 200
    assert r2.headers["x-cache"] == "HIT"
    assert r2.json() == r1.json()
    assert hits["leaderboard"] == 1  # rota (e portanto get_db) não re-executou


def test_query_order_is_canonicalized() -> None:
    client, hits = make_app(FakeRedis())
    client.get("/api/v1/leaderboard?page=2&size=10")
    r = client.get("/api/v1/leaderboard?size=10&page=2")
    assert r.headers["x-cache"] == "HIT"
    assert hits["leaderboard"] == 1
    assert cache_key("/leaderboard", b"page=2&size=10") == cache_key(
        "/leaderboard", b"size=10&page=2"
    )


def test_ttl_per_route_is_the_configured_one() -> None:
    redis = FakeRedis()
    client, _hits = make_app(redis)
    cfg = Settings()

    client.get("/api/v1/leaderboard")
    client.get("/api/v1/match/BR1_123")
    ttls = set(redis.ttls.values())
    assert cfg.cache_ttl_leaderboard_s in ttls  # 60 por default
    assert cfg.cache_ttl_match_s in ttls  # 3600 por default


def test_admin_post_and_errors_are_never_cached() -> None:
    redis = FakeRedis()
    client, hits = make_app(redis)

    client.get("/api/v1/admin/overview")
    client.get("/api/v1/admin/overview")
    assert hits["admin"] == 2  # /admin sempre passa reto

    client.post("/api/v1/leaderboard")
    client.post("/api/v1/leaderboard")
    assert hits["post"] == 2  # não-GET sempre passa reto

    e1 = client.get("/api/v1/player/erro")
    assert e1.status_code == 404
    client.get("/api/v1/player/erro")
    assert hits["erro"] == 2  # erro nunca é cacheado
    assert not any("erro" in k for k in redis.store)


def test_no_redis_is_a_clean_bypass() -> None:
    client, hits = make_app(None)
    assert client.get("/api/v1/leaderboard").status_code == 200
    assert client.get("/api/v1/leaderboard").status_code == 200
    assert hits["leaderboard"] == 2


def test_broken_redis_is_a_clean_bypass() -> None:
    client, hits = make_app(BrokenRedis())
    assert client.get("/api/v1/leaderboard").status_code == 200
    assert client.get("/api/v1/leaderboard").status_code == 200
    assert hits["leaderboard"] == 2


def test_rules_come_from_settings() -> None:
    cfg = Settings(cache_ttl_leaderboard_s=7)
    rules = dict(build_rules(cfg))
    assert rules["/leaderboard"] == 7
    assert rules["/players/search"] == cfg.cache_ttl_players_search_s


# ---------------------------------------------------------------------------
# T1.1 — Cache-Control por rota (s-maxage p/ edge Cloudflare) + no-store
# ---------------------------------------------------------------------------


def test_public_get_emits_smaxage_with_stale_directives() -> None:
    client, _hits = make_app(FakeRedis())
    cfg = Settings()

    lb = client.get("/api/v1/leaderboard")
    assert lb.headers["cache-control"] == (
        f"public, s-maxage={cfg.cache_ttl_leaderboard_s}, "
        "stale-while-revalidate=300, stale-if-error=86400"
    )
    match = client.get("/api/v1/match/BR1_123")
    assert f"s-maxage={cfg.cache_ttl_match_s}" in match.headers["cache-control"]


def test_cache_control_emitted_even_without_redis() -> None:
    # A camada de edge não pode depender da camada Redis.
    client, _hits = make_app(None)
    r = client.get("/api/v1/leaderboard")
    assert "s-maxage=" in r.headers["cache-control"]
    assert "x-cache" not in r.headers  # sem Redis não há HIT/MISS a reportar


def test_hit_keeps_cache_control() -> None:
    client, _hits = make_app(FakeRedis())
    client.get("/api/v1/leaderboard")
    hit = client.get("/api/v1/leaderboard")
    assert hit.headers["x-cache"] == "HIT"
    assert "s-maxage=" in hit.headers["cache-control"]


def test_admin_post_error_and_unlisted_are_no_store() -> None:
    client, _hits = make_app(FakeRedis())
    assert client.get("/api/v1/admin/overview").headers["cache-control"] == "no-store"
    assert client.post("/api/v1/leaderboard").headers["cache-control"] == "no-store"
    assert client.get("/api/v1/player/erro").headers["cache-control"] == "no-store"
    assert (
        client.get("/api/v1/interno/fora-da-allowlist").headers["cache-control"] == "no-store"
    )


def test_cors_is_wildcard_without_credentials() -> None:
    # Cloudflare ignora Vary: ACAO tem que ser fixo "*" e sem credenciais,
    # senão a edge serve o ACAO de uma origem para outra (T1.1/T1.2).
    from arena.api.app import create_app

    client = TestClient(create_app(), raise_server_exceptions=False)
    r = client.get("/healthz", headers={"Origin": "https://arenarank.lol"})
    assert r.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in r.headers