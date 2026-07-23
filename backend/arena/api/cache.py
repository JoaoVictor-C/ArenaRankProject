"""Full-response Redis cache for the public read API (T0.3, arquitetura §3.3).

Pure-ASGI middleware that short-circuits hot GET endpoints from Redis before
FastAPI resolves any dependency — a hit never opens a DB session. Keys are
``arena:api:cache:{path}?{query ordenada}`` (query canonicalized by sorting,
so param order doesn't fragment the cache) and values are the raw JSON body,
written with ``SETEX`` using the per-route TTLs from :class:`Settings`.

Hard rules:

* **allowlist only** — routes not matched by a rule are never cached;
* ``/admin/*`` (and any non-GET) always bypasses;
* only ``200`` responses are stored (errors are never cached);
* Redis down/broken → clean bypass (the request flows to the router as if the
  middleware didn't exist). Mirrors the ``LeaderboardService`` degrade posture.

The middleware is registered innermost (before CORS/logging) so cache hits
still receive CORS headers and request-id logging from the outer layers. An
``x-cache: HIT|MISS`` header is emitted for observability and for the
Cloudflare edge work in T1.x (debugging which layer answered).

T1.1 — the same route→TTL map also drives ``Cache-Control`` so the Cloudflare
edge (and any shared cache) can serve the hot pages without touching the box:

* allowlisted GET + 200 → ``public, s-maxage={ttl}, stale-while-revalidate=300,
  stale-if-error=86400`` (emitted even when Redis is down — the edge layer
  must not depend on the Redis layer);
* everything else under the API prefix (``/admin/*``, non-GET, unlisted
  routes, non-200) → ``no-store`` (a shared cache must never hold them).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from urllib.parse import parse_qsl, urlencode

from arena.core.config import Settings, settings
from arena.core.logging import get_logger

_log = get_logger("arena.api.cache")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_KEY_PREFIX = "arena:api:cache:"

#: Sobrevida de edge (Cloudflare) além do TTL: serve stale enquanto revalida /
#: serve stale por até 24h se a origem cair (arquitetura §3.2).
_STALE_WHILE_REVALIDATE_S = 300
_STALE_IF_ERROR_S = 86_400
_NO_STORE = b"no-store"


def _cache_control_for(ttl: int) -> bytes:
    return (
        f"public, s-maxage={ttl}, "
        f"stale-while-revalidate={_STALE_WHILE_REVALIDATE_S}, "
        f"stale-if-error={_STALE_IF_ERROR_S}"
    ).encode()

#: (prefixo do path relativo a /api/v1, nome do campo de TTL em Settings).
#: Ordem importa: primeiro match vence (/players/search antes de /player/).
_RULE_FIELDS: tuple[tuple[str, str], ...] = (
    ("/players/search", "cache_ttl_players_search_s"),
    ("/leaderboard", "cache_ttl_leaderboard_s"),
    ("/champions", "cache_ttl_champions_s"),
    ("/meta/", "cache_ttl_meta_s"),
    ("/match/", "cache_ttl_match_s"),
    ("/player/", "cache_ttl_player_s"),
    ("/tournaments", "cache_ttl_tournaments_s"),
)


def build_rules(cfg: Settings) -> tuple[tuple[str, int], ...]:
    """Materialize the (prefix, ttl_s) allowlist from env-driven settings."""
    return tuple((prefix, int(getattr(cfg, field))) for prefix, field in _RULE_FIELDS)


def cache_key(rel_path: str, query_string: bytes) -> str:
    """Canonical cache key: path + query params sorted by (name, value)."""
    pairs = sorted(parse_qsl(query_string.decode("latin-1"), keep_blank_values=True))
    return f"{_KEY_PREFIX}{rel_path}?{urlencode(pairs)}"


class ResponseCacheMiddleware:
    """ASGI middleware: serve/store whole JSON responses for allowlisted GETs."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        prefix: str = "/api/v1",
        rules: tuple[tuple[str, int], ...] | None = None,
        redis_provider: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        self.app = app
        self.prefix = prefix
        self.rules = rules if rules is not None else build_rules(settings)
        self._redis_provider = redis_provider

    async def _redis(self) -> Any:
        if self._redis_provider is not None:
            return await self._redis_provider()
        from arena.api.deps import get_redis

        return await get_redis()

    def _ttl_for(self, rel_path: str) -> int | None:
        if rel_path.startswith("/admin"):
            return None
        for rule_prefix, ttl in self.rules:
            if rel_path.startswith(rule_prefix):
                return ttl
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if not path.startswith(self.prefix):
            # Fora da API versionada (/healthz, /docs): não interferir.
            await self.app(scope, receive, send)
            return
        rel_path = path[len(self.prefix) :]
        ttl = self._ttl_for(rel_path) if scope.get("method") == "GET" else None

        if ttl is None or ttl <= 0:
            # /admin, não-GET, rota fora da allowlist: cache compartilhada
            # proibida (no-store), sem camada Redis.
            await self._passthrough(scope, receive, send, ttl=None)
            return

        redis = None
        try:
            redis = await self._redis()
        except Exception:  # pragma: no cover - provider must not break requests
            redis = None
        if redis is None:
            # Sem Redis a edge continua funcionando: só Cache-Control.
            await self._passthrough(scope, receive, send, ttl=ttl)
            return

        key = cache_key(rel_path, scope.get("query_string", b""))
        try:
            cached = await redis.get(key)
        except Exception:
            _log.warning("api.cache.read_failed", key=key, exc_info=True)
            cached = None

        if cached is not None:
            body = cached if isinstance(cached, bytes | bytearray) else str(cached).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        (b"cache-control", _cache_control_for(ttl)),
                        (b"x-cache", b"HIT"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": bytes(body)})
            return

        # Miss: run the route capturing the response; store only 200s.
        chunks: list[bytes] = []
        status_code = await self._passthrough(
            scope, receive, send, ttl=ttl, capture_into=chunks, x_cache=b"MISS"
        )

        if status_code == 200 and chunks:
            try:
                await redis.setex(key, ttl, b"".join(chunks))
            except Exception:
                _log.warning("api.cache.write_failed", key=key, exc_info=True)

    async def _passthrough(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        ttl: int | None,
        capture_into: list[bytes] | None = None,
        x_cache: bytes | None = None,
    ) -> int:
        """Run the app injecting cache headers; optionally capture the body.

        ``ttl`` set + status 200 → ``Cache-Control: public, s-maxage=...``;
        everything else → ``no-store``. Returns the response status code.
        """
        status_code = 0

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers") or [])
                cc = _cache_control_for(ttl) if (ttl and status_code == 200) else _NO_STORE
                headers.append((b"cache-control", cc))
                if x_cache is not None:
                    headers.append((b"x-cache", x_cache))
                message = {**message, "headers": headers}
            elif message["type"] == "http.response.body":
                if capture_into is not None and status_code == 200:
                    capture_into.append(bytes(message.get("body") or b""))
            await send(message)

        await self.app(scope, receive, send_wrapper)
        return status_code


__all__ = ["ResponseCacheMiddleware", "build_rules", "cache_key"]
