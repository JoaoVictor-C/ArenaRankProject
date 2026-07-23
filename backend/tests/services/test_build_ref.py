"""Tests for the PROVISIONAL champion build-ref transform (build_ref_service).

Covers the credibility rules: empty-slot/id-0 skip, sample floor, unmapped-id
drop (rotated-out augments), numeric-tier -> letter mapping, tier-then-pick
ordering, rarity/boots categorization and per-category caps.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from arena.services.build_ref_service import (
    BUILD_MIN_GAMES,
    TOP_MIN_GAMES,
    BuildRefService,
    TopBuildView,
    _augment_icon_url,
    _coerce_cached_map,
    _coerce_top_view,
    _item_icon_url,
    _top_view_to_json,
)


def _stats(
    *,
    games: int = 500,
    tier: int = 1,
    pick: float = 0.10,
    top1: float = 0.25,
    top4: float = 0.80,
    avg: float = 3.0,
) -> dict[str, Any]:
    return {
        "num_games": games,
        "tier": tier,
        "pick_rate": pick,
        "top_1_percent": top1,
        "top_4_percent": top4,
        "avg_placement": avg,
        "win_rate": None,  # never read; present to mirror the real payload
    }


class TestEntries:
    def test_skips_empty_slot_floor_and_unmapped(self) -> None:
        raw = {
            "0": _stats(),  # empty item slot
            "10": _stats(games=BUILD_MIN_GAMES - 1),  # below floor
            "11": _stats(),  # not in display map (rotated out)
            "12": _stats(),  # the only survivor
        }
        display = {12: ("Nome", None, 0), 10: ("Outro", None, 0)}
        rows = BuildRefService._entries(raw, display)
        assert [e.id for e, _ in rows] == [12]

    def test_tier_letter_mapping_and_unknown_tier_dropped(self) -> None:
        raw = {
            "1": _stats(tier=1),
            "2": _stats(tier=2),
            "3": _stats(tier=3),
            "4": _stats(tier=4),
            "5": _stats(tier=5),
            "6": _stats(tier=0),  # unknown tier -> dropped
        }
        display = {i: (f"N{i}", None, 0) for i in range(1, 7)}
        rows = BuildRefService._entries(raw, display)
        assert {e.id: e.tier for e, _ in rows} == {1: "S", 2: "A", 3: "B", 4: "C", 5: "D"}

    def test_sorts_by_tier_then_pick_rate(self) -> None:
        raw = {
            "1": _stats(tier=2, pick=0.30),
            "2": _stats(tier=1, pick=0.05),
            "3": _stats(tier=1, pick=0.20),
        }
        display = {i: (f"N{i}", None, 0) for i in (1, 2, 3)}
        rows = BuildRefService._entries(raw, display)
        assert [e.id for e, _ in rows] == [3, 2, 1]  # S antes de A; dentro do S, pick desc

    def test_without_display_map_keeps_ids_with_blank_names(self) -> None:
        rows = BuildRefService._entries({"127": _stats()}, None)
        assert len(rows) == 1
        entry, extra = rows[0]
        assert (entry.id, entry.name, extra) == (127, "", 0)

    def test_percent_scaling(self) -> None:
        rows = BuildRefService._entries(
            {"1": _stats(pick=0.336, top1=0.241, top4=0.835, avg=2.817)},
            {1: ("N", None, 0)},
        )
        entry = rows[0][0]
        assert entry.pick_rate == 33.6
        assert entry.top1 == 24
        assert entry.top4 == 84  # round(83.5)
        assert entry.avg_place == 2.82


class _FakeResult:
    def __init__(self, row: Any) -> None:
        self._row = row

    def scalars(self) -> "_FakeResult":
        return self

    def first(self) -> Any:
        return self._row


class _FakeSession:
    def __init__(self, row: Any) -> None:
        self._row = row

    async def execute(self, _stmt: Any) -> _FakeResult:
        return _FakeResult(self._row)


def _service_with_maps(
    item_map: dict[int, tuple[str, str | None, int]],
    augment_map: dict[int, tuple[str, str | None, int]],
) -> BuildRefService:
    svc = BuildRefService(redis=None, http=None)

    async def _items() -> dict[int, tuple[str, str | None, int]]:
        return item_map

    async def _augments() -> dict[int, tuple[str, str | None, int]]:
        return augment_map

    svc._item_map = _items  # type: ignore[method-assign]
    svc._augment_map = _augments  # type: ignore[method-assign]
    return svc


class TestChampionBuild:
    async def test_none_without_snapshot(self) -> None:
        svc = _service_with_maps({}, {})
        view = await svc.champion_build(_FakeSession(None), champion_id=876)  # type: ignore[arg-type]
        assert view is None

    async def test_categorizes_rarities_boots_and_globals(self) -> None:
        payload = {
            "num_games": 20515,
            "avg_placement": 3.205,
            "tier": 1,
            "top_1_percent": 0.2,
            "top_4_percent": 0.74,
            "augments": {
                "1": _stats(tier=1),  # prismatic
                "2": _stats(tier=2),  # gold
                "3": _stats(tier=3),  # silver
                "9": _stats(tier=1),  # unmapped -> dropped
            },
            "items": {
                "223003": _stats(tier=1),
                "3009": _stats(tier=2),  # boots
                "0": _stats(),  # empty slot
            },
            "teammates": {"127": _stats(tier=1), "45": _stats(tier=2)},
        }
        row = SimpleNamespace(patch="16.14", dt="2026-07-19", payload=payload)
        svc = _service_with_maps(
            item_map={223003: ("Cajado", "http://i/223003.png", 0), 3009: ("Botas", None, 1)},
            augment_map={
                1: ("Prisma", None, 2),
                2: ("Ouro", None, 1),
                3: ("Prata", None, 0),
            },
        )
        view = await svc.champion_build(_FakeSession(row), champion_id=876)  # type: ignore[arg-type]
        assert view is not None
        assert view.patch == "16.14"
        assert view.updated_at == "2026-07-19"
        assert (view.games, view.tier, view.top1, view.top4) == (20515, "S", 20, 74)
        assert view.avg_place == 3.21
        assert [e.name for e in view.augments_prismatic] == ["Prisma"]
        assert [e.name for e in view.augments_gold] == ["Ouro"]
        assert [e.name for e in view.augments_silver] == ["Prata"]
        assert [e.name for e in view.items] == ["Cajado"]
        assert [e.name for e in view.boots] == ["Botas"]
        assert sorted(e.id for e in view.teammates) == [45, 127]
        assert all(e.name == "" for e in view.teammates)  # router resolves display

    async def test_unknown_patch_normalizes_to_blank(self) -> None:
        row = SimpleNamespace(patch="unknown", dt=None, payload={"num_games": 100})
        svc = _service_with_maps({}, {})
        view = await svc.champion_build(_FakeSession(row), champion_id=1)  # type: ignore[arg-type]
        assert view is not None
        assert view.patch == ""
        assert view.updated_at == ""
        assert view.tier is None


class TestAggregateSection:
    def test_weighted_merge_rank_and_share(self) -> None:
        # Mesmo augment em 2 campeões: merge ponderado por games.
        raws = [
            {"1": _stats(games=300, avg=2.0, top1=0.30, top4=0.90),
             "2": _stats(games=900, avg=4.0, top1=0.10, top4=0.50)},
            {"1": _stats(games=100, avg=4.0, top1=0.10, top4=0.50)},
        ]
        display = {1: ("Forte", None, 0), 2: ("Popular", None, 0)}
        out = BuildRefService._aggregate_section(
            raws, display, min_games=TOP_MIN_GAMES, cap=10
        )
        # Ordem = games desc: "Popular" (900) antes de "Forte" (400).
        assert [e.name for e in out] == ["Popular", "Forte"]
        forte = out[1]
        assert forte.games == 400
        assert forte.avg_place == 2.5  # (300*2 + 100*4) / 400
        assert forte.top1 == 25  # (300*.3 + 100*.1)/400 = .25
        # Tier por força (avg_place), posição relativa: com pool de 2, o melhor
        # cai em 1/2=0.5 → "B" e o pior em 1.0 → "D" (S exige top 10% do pool).
        assert forte.tier == "B"
        assert out[0].tier == "D"
        # pick = share da categoria: 900/1300, 400/1300.
        assert out[0].pick_rate == 69.2
        assert forte.pick_rate == 30.8

    def test_floor_and_unmapped_dropped(self) -> None:
        raws = [{"1": _stats(games=TOP_MIN_GAMES - 1), "9": _stats(games=5000)}]
        display = {1: ("Raso", None, 0)}  # 9 sem display -> dropado
        out = BuildRefService._aggregate_section(
            raws, display, min_games=TOP_MIN_GAMES, cap=10
        )
        assert out == []


class _FakeAllResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> "_FakeAllResult":
        return self

    def all(self) -> list[Any]:
        return self._rows


class _FakeAllSession:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def execute(self, _stmt: Any) -> _FakeAllResult:
        return _FakeAllResult(self._rows)


class TestTopBuild:
    async def test_empty_db_returns_zero_and_never_caches(self) -> None:
        svc = _service_with_maps({}, {})
        view = await svc.top_build(_FakeAllSession([]))  # type: ignore[arg-type]
        assert view.games == 0 and view.augments == []
        assert svc._cache.get_local("buildref:top:pt_br") is None

    async def test_latest_snapshot_per_champion_wins(self) -> None:
        old = SimpleNamespace(
            champion_id=876, patch="16.13", dt="2026-07-01", fetched_at=1,
            payload={"num_games": 999999, "augments": {}, "items": {}},
        )
        new = SimpleNamespace(
            champion_id=876, patch="16.14", dt="2026-07-19", fetched_at=2,
            payload={
                "num_games": 1000,
                "augments": {"1": _stats(games=500)},
                "items": {"223003": _stats(games=500)},
            },
        )
        svc = _service_with_maps(
            item_map={223003: ("Cajado", None, 0)},
            augment_map={1: ("Prisma", None, 2)},
        )
        view = await svc.top_build(_FakeAllSession([old, new]))  # type: ignore[arg-type]
        assert view.games == 1000  # o snapshot velho não conta
        assert view.patch == "16.14"
        assert view.updated_at == "2026-07-19"
        assert [e.name for e in view.augments] == ["Prisma"]
        assert [e.name for e in view.items] == ["Cajado"]

    def test_top_view_json_roundtrip(self) -> None:
        view = TopBuildView(
            patch="16.14", updated_at="2026-07-19", games=10, champions=2,
        )
        assert _coerce_top_view(_top_view_to_json(view)) == view
        assert _coerce_top_view(None) is None
        assert _coerce_top_view({"games": "x"}) is None


class TestIconUrls:
    def test_item_icon_url_lowercases_relative_path(self) -> None:
        url = _item_icon_url("/lol-game-data/assets/ASSETS/Items/Icons2D/1058_Mage.png")
        assert url == (
            "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/"
            "global/default/assets/items/icons2d/1058_mage.png"
        )

    def test_item_icon_url_rejects_foreign_prefix(self) -> None:
        assert _item_icon_url("/other/path.png") is None

    def test_augment_icon_url(self) -> None:
        url = _augment_icon_url("assets/ux/cherry/augments/icons/Acc_small.png")
        assert url == (
            "https://raw.communitydragon.org/latest/game/"
            "assets/ux/cherry/augments/icons/acc_small.png"
        )
        assert _augment_icon_url("") is None


class TestCoerceCachedMap:
    def test_roundtrip_and_garbage_tolerance(self) -> None:
        raw = {
            "10": ["Nome", "http://icon", 2],
            "x": ["a", None, 0],  # non-int key
            "11": ["", None, 0],  # blank name
            "12": ["Ok", None],  # wrong arity
            "13": ["Certo", None, 1],
        }
        out = _coerce_cached_map(raw)
        assert out == {10: ("Nome", "http://icon", 2), 13: ("Certo", None, 1)}

    def test_non_dict_is_empty(self) -> None:
        assert _coerce_cached_map(None) == {}
        assert _coerce_cached_map([1, 2]) == {}
