"""Data Dragon (``ddragon``) package — Riot's official static CDN integration.

Resolves champion display names and champion/summoner icon URLs from Riot's
ToS-compliant Data Dragon CDN, so the frontend can show real champion icons and
PT-BR names instead of gradient-placeholder avatars.

Public surface:

- :class:`~arena.ddragon.service.DDragonService` — the async accessor.
- :func:`~arena.ddragon.service.get_ddragon` — process-wide sync-cached singleton
  (use this from request handlers; one shared in-process cache).
- :func:`~arena.ddragon.service.warm_ddragon` — preload version + champion map.
- :func:`~arena.ddragon.service.refresh_ddragon` — scheduler refresh hook
  (accepts an optional arq ``ctx``).

Caching is two-tier — in-process (always) over Redis (optional, 12h TTL). Redis
is degrade-gracefully: with no ``REDIS_URL`` the service runs in-process-only.
"""

from __future__ import annotations

from .cache import DEFAULT_TTL_SECONDS, DDragonCache
from .service import (
    DDRAGON_BASE,
    KEY_CHAMPIONS,
    KEY_VERSION,
    LOCALE,
    VERSIONS_URL,
    ChampionMap,
    ChampionMeta,
    DDragonService,
    get_ddragon,
    refresh_ddragon,
    reset_ddragon,
    warm_ddragon,
)

__all__ = [
    "DDragonService",
    "DDragonCache",
    "ChampionMap",
    "ChampionMeta",
    "get_ddragon",
    "reset_ddragon",
    "warm_ddragon",
    "refresh_ddragon",
    "DDRAGON_BASE",
    "VERSIONS_URL",
    "LOCALE",
    "KEY_VERSION",
    "KEY_CHAMPIONS",
    "DEFAULT_TTL_SECONDS",
]
