"""Data Dragon service — champion names + champion/summoner icon URLs.

Data Dragon (``ddragon``) is Riot's **official** static CDN (the same static
assets the LoL client ships). It is ToS-compliant, free, key-less, and the
canonical source for champion display names and asset URLs — exactly what the
frontend needs to replace gradient-placeholder avatars with real icons.

What this provides
------------------
* :meth:`DDragonService.get_version` — latest patch version (index 0 of
  ``versions.json``), cached in Redis (``ddragon:version``, 12h) + in-process.
* :meth:`DDragonService.champion_meta` — ``{"key", "name"}`` for a numeric
  ``championId`` (None-safe: unknown ids fall back to ``{"key": "", "name":
  str(id)}``).
* :meth:`DDragonService.champion_icon_url` / :meth:`profile_icon_url` —
  fully-qualified ddragon image URLs.
* :meth:`warm` / :meth:`refresh` — async preload / force-refresh of the version
  + champion map (call once per process; re-call from a scheduler hook).

Caching & resilience
--------------------
A two-tier :class:`~arena.ddragon.cache.DDragonCache` sits in front of every
fetch: in-process (always) over Redis (optional). Redis is *optional* — if
``REDIS_URL`` is absent or the connection fails, the service degrades to the
in-process cache and live HTTP. Champion-name/icon resolution after :meth:`warm`
never touches the network on the hot path.

The locale is ``pt_BR`` so champion display names match the PT-BR UI.

Boundary: only champion-level public metadata is exposed here — no augment/item
winrate, no mu/sigma. All user-facing fallbacks are plain strings.
"""

from __future__ import annotations

import asyncio
import json
from functools import lru_cache
from importlib import resources
from typing import Any

import httpx

from ..core.logging import get_logger
from .cache import DEFAULT_TTL_SECONDS, DDragonCache

_log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DDRAGON_BASE = "https://ddragon.leagueoflegends.com"
VERSIONS_URL = f"{DDRAGON_BASE}/api/versions.json"

# Locale for champion display names — matches the PT-BR frontend contract.
LOCALE = "pt_BR"

# Redis cache keys (also used as in-process keys).
KEY_VERSION = "ddragon:version"
KEY_CHAMPIONS = "ddragon:champions"

# Conservative fallback if ``versions.json`` is unreachable before the first
# successful fetch. Only used to keep URL construction non-fatal; refreshed asap.
# Kept in step with the bundled ``champions_static.json`` patch so offline icon
# URLs point at assets that actually exist.
FALLBACK_VERSION = "16.14.1"

# Bundled offline champion catalog (id→{"key","name"}), generated from ddragon
# pt_BR. The final resolution fallback when the warmed cache is cold AND ddragon
# is unreachable — keeps names/icons real instead of degrading to numeric ids.
STATIC_CATALOG_RESOURCE = "champions_static.json"

# Bundled offline id→PT-BR class map (Mago/Tanque/Lutador/Suporte/Atirador/
# Assassino), generated from ddragon championFull ``tags[0]``. Arena has no fixed
# roles, so this is a champion-class taxonomy for the /winrate class chips — not
# a lane/position. Regenerate with the champion catalog when the patch bumps.
STATIC_CLASSES_RESOURCE = "champion_classes.json"

_HTTP_TIMEOUT = 10.0


ChampionMap = dict[int, dict[str, str]]
ChampionMeta = dict[str, str]


def _empty_meta(champion_id: int) -> ChampionMeta:
    """None-safe fallback metadata for an unknown champion id."""
    return {"key": "", "name": str(champion_id)}


@lru_cache(maxsize=1)
def _static_champion_map() -> ChampionMap:
    """Bundled offline id→{"key","name"} catalog (see ``STATIC_CATALOG_RESOURCE``).

    Loaded once from package data. The last-ditch fallback so a cold cache with
    no network still yields real champion names/icons rather than numeric ids.
    Returns ``{}`` if the resource is missing/corrupt (still None-safe upstream).
    """
    try:
        raw = (
            resources.files("arena.ddragon")
            .joinpath(STATIC_CATALOG_RESOURCE)
            .read_text(encoding="utf-8")
        )
        data = json.loads(raw)
    except (OSError, ValueError):  # pragma: no cover - packaging/corruption guard
        return {}
    if not isinstance(data, dict):
        return {}
    result: ChampionMap = {}
    for key, value in data.items():
        try:
            champ_id = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            result[champ_id] = {
                "key": str(value.get("key", "")),
                "name": str(value.get("name", "")),
            }
    return result


