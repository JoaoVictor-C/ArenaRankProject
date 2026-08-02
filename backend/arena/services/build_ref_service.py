"""CDragon display resolution for augments/items — name, icon, rarity, description.

Riot's match-v5 payload only ever gives us NUMERIC augment/item ids
(``playerAugment1..6`` / ``item0..6``, captured in ``arena/riot/arena.py`` and
rolled up into ``champion_build_stats`` by ``StatsService``) — never a name,
icon, or rarity. This module is the one remaining reason to talk to
CommunityDragon for builds: turning those ids into something a person can
read. The STATS themselves (games/top1/top4/pick_rate/tier) are OUR OWN data
now — see ``stats_service.py``'s ``champion_build_picks``/``top_build_picks``
and ``arena/api/routers/champions.py``, which join the two together.

(Until this session, this module ALSO owned the stats: a third-party
aggregate, ``champion_build_ref``, snapshotted by a script that has since been
removed along with the table — migration ``0020_drop_champion_build_ref``.
That was always meant to be provisional; native augment/item capture landed,
so it's gone.)

Display names and icons resolve via CommunityDragon (PT-BR locale):

- items:    ``plugins/rcp-be-lol-game-data/global/pt_br/v1/items.json``
  (includes the Arena ``22xxxxx`` item variants ddragon lacks; ``categories``
  containing ``"Boots"`` drives the itens/botas split).
- augments: ``cdragon/arena/pt_br.json`` (``rarity``: 0=silver 1=gold
  2=prismatic, 4=unique).

Both are cached 12h through the same two-tier :class:`DDragonCache` pattern
the ddragon service uses (in-process always, Redis best-effort).

Entries whose id no longer maps to a live CDragon name (augments/items
rotated out of the current patch) are DROPPED wherever they're joined against
our own stats — a bare numeric id would read as broken data.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

import httpx

from arena.core.logging import get_logger
from arena.ddragon.cache import DEFAULT_TTL_SECONDS, DDragonCache

# Redis builder shared with the ddragon singleton (same optional-Redis policy).
from arena.ddragon.service import _build_redis

_log = get_logger("arena.services.build_ref")

CDRAGON_BASE = "https://raw.communitydragon.org/latest"
CDRAGON_ITEMS_URL = f"{CDRAGON_BASE}/plugins/rcp-be-lol-game-data/global/pt_br/v1/items.json"
CDRAGON_AUGMENTS_URL = f"{CDRAGON_BASE}/cdragon/arena/pt_br.json"

KEY_ITEMS = "cdragon:items:pt_br"
KEY_AUGMENTS = "cdragon:augments:pt_br"
KEY_AUGMENT_CATALOG = "cdragon:augment_catalog:pt_br"

#: READ floor for a (champion, pick) cell in ``champion_build_stats`` — below
#: this, the sample is too thin to show with a confident-looking tier. Must
#: stay ABOVE ``settings.champion_build_min_games`` (the WRITE floor) or the
#: read path would silently lose cells it's entitled to show.
BUILD_MIN_GAMES = 50

#: READ floor for the GLOBAL (cross-champion) top lists — higher than the
#: per-champion floor because the pool is summed across every champion.
TOP_MIN_GAMES = 200

# CDragon augment ``rarity`` values. 4 ("unique") isn't a draft-round rarity
# (the champion_build panel only buckets prismatic/gold/silver) but the
# /augments catalog surfaces it — special rule-changing picks (e.g. "Recebe
# uma Bigorna de Atributo Prismática").
_RARITY_SILVER = 0
_RARITY_GOLD = 1
_RARITY_PRISMATIC = 2
_RARITY_UNIQUE = 4

_CATALOG_RARITY: dict[int, str] = {
    _RARITY_SILVER: "silver",
    _RARITY_GOLD: "gold",
    _RARITY_PRISMATIC: "prismatic",
    _RARITY_UNIQUE: "unique",
}

_HTTP_TIMEOUT = 15.0

# items.json carries no rarity/category field for items (unlike augments.json's
# `rarity`) and the 48 real Prismatic Items have no shared id range — they're
# scattered across 443xxx, 447xxx, AND several reused base-game SR ids
# (e.g. 6632 Divine Sunderer, 3131 Sword of the Divine). An id-range guess
# (what shipped first) was flat wrong: it caught 9 unrelated 228xxx items
# (Anathema's Chains, Wooglet's Witchcap, Deathblade, Adaptive Helm, Obsidian
# Cleaver, Sanguine Blade, Runeglaive, Multitool, Abyssal Mask — a different,
# unrelated Arena shop tier) and missed every real one. This is an explicit
# id allowlist instead, cross-checked name-by-name against the League Wiki's
# "Prismatic items" category (wiki.leagueoflegends.com/en-us/Category:
# Prismatic_items, 48 entries) against CDragon's items.json 2026-08-01 —
# re-verify both sources if Riot adds/removes Prismatic Items.
PRISMATIC_ITEM_IDS: frozenset[int] = frozenset(
    {
        447122,  # Black Hole Gauntlet
        443059,  # Cloak of Starry Night
        4644,  # Crown of the Shattered Queen
        447109,  # Cruelty
        443054,  # Darksteel Talons
        447107,  # Decapitator
        443056,  # Demon King's Crown
        4637,  # Demonic Embrace
        447113,  # Detonation Orb
        447120,  # Diamond-Tipped Spear
        6632,  # Divine Sunderer
        447106,  # Dragonheart
        6691,  # Duskblade of Draktharr
        443063,  # Eleisa's Miracle
        447105,  # Empyrean Promise
        6656,  # Everfrost
        447112,  # Flesheater
        443061,  # Force of Entropy
        443055,  # Fulmination
        6671,  # Galeforce
        447101,  # Gambler's Blade
        3193,  # Gargoyle Stoneplate
        6630,  # Goredrinker
        443069,  # Hamstringer
        447103,  # Hemomancer's Helm
        443081,  # Hexbolt Companion
        4402,  # Innervating Locket
        447116,  # Kinkou Jitte
        447119,  # Lightning Rod
        447100,  # Mirage Blade
        447110,  # Moonflair Spellblade
        4636,  # Night Harvester
        6693,  # Prowler's Claw
        447123,  # Puppeteer
        447118,  # Pyromancer's Cloak
        6667,  # Radiant Virtue
        447102,  # Reality Fracture
        443090,  # Reaper's Toll
        447115,  # Regicide
        447114,  # Reverberation
        447108,  # Runecarver
        443062,  # Sanguine Gift
        443058,  # Shield of Molten Stone
        3131,  # Sword of the Divine
        443064,  # Talisman of Ascension
        443079,  # Turbo Chemtank
        447121,  # Twilight's Edge
        443080,  # Twin Mask
    }
)


def is_prismatic_item(item_id: int) -> bool:
    return item_id in PRISMATIC_ITEM_IDS


@dataclass(slots=True)
class AugmentCatalogEntryView:
    """One Arena augment for the global catalog (``/augments`` page).

    Identity only (name/icon/rarity/description) — not a placement stat row.
    """

    id: int
    name: str
    icon_url: str | None
    rarity: str  # "unique" | "prismatic" | "gold" | "silver"
    description: str


def _item_icon_url(icon_path: str) -> str | None:
    """CDragon ``iconPath`` -> fully-qualified icon URL (lowercased rel path)."""
    prefix = "/lol-game-data/assets/"
    if not icon_path.lower().startswith(prefix):
        return None
    rel = icon_path[len(prefix) :].lower()
    return f"{CDRAGON_BASE}/plugins/rcp-be-lol-game-data/global/default/{rel}"


def _augment_icon_url(icon_rel: str) -> str | None:
    """CDragon arena ``iconSmall`` (game-relative path) -> fully-qualified URL."""
    rel = icon_rel.strip().lower()
    if not rel:
        return None
    return f"{CDRAGON_BASE}/game/{rel}"


_DESC_TAG_RE = re.compile(r"<[^>]+>")
# CDragon uses two placeholder syntaxes: `@MaxStacks@` (scaling values, resolved
# per-rank in-game) and `%i:Augment%` (inline icon markers). Neither has a value
# outside a live game, so both are dropped rather than shown literally.
_DESC_PLACEHOLDER_RE = re.compile(r"[@%][^@%\s]+[@%]")
_DESC_WHITESPACE_RE = re.compile(r"\s+")


def _clean_display_text(desc: str) -> str:
    """CDragon rich-text (augment ``desc`` or item ``description``) -> plain
    PT-BR text for display.

    Strips rich-text tags (``<br>``, ``<spellName>...</spellName>``,
    ``<mainText>``/``<stats>``/``<attention>`` for items) — keeping the tags'
    inner text — and unresolved placeholders (``@MaxStacks@``,
    ``%i:Augment%``). The aggregate has no rank/context to resolve those
    against, and a literal "@MaxStacks@%" would read as broken data; we drop
    the token rather than show a fake value, same posture as dropping a stale
    augment id elsewhere in this module.
    """
    text = desc.replace("<br>", " ").replace("<br/>", " ").replace("<BR>", " ")
    text = _DESC_TAG_RE.sub("", text)
    text = _DESC_PLACEHOLDER_RE.sub("", text)
    return _DESC_WHITESPACE_RE.sub(" ", text).strip()


# JSON-safe cache rows: {"<id>": [name, icon_url|None, extra]} where extra is
# ``1 if boots else 0`` for items and the rarity int for augments.
_MapRow = tuple[str, str | None, int]

# Item map rows carry two more fields than the shared ``_MapRow`` shape (gold
# cost + description) — the match-detail item hover (Perfil `/perfil` loadout
# tooltip) needs both, and the augment map doesn't (augments have no gold
# cost; their description already comes from ``augment_catalog()``).
_ItemMapRow = tuple[str, str | None, int, int, str]


def _coerce_cached_map(raw: Any) -> dict[int, _MapRow]:
    """Coerce a JSON-decoded cached map (string keys / list rows) back."""
    if not isinstance(raw, dict):
        return {}
    out: dict[int, _MapRow] = {}
    for key, row in raw.items():
        try:
            entry_id = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            continue
        name, icon, extra = row
        if not isinstance(name, str) or not name:
            continue
        out[entry_id] = (name, icon if isinstance(icon, str) else None, int(extra or 0))
    return out


def _coerce_cached_item_map(raw: Any) -> dict[int, _ItemMapRow]:
    """Same as :func:`_coerce_cached_map` but for the wider item row shape."""
    if not isinstance(raw, dict):
        return {}
    out: dict[int, _ItemMapRow] = {}
    for key, row in raw.items():
        try:
            entry_id = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(row, (list, tuple)) or len(row) != 5:
            continue
        name, icon, is_boots, gold, description = row
        if not isinstance(name, str) or not name:
            continue
        out[entry_id] = (
            name,
            icon if isinstance(icon, str) else None,
            int(is_boots or 0),
            int(gold or 0),
            str(description or ""),
        )
    return out


class BuildRefService:
    """Async accessor: CDragon augment/item display maps + the augment catalog."""

    def __init__(
        self,
        *,
        redis: Any | None = None,
        http: httpx.AsyncClient | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._cache = DDragonCache(redis=redis, ttl_seconds=ttl_seconds)
        self._http = http
        self._owns_http = http is None
        self._lock = asyncio.Lock()

    # -- HTTP plumbing (same shape as DDragonService) -----------------------

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
        return self._http

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _fetch_json(self, url: str) -> Any | None:
        try:
            client = await self._client()
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            _log.warning("build_ref.fetch_failed", url=url, error=str(exc))
            return None

    # -- CDragon display maps ------------------------------------------------

    async def _item_map(self) -> dict[int, _ItemMapRow]:
        """``{itemId: (pt-BR name, icon_url, 1 if boots, gold total, description)}``
        (cache-first, 12h). Gold + description feed the match-detail item
        hover (Perfil `/perfil` loadout tooltip) — everything else already
        only used name/icon/is_boots, so those keep working unchanged (Python
        doesn't care that the tuple grew two more trailing fields)."""
        cached = await self._cache.get(KEY_ITEMS)
        coerced = _coerce_cached_item_map(cached)
        if coerced:
            return coerced

        async with self._lock:
            cached = await self._cache.get(KEY_ITEMS)
            coerced = _coerce_cached_item_map(cached)
            if coerced:
                return coerced
            data = await self._fetch_json(CDRAGON_ITEMS_URL)
            built: dict[str, _ItemMapRow] = {}
            if isinstance(data, list):
                for it in data:
                    if not isinstance(it, dict):
                        continue
                    try:
                        item_id = int(it.get("id", 0))
                    except (TypeError, ValueError):
                        continue
                    name = str(it.get("name", "")).strip()
                    if item_id <= 0 or not name:
                        continue
                    categories = it.get("categories") or []
                    is_boots = isinstance(categories, list) and "Boots" in categories
                    icon = _item_icon_url(str(it.get("iconPath", "")))
                    gold_raw = it.get("priceTotal")
                    gold = int(gold_raw) if isinstance(gold_raw, (int, float)) else 0
                    description = _clean_display_text(str(it.get("description", "") or ""))
                    built[str(item_id)] = (name, icon, 1 if is_boots else 0, gold, description)
            if built:
                await self._cache.set(KEY_ITEMS, built)
                _log.info("build_ref.items_loaded", count=len(built))
            return _coerce_cached_item_map(built)

    async def _augment_map(self) -> dict[int, _MapRow]:
        """``{augmentId: (pt-BR name, icon_url, rarity)}`` (cache-first, 12h)."""
        cached = await self._cache.get(KEY_AUGMENTS)
        coerced = _coerce_cached_map(cached)
        if coerced:
            return coerced

        async with self._lock:
            cached = await self._cache.get(KEY_AUGMENTS)
            coerced = _coerce_cached_map(cached)
            if coerced:
                return coerced
            data = await self._fetch_json(CDRAGON_AUGMENTS_URL)
            built: dict[str, _MapRow] = {}
            augments = data.get("augments") if isinstance(data, dict) else None
            if isinstance(augments, list):
                for aug in augments:
                    if not isinstance(aug, dict):
                        continue
                    try:
                        aug_id = int(aug.get("id", 0))
                    except (TypeError, ValueError):
                        continue
                    name = str(aug.get("name", "")).strip()
                    if aug_id <= 0 or not name:
                        continue
                    rarity = aug.get("rarity")
                    if rarity not in (_RARITY_SILVER, _RARITY_GOLD, _RARITY_PRISMATIC):
                        continue
                    icon = _augment_icon_url(str(aug.get("iconSmall", "")))
                    built[str(aug_id)] = (name, icon, int(rarity))
            if built:
                await self._cache.set(KEY_AUGMENTS, built)
                _log.info("build_ref.augments_loaded", count=len(built))
            return _coerce_cached_map(built)

    async def augment_catalog(self) -> list[AugmentCatalogEntryView]:
        """Every current Arena augment: id/name/icon/rarity/description, PT-BR.

        A direct CDragon fetch (cache-first, 12h). Broader than
        :meth:`_augment_map` (which only keeps rarities 0/1/2 for build-stats
        display matching): this also keeps rarity 4 ("unique" — special
        rule-changing picks) and carries the description.
        """
        cached = await self._cache.get(KEY_AUGMENT_CATALOG)
        entries = _coerce_catalog(cached)
        if entries:
            return entries

        async with self._lock:
            cached = await self._cache.get(KEY_AUGMENT_CATALOG)
            entries = _coerce_catalog(cached)
            if entries:
                return entries
            data = await self._fetch_json(CDRAGON_AUGMENTS_URL)
            augments = data.get("augments") if isinstance(data, dict) else None
            built: list[AugmentCatalogEntryView] = []
            if isinstance(augments, list):
                for aug in augments:
                    if not isinstance(aug, dict):
                        continue
                    try:
                        aug_id = int(aug.get("id", 0))
                    except (TypeError, ValueError):
                        continue
                    name = str(aug.get("name", "")).strip()
                    try:
                        rarity_num = int(aug.get("rarity", -1))
                    except (TypeError, ValueError):
                        continue
                    rarity_key = _CATALOG_RARITY.get(rarity_num)
                    if aug_id <= 0 or not name or rarity_key is None:
                        continue
                    icon = _augment_icon_url(str(aug.get("iconSmall", "")))
                    description = _clean_display_text(str(aug.get("desc", "") or ""))
                    built.append(
                        AugmentCatalogEntryView(
                            id=aug_id,
                            name=name,
                            icon_url=icon,
                            rarity=rarity_key,
                            description=description,
                        )
                    )
            if built:
                await self._cache.set(
                    KEY_AUGMENT_CATALOG, [_catalog_entry_to_json(e) for e in built]
                )
                _log.info("build_ref.augment_catalog_loaded", count=len(built))
            return built


def _catalog_entry_to_json(e: AugmentCatalogEntryView) -> dict[str, Any]:
    return {
        "id": e.id,
        "name": e.name,
        "icon_url": e.icon_url,
        "rarity": e.rarity,
        "description": e.description,
    }


def _catalog_entry_from_json(raw: Any) -> AugmentCatalogEntryView | None:
    if not isinstance(raw, dict):
        return None
    try:
        return AugmentCatalogEntryView(
            id=int(raw["id"]),
            name=str(raw["name"]),
            icon_url=raw.get("icon_url"),
            rarity=str(raw["rarity"]),
            description=str(raw.get("description", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _coerce_catalog(raw: Any) -> list[AugmentCatalogEntryView]:
    if not isinstance(raw, list):
        return []
    out: list[AugmentCatalogEntryView] = []
    for item in raw:
        entry = _catalog_entry_from_json(item)
        if entry is not None:
            out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Sync-cached singleton (same pattern as get_ddragon)
# ---------------------------------------------------------------------------

_SINGLETON: BuildRefService | None = None


def get_build_ref_service() -> BuildRefService:
    """Process-wide :class:`BuildRefService` singleton (sync, cached)."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = BuildRefService(redis=_build_redis())
    return _SINGLETON


def reset_build_ref_service() -> None:
    """Drop the singleton (test / reconfiguration aid)."""
    global _SINGLETON
    _SINGLETON = None
