"""PROVISIONAL — categorized champion reference build (``champion_build_ref``).

Serves the "build recomendada" surface: augments grouped by in-game rarity
(prismatic / gold / silver — the three draft rounds), items split into itens /
botas, and reference teammates, for one champion. Source is the external
GLOBAL patch aggregate snapshotted into ``champion_build_ref`` by
``scripts/fetch_build_ref.py`` (migration 0006) — not our BR ladder; the UI
labels it as such.

Display names and icons resolve via CommunityDragon (PT-BR locale):

- items:    ``plugins/rcp-be-lol-game-data/global/pt_br/v1/items.json``
  (includes the Arena ``22xxxxx`` item variants ddragon lacks; ``categories``
  containing ``"Boots"`` drives the itens/botas split).
- augments: ``cdragon/arena/pt_br.json`` (``rarity``: 0=silver 1=gold
  2=prismatic).

Both are cached 12h through the same two-tier :class:`DDragonCache` pattern
the ddragon service uses (in-process always, Redis best-effort).

ToS posture: every surfaced stat is placement-derived (top1/top4 rate +
average placement + pick rate); the aggregate's ``win_rate`` fields (null
upstream anyway) are never read. Entries whose id no longer maps to a live
CDragon name (augments rotated out of the current patch, ~12% of games in
sampling) are DROPPED — a bare numeric id would read as broken data.

Drop the whole feature (this module, the table/model, migration 0006, the
fetch script, the endpoint) once native augment ingestion lands.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arena.core.logging import get_logger
from arena.db import models as m
from arena.ddragon.cache import DEFAULT_TTL_SECONDS, DDragonCache

# Redis builder shared with the ddragon singleton (same optional-Redis policy).
from arena.ddragon.service import _build_redis

_log = get_logger("arena.services.build_ref")

CDRAGON_BASE = "https://raw.communitydragon.org/latest"
CDRAGON_ITEMS_URL = f"{CDRAGON_BASE}/plugins/rcp-be-lol-game-data/global/pt_br/v1/items.json"
CDRAGON_AUGMENTS_URL = f"{CDRAGON_BASE}/cdragon/arena/pt_br.json"

KEY_ITEMS = "cdragon:items:pt_br"
KEY_AUGMENTS = "cdragon:augments:pt_br"

#: Sample floor per entry (games). The aggregate carries plenty of sub-50
#: noise entries with confident-looking tiers; below this we don't show them.
#: Exposed on the API response so the UI can state the criterion.
BUILD_MIN_GAMES = 50

#: Sample floor per entry in the GLOBAL (cross-champion) top lists — higher
#: than the per-champion floor because the global pool is ~170x larger.
TOP_MIN_GAMES = 200

# Display caps for the global top lists.
_CAP_TOP_AUGMENTS = 12
_CAP_TOP_ITEMS = 14

# Redis/in-process key for the aggregated global top (heavy to recompute:
# ~170 JSONB payloads scanned).
KEY_TOP_BUILD = "buildref:top:pt_br"

# Relative-position cutoffs for the global tier letters (by weighted average
# placement, best first) — same bucketing idea as the champions tierlist.
_TOP_TIER_CUTOFFS: list[tuple[str, float]] = [
    ("S", 0.10),
    ("A", 0.30),
    ("B", 0.55),
    ("C", 0.80),
    ("D", 1.0),
]

# Display caps per category (sorted best-first before capping).
_CAP_AUGMENTS_PER_RARITY = 8
_CAP_ITEMS = 12
_CAP_BOOTS = 4
_CAP_TEAMMATES = 8

# Aggregate's numeric tier (1 best .. 5 worst) -> our tier letters.
_TIER_LETTER: dict[int, str] = {1: "S", 2: "A", 3: "B", 4: "C", 5: "D"}
_TIER_ORDER = "SABCD"

# CDragon augment ``rarity`` values.
_RARITY_SILVER = 0
_RARITY_GOLD = 1
_RARITY_PRISMATIC = 2

_HTTP_TIMEOUT = 15.0


@dataclass(slots=True)
class BuildEntryView:
    """One augment / item / teammate row (teammates: ``id`` is a championId)."""

    id: int
    name: str
    icon_url: str | None
    tier: str  # "S".."D"
    games: int
    avg_place: float
    top1: int  # 0..100
    top4: int  # 0..100
    pick_rate: float  # 0..100


@dataclass(slots=True)
class TopBuildView:
    """Global (cross-champion) top augments/items — the /winrate right rail."""

    patch: str
    updated_at: str
    games: int  # total champion-games in the sampled snapshots
    champions: int  # champions aggregated
    augments: list[BuildEntryView] = field(default_factory=list)
    items: list[BuildEntryView] = field(default_factory=list)


@dataclass(slots=True)
class ChampionBuildView:
    """Categorized reference build for one champion (global patch aggregate)."""

    patch: str
    updated_at: str  # snapshot date ("2026-07-19"); "" when unknown
    games: int
    avg_place: float
    tier: str | None
    top1: int
    top4: int
    augments_prismatic: list[BuildEntryView] = field(default_factory=list)
    augments_gold: list[BuildEntryView] = field(default_factory=list)
    augments_silver: list[BuildEntryView] = field(default_factory=list)
    items: list[BuildEntryView] = field(default_factory=list)
    boots: list[BuildEntryView] = field(default_factory=list)
    # name/icon resolution for teammates happens in the router via the ddragon
    # helpers already used by the tierlist (name is "" here).
    teammates: list[BuildEntryView] = field(default_factory=list)


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


# JSON-safe cache rows: {"<id>": [name, icon_url|None, extra]} where extra is
# ``1 if boots else 0`` for items and the rarity int for augments.
_MapRow = tuple[str, str | None, int]


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


class BuildRefService:
    """Async accessor: CDragon display maps + ``champion_build_ref`` transform."""

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

    async def _item_map(self) -> dict[int, _MapRow]:
        """``{itemId: (pt-BR name, icon_url, 1 if boots)}`` (cache-first, 12h)."""
        cached = await self._cache.get(KEY_ITEMS)
        coerced = _coerce_cached_map(cached)
        if coerced:
            return coerced

        async with self._lock:
            cached = await self._cache.get(KEY_ITEMS)
            coerced = _coerce_cached_map(cached)
            if coerced:
                return coerced
            data = await self._fetch_json(CDRAGON_ITEMS_URL)
            built: dict[str, _MapRow] = {}
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
                    built[str(item_id)] = (name, icon, 1 if is_boots else 0)
            if built:
                await self._cache.set(KEY_ITEMS, built)
                _log.info("build_ref.items_loaded", count=len(built))
            return _coerce_cached_map(built)

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

    # -- transform ----------------------------------------------------------

    @staticmethod
    def _entries(
        raw: Any,
        display: dict[int, _MapRow] | None,
        *,
        min_games: int = BUILD_MIN_GAMES,
    ) -> list[tuple[BuildEntryView, int]]:
        """Filtered, sorted ``(entry, extra)`` rows from one aggregate section.

        ``display=None`` (teammates) keeps every id and leaves ``name`` blank
        for the router to resolve via ddragon. With a display map, unmapped ids
        are dropped (credibility: no name, no row). ``extra`` is the map's third
        field (boots flag / rarity), 0 without a map.
        """
        if not isinstance(raw, dict):
            return []
        rows: list[tuple[BuildEntryView, int]] = []
        for key, stats in raw.items():
            try:
                entry_id = int(key)
            except (TypeError, ValueError):
                continue
            if entry_id <= 0 or not isinstance(stats, dict):
                continue  # id 0 = empty item slot in the aggregate
            games = int(stats.get("num_games") or 0)
            if games < min_games:
                continue
            tier = _TIER_LETTER.get(int(stats.get("tier") or 0))
            if tier is None:
                continue
            name = ""
            icon: str | None = None
            extra = 0
            if display is not None:
                mapped = display.get(entry_id)
                if mapped is None:
                    continue
                name, icon, extra = mapped
            rows.append(
                (
                    BuildEntryView(
                        id=entry_id,
                        name=name,
                        icon_url=icon,
                        tier=tier,
                        games=games,
                        avg_place=round(float(stats.get("avg_placement") or 0.0), 2),
                        top1=round(float(stats.get("top_1_percent") or 0.0) * 100),
                        top4=round(float(stats.get("top_4_percent") or 0.0) * 100),
                        pick_rate=round(float(stats.get("pick_rate") or 0.0) * 100, 1),
                    ),
                    extra,
                )
            )
        rows.sort(key=lambda r: (_TIER_ORDER.index(r[0].tier), -r[0].pick_rate))
        return rows

    async def champion_build(
        self, session: AsyncSession, *, champion_id: int
    ) -> ChampionBuildView | None:
        """Latest snapshot for one champion, categorized; ``None`` with no row."""
        stmt = (
            select(m.ChampionBuildRef)
            .where(m.ChampionBuildRef.champion_id == champion_id)
            .order_by(
                m.ChampionBuildRef.dt.desc().nulls_last(),
                m.ChampionBuildRef.fetched_at.desc(),
            )
            .limit(1)
        )
        row = (await session.execute(stmt)).scalars().first()
        if row is None:
            return None
        payload: dict[str, Any] = row.payload if isinstance(row.payload, dict) else {}

        item_map, augment_map = await asyncio.gather(self._item_map(), self._augment_map())

        augments = self._entries(payload.get("augments"), augment_map)
        by_rarity: dict[int, list[BuildEntryView]] = {
            _RARITY_PRISMATIC: [],
            _RARITY_GOLD: [],
            _RARITY_SILVER: [],
        }
        for entry, rarity in augments:
            bucket = by_rarity.get(rarity)
            if bucket is not None and len(bucket) < _CAP_AUGMENTS_PER_RARITY:
                bucket.append(entry)

        items: list[BuildEntryView] = []
        boots: list[BuildEntryView] = []
        for entry, is_boots in self._entries(payload.get("items"), item_map):
            target, cap = (boots, _CAP_BOOTS) if is_boots else (items, _CAP_ITEMS)
            if len(target) < cap:
                target.append(entry)

        teammates = [
            entry
            for entry, _ in self._entries(payload.get("teammates"), None)[:_CAP_TEAMMATES]
        ]

        tier = _TIER_LETTER.get(int(payload.get("tier") or 0))
        return ChampionBuildView(
            patch=row.patch if row.patch != "unknown" else "",
            updated_at=row.dt or "",
            games=int(payload.get("num_games") or 0),
            avg_place=round(float(payload.get("avg_placement") or 0.0), 2),
            tier=tier,
            top1=round(float(payload.get("top_1_percent") or 0.0) * 100),
            top4=round(float(payload.get("top_4_percent") or 0.0) * 100),
            augments_prismatic=by_rarity[_RARITY_PRISMATIC],
            augments_gold=by_rarity[_RARITY_GOLD],
            augments_silver=by_rarity[_RARITY_SILVER],
            items=items,
            boots=boots,
            teammates=teammates,
        )


    # -- global top (cross-champion aggregate) -------------------------------

    @staticmethod
    def _aggregate_section(
        raws: list[Any],
        display: dict[int, _MapRow],
        *,
        min_games: int,
        cap: int,
    ) -> list[BuildEntryView]:
        """Games-weighted cross-champion aggregate of one payload section.

        Rank order = total games desc ("em alta": what the meta actually plays).
        Tier letter = relative position by weighted average placement (strength),
        so a popular-but-weak pick still reads as B/C. ``pick_rate`` becomes the
        entry's share of the whole category's games (the mock's "PR").
        """
        acc: dict[int, list[float]] = {}  # id -> [games, avg_sum, top1_sum, top4_sum]
        for raw in raws:
            if not isinstance(raw, dict):
                continue
            for key, stats in raw.items():
                try:
                    entry_id = int(key)
                except (TypeError, ValueError):
                    continue
                if entry_id <= 0 or not isinstance(stats, dict) or entry_id not in display:
                    continue
                games = int(stats.get("num_games") or 0)
                if games <= 0:
                    continue
                slot = acc.setdefault(entry_id, [0.0, 0.0, 0.0, 0.0])
                slot[0] += games
                slot[1] += games * float(stats.get("avg_placement") or 0.0)
                slot[2] += games * float(stats.get("top_1_percent") or 0.0)
                slot[3] += games * float(stats.get("top_4_percent") or 0.0)

        pool = [(eid, s) for eid, s in acc.items() if s[0] >= min_games]
        if not pool:
            return []
        category_games = sum(s[0] for _, s in pool)

        # Tier by strength: weighted avg placement, best (lowest) first.
        by_strength = sorted(pool, key=lambda p: p[1][1] / p[1][0])
        tier_of: dict[int, str] = {}
        total = len(by_strength)
        for pos, (eid, _s) in enumerate(by_strength):
            frac = (pos + 1) / total
            tier_of[eid] = next(t for t, cutoff in _TOP_TIER_CUTOFFS if frac <= cutoff)

        out: list[BuildEntryView] = []
        for eid, s in sorted(pool, key=lambda p: -p[1][0])[:cap]:
            games = int(s[0])
            name, icon, _extra = display[eid]
            out.append(
                BuildEntryView(
                    id=eid,
                    name=name,
                    icon_url=icon,
                    tier=tier_of[eid],
                    games=games,
                    avg_place=round(s[1] / s[0], 2),
                    top1=round(s[2] / s[0] * 100),
                    top4=round(s[3] / s[0] * 100),
                    pick_rate=round(s[0] / category_games * 100, 1),
                )
            )
        return out

    async def top_build(self, session: AsyncSession) -> TopBuildView:
        """Global top augments/items across every champion snapshot (cached 12h)."""
        cached = _coerce_top_view(await self._cache.get(KEY_TOP_BUILD))
        if cached is not None:
            return cached

        rows = (await session.execute(select(m.ChampionBuildRef))).scalars().all()
        # Latest snapshot per champion (dt lexicographic, then fetched_at).
        latest: dict[int, m.ChampionBuildRef] = {}
        for row in rows:
            cur = latest.get(row.champion_id)
            key = (row.dt or "", row.fetched_at)
            if cur is None or key > ((cur.dt or ""), cur.fetched_at):
                latest[row.champion_id] = row
        if not latest:
            return TopBuildView(patch="", updated_at="", games=0, champions=0)

        item_map, augment_map = await asyncio.gather(self._item_map(), self._augment_map())
        payloads = [r.payload for r in latest.values() if isinstance(r.payload, dict)]
        augments = self._aggregate_section(
            [p.get("augments") for p in payloads],
            augment_map,
            min_games=TOP_MIN_GAMES,
            cap=_CAP_TOP_AUGMENTS,
        )
        items = self._aggregate_section(
            [p.get("items") for p in payloads],
            item_map,
            min_games=TOP_MIN_GAMES,
            cap=_CAP_TOP_ITEMS,
        )

        patches = [r.patch for r in latest.values() if r.patch and r.patch != "unknown"]
        patch = max(set(patches), key=patches.count) if patches else ""
        dts = [r.dt for r in latest.values() if r.dt]
        view = TopBuildView(
            patch=patch,
            updated_at=max(dts) if dts else "",
            games=sum(int(p.get("num_games") or 0) for p in payloads),
            champions=len(latest),
            augments=augments,
            items=items,
        )
        if view.games > 0:  # never pin an empty aggregate for 12h
            await self._cache.set(KEY_TOP_BUILD, _top_view_to_json(view))
        return view


def _entry_to_json(e: BuildEntryView) -> dict[str, Any]:
    return {
        "id": e.id,
        "name": e.name,
        "icon_url": e.icon_url,
        "tier": e.tier,
        "games": e.games,
        "avg_place": e.avg_place,
        "top1": e.top1,
        "top4": e.top4,
        "pick_rate": e.pick_rate,
    }


def _entry_from_json(raw: Any) -> BuildEntryView | None:
    if not isinstance(raw, dict):
        return None
    try:
        return BuildEntryView(
            id=int(raw["id"]),
            name=str(raw["name"]),
            icon_url=raw.get("icon_url"),
            tier=str(raw["tier"]),
            games=int(raw["games"]),
            avg_place=float(raw["avg_place"]),
            top1=int(raw["top1"]),
            top4=int(raw["top4"]),
            pick_rate=float(raw["pick_rate"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _top_view_to_json(v: TopBuildView) -> dict[str, Any]:
    return {
        "patch": v.patch,
        "updated_at": v.updated_at,
        "games": v.games,
        "champions": v.champions,
        "augments": [_entry_to_json(e) for e in v.augments],
        "items": [_entry_to_json(e) for e in v.items],
    }


def _coerce_top_view(raw: Any) -> TopBuildView | None:
    if not isinstance(raw, dict):
        return None
    try:
        augments = [e for e in (_entry_from_json(x) for x in raw.get("augments", [])) if e]
        items = [e for e in (_entry_from_json(x) for x in raw.get("items", [])) if e]
        return TopBuildView(
            patch=str(raw.get("patch", "")),
            updated_at=str(raw.get("updated_at", "")),
            games=int(raw.get("games", 0)),
            champions=int(raw.get("champions", 0)),
            augments=augments,
            items=items,
        )
    except (TypeError, ValueError):
        return None


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