@lru_cache(maxsize=1)
def _static_class_map() -> dict[int, str]:
    """Bundled offline id→PT-BR class map (see ``STATIC_CLASSES_RESOURCE``).

    Loaded once from package data. Returns ``{}`` if the resource is missing or
    corrupt — callers degrade to an empty class (None-safe: the UI just omits the
    chip filter for that champion).
    """
    try:
        raw = (
            resources.files("arena.ddragon")
            .joinpath(STATIC_CLASSES_RESOURCE)
            .read_text(encoding="utf-8")
        )
        data = json.loads(raw)
    except (OSError, ValueError):  # pragma: no cover - packaging/corruption guard
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[int, str] = {}
    for key, value in data.items():
        try:
            champ_id = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, str):
            result[champ_id] = value
    return result


class DDragonService:
    """Async Data Dragon accessor with a sync-cached singleton (see module funcs).

    Construct via :func:`get_ddragon` (process-wide singleton) rather than
    directly, so the in-process cache is shared across request handlers.
    """

    def __init__(
        self,
        *,
        redis: Any | None = None,
        http: httpx.AsyncClient | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        locale: str = LOCALE,
    ) -> None:
        self._cache = DDragonCache(redis=redis, ttl_seconds=ttl_seconds)
        self._http = http
        self._owns_http = http is None
        self._locale = locale
        # Guards a single concurrent warm/refresh; many request handlers may race
        # to be first — only one should hit ddragon.
        self._lock = asyncio.Lock()

    # -- HTTP plumbing ------------------------------------------------------

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
        return self._http

    async def aclose(self) -> None:
        """Close the owned HTTP client (no-op if one was injected)."""
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _fetch_json(self, url: str) -> Any | None:
        """GET + parse JSON; return ``None`` on any HTTP/parse error (logged)."""
        try:
            client = await self._client()
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            _log.warning("ddragon.fetch_failed", url=url, error=str(exc))
            return None

    # -- version ------------------------------------------------------------

    async def get_version(self, *, force: bool = False) -> str:
        """Return the latest ddragon version (``versions.json`` index 0).

        Cache-first (in-process → Redis); on a miss fetch and write-through.
        Falls back to the last-known/seed version if ddragon is unreachable so
        URL construction never fails.
        """
        if not force:
            cached = await self._cache.get(KEY_VERSION)
            if isinstance(cached, str) and cached:
                return cached

        data = await self._fetch_json(VERSIONS_URL)
        if isinstance(data, list) and data and isinstance(data[0], str):
            version = data[0]
            await self._cache.set(KEY_VERSION, version)
            return version

        # Fetch failed: reuse any stale in-process value, else the seed.
        stale = self._cache.get_local(KEY_VERSION)
        if isinstance(stale, str) and stale:
            return stale
        return FALLBACK_VERSION

    # -- champion map -------------------------------------------------------

    async def _get_champion_map(self, *, force: bool = False) -> ChampionMap:
        """Return ``{int championId: {"key", "name"}}`` (cache-first)."""
        if not force:
            cached = await self._cache.get(KEY_CHAMPIONS)
            if isinstance(cached, dict) and cached:
                return self._coerce_map(cached)

        version = await self.get_version(force=force)
        url = f"{DDRAGON_BASE}/cdn/{version}/data/{self._locale}/champion.json"
        data = await self._fetch_json(url)
        champ_map = self._build_map(data)
        if champ_map:
            # Store with string keys (JSON requirement); coerce back on read.
            await self._cache.set(KEY_CHAMPIONS, {str(k): v for k, v in champ_map.items()})
            return champ_map

        # Fetch failed: reuse stale in-process map if present, else the bundled
        # offline catalog (never cached, so a later call re-tries the network).
        stale = self._cache.get_local(KEY_CHAMPIONS)
        if isinstance(stale, dict) and stale:
            return self._coerce_map(stale)
        return dict(_static_champion_map())

    @staticmethod
    def _build_map(data: Any) -> ChampionMap:
        """Build the id→meta map from a raw ``champion.json`` payload.

        ``entry["key"]`` is the numeric championId (as a string), ``entry["id"]``
        is the asset/icon key (e.g. ``"Aatrox"``), ``entry["name"]`` is the
        localized display name.
        """
        if not isinstance(data, dict):
            return {}
        entries = data.get("data")
        if not isinstance(entries, dict):
            return {}
        result: ChampionMap = {}
        for entry in entries.values():
            if not isinstance(entry, dict):
                continue
            raw_key = entry.get("key")
            if raw_key is None:
                continue
            try:
                champ_id = int(raw_key)
            except (TypeError, ValueError):
                continue
            result[champ_id] = {
                "key": str(entry.get("id", "")),
                "name": str(entry.get("name", "")),
            }
        return result

    @staticmethod
    def _coerce_map(raw: dict[Any, Any]) -> ChampionMap:
        """Coerce a JSON-decoded map (string keys) back to ``{int: meta}``."""
        result: ChampionMap = {}
        for key, value in raw.items():
            try:
                champ_id = int(key)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                result[champ_id] = {
                    "key": str(value.get("key", "")),
                    "name": str(value.get("name", "")),
                }
        return result

    # -- public resolution --------------------------------------------------

    async def champion_meta(self, champion_id: int | None) -> ChampionMeta:
        """Return ``{"key", "name"}`` for a numeric championId (None-safe).

        Unknown / ``None`` ids fall back to ``{"key": "", "name": str(id)}`` so
        the UI always has a stable label and never crashes on a missing champion.
        """
        if champion_id is None:
            return {"key": "", "name": ""}
        champ_map = await self._get_champion_map()
        meta = champ_map.get(int(champion_id))
        if meta is None:
            return _empty_meta(int(champion_id))
        return {"key": meta.get("key", ""), "name": meta.get("name", str(champion_id))}

    async def champion_icon_url(self, champion_id: int | None) -> str | None:
        """Fully-qualified champion-square icon URL, or ``None`` if unresolved."""
        meta = await self.champion_meta(champion_id)
        key = meta.get("key", "")
        if not key:
            return None
        version = await self.get_version()
        return f"{DDRAGON_BASE}/cdn/{version}/img/champion/{key}.png"

    async def profile_icon_url(self, icon_id: int | None) -> str | None:
        """Fully-qualified summoner profile-icon URL, or ``None`` if no id."""
        if icon_id is None:
            return None
        version = await self.get_version()
        return f"{DDRAGON_BASE}/cdn/{version}/img/profileicon/{int(icon_id)}.png"

    # -- sync resolution (warmed cache only — for sync-fast request handlers) ----
    #
    # These read straight from the in-process cache populated by :meth:`warm`
    # (called once at app startup). They NEVER touch the network or Redis, so a
    # request handler can resolve hundreds of champion names/icons synchronously
    # without an ``await`` per row. If the cache is cold (warm not yet run) they
    # degrade to the None-safe fallbacks (champion id as the name, ``None`` URLs).

    def version_sync(self) -> str:
        """Last-warmed ddragon version (in-process only); seed if never warmed."""
        cached = self._cache.get_local(KEY_VERSION)
        if isinstance(cached, str) and cached:
            return cached
        return FALLBACK_VERSION

    def _champion_map_sync(self) -> ChampionMap:
        cached = self._cache.get_local(KEY_CHAMPIONS)
        if isinstance(cached, dict) and cached:
            return self._coerce_map(cached)
        # Cache cold (warm never ran / failed): resolve from the bundled catalog
        # so names + icons stay real instead of degrading to numeric ids.
        return _static_champion_map()

    def champion_meta_sync(self, champion_id: int | None) -> ChampionMeta:
        """Sync ``{"key", "name"}`` for a championId from the warmed cache (None-safe)."""
        if champion_id is None:
            return {"key": "", "name": ""}
        meta = self._champion_map_sync().get(int(champion_id))
        if meta is None:
            return _empty_meta(int(champion_id))
        return {"key": meta.get("key", ""), "name": meta.get("name", str(champion_id))}

    def champion_name_sync(self, champion_id: int | None) -> str:
        """Sync localized champion display name from the warmed cache (None-safe)."""
        return self.champion_meta_sync(champion_id).get("name", "")

    def champion_class_sync(self, champion_id: int | None) -> str:
        """Sync PT-BR champion class (Mago/Tanque/Lutador/...) or ``""`` if unknown.

        Sourced from the bundled ``champion_classes.json`` (ddragon ``tags[0]``).
        Arena has no fixed roles, so this is a class taxonomy for the class chips,
        not a position. None-safe: an unknown id yields ``""`` (no chip filter)."""
        if champion_id is None:
            return ""
        return _static_class_map().get(int(champion_id), "")

    def champion_icon_url_sync(self, champion_id: int | None) -> str | None:
        """Sync champion-square icon URL from the warmed cache, or ``None``."""
        key = self.champion_meta_sync(champion_id).get("key", "")
        if not key:
            return None
        return f"{DDRAGON_BASE}/cdn/{self.version_sync()}/img/champion/{key}.png"

    def champion_splash_url_sync(self, champion_id: int | None) -> str | None:
        """Sync champion loading-screen splash URL (1215×717) from the warmed
        cache, or ``None``. Version-less path (ddragon serves splash/loading art
        outside the ``/cdn/{version}`` tree). Base skin (``_0``); centered on the
        subject via CSS on the client since ddragon has no pre-centered crop."""
        key = self.champion_meta_sync(champion_id).get("key", "")
        if not key:
            return None
        return f"{DDRAGON_BASE}/cdn/img/champion/splash/{key}_0.jpg"

    def profile_icon_url_sync(self, icon_id: int | None) -> str | None:
        """Sync summoner profile-icon URL from the warmed cache, or ``None``."""
        if icon_id is None:
            return None
        return f"{DDRAGON_BASE}/cdn/{self.version_sync()}/img/profileicon/{int(icon_id)}.png"

    # -- lifecycle ----------------------------------------------------------

    async def warm(self) -> dict[str, Any]:
        """Preload version + champion map once (idempotent, race-safe).

        Call at startup / first request. Concurrent callers collapse onto a
        single ddragon fetch via the internal lock.
        """
        async with self._lock:
            version = await self.get_version()
            champ_map = await self._get_champion_map()
            result = {"version": version, "champions": len(champ_map)}
        _log.info("ddragon.warm", **result)
        return result

    async def refresh(self) -> dict[str, Any]:
        """Force-refresh version + champion map from ddragon (scheduler hook).

        Bypasses the cache read so a new patch is picked up promptly; writes the
        fresh values back through both cache tiers.
        """
        async with self._lock:
            version = await self.get_version(force=True)
            champ_map = await self._get_champion_map(force=True)
            result = {"version": version, "champions": len(champ_map)}
        _log.info("ddragon.refresh", **result)
        return result


# ---------------------------------------------------------------------------
# Sync-cached singleton
# ---------------------------------------------------------------------------

_SINGLETON: DDragonService | None = None


def _build_redis() -> Any | None:
    """Build an async Redis client from settings, or ``None`` if unavailable.

    Redis is *optional*: a missing/blank ``REDIS_URL`` or an import failure means
    the service runs in-process-only. We do not connect eagerly here — the
    redis-py async client connects lazily on first command — so an unreachable
    Redis only costs a best-effort, swallowed error on the first cache touch.
    """
    try:
        from redis.asyncio import Redis

        from ..core.config import settings

        url = (settings.redis_url or "").strip()
        if not url:
            return None
        return Redis.from_url(url)
    except Exception:  # noqa: BLE001 - Redis is fully optional
        _log.info("ddragon.redis_unavailable", reason="degrading to in-process cache")
        return None


def get_ddragon() -> DDragonService:
    """Return the process-wide :class:`DDragonService` singleton (sync, cached).

    Safe to call from sync contexts (e.g. building a router dependency); the
    actual ddragon fetches happen in the async methods. The singleton shares one
    in-process cache across all request handlers, so :meth:`warm` only needs to
    run once per process.
    """
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = DDragonService(redis=_build_redis())
    return _SINGLETON


def reset_ddragon() -> None:
    """Drop the singleton (test / reconfiguration aid)."""
    global _SINGLETON
    _SINGLETON = None


async def warm_ddragon() -> dict[str, Any]:
    """Convenience: warm the singleton (preload map once)."""
    return await get_ddragon().warm()


async def refresh_ddragon(_ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Scheduler-friendly refresh hook.

    Accepts an optional arq-style ``ctx`` (ignored) so it can be dropped straight
    into ``arena.workers.scheduler`` as a cron coroutine without an adapter.
    """
    return await get_ddragon().refresh()


__all__ = [
    "DDragonService",
    "ChampionMap",
    "ChampionMeta",
    "DDRAGON_BASE",
    "VERSIONS_URL",
    "LOCALE",
    "KEY_VERSION",
    "KEY_CHAMPIONS",
    "DEFAULT_TTL_SECONDS",
    "get_ddragon",
    "reset_ddragon",
    "warm_ddragon",
    "refresh_ddragon",
]
