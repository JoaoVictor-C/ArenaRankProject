"""Tests for ``build_ref_service`` — CDragon display resolution for augments/items.

Covers what's left after the stats half moved to ``champion_build_stats``
(native rollup — see ``test_champion_build_stats_rollup.py`` /
``test_champion_build_stats_read.py``): icon URL construction, the augment
description cleaner, the augment catalog fetch (rarity mapping including
"unique", cache-then-no-refetch), and the cached-map coercion the display
maps round-trip through.
"""

from __future__ import annotations

from typing import Any

from arena.services.build_ref_service import (
    BuildRefService,
    _augment_icon_url,
    _clean_display_text,
    _coerce_cached_map,
    _item_icon_url,
)


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


class TestCleanAugmentDescription:
    def test_strips_tags_but_keeps_inner_text(self) -> None:
        assert (
            _clean_display_text(
                "Recebe o Feitiço de Invocador <spellName>Aquecimento</spellName>."
            )
            == "Recebe o Feitiço de Invocador Aquecimento."
        )

    def test_br_becomes_a_space_not_glued_words(self) -> None:
        assert _clean_display_text("Primeira frase.<br><br>Segunda frase.") == (
            "Primeira frase. Segunda frase."
        )

    def test_drops_at_placeholders(self) -> None:
        assert _clean_display_text("até um máximo de @MaxStacks@%.") == (
            "até um máximo de %."
        )

    def test_drops_percent_icon_placeholders(self) -> None:
        assert _clean_display_text(
            "Recebe <keywordMajor>%i:StatAnvil% Bigorna</keywordMajor>."
        ) == "Recebe Bigorna."

    def test_does_not_eat_a_real_percentage(self) -> None:
        assert _clean_display_text("aumentar seu dano em 2% por segundo") == (
            "aumentar seu dano em 2% por segundo"
        )

    def test_empty_is_empty(self) -> None:
        assert _clean_display_text("") == ""


def _cdragon_augment(
    *, aug_id: int, name: str = "Nome", rarity: int = 0, desc: str = "Descrição."
) -> dict[str, Any]:
    return {
        "id": aug_id,
        "name": name,
        "rarity": rarity,
        "desc": desc,
        "iconSmall": f"assets/ux/cherry/augments/icons/{aug_id}_small.png",
    }


class TestAugmentCatalog:
    async def test_maps_rarities_including_unique(self) -> None:
        svc = BuildRefService(redis=None, http=None)
        calls = 0

        async def fake_fetch(_url: str) -> Any:
            nonlocal calls
            calls += 1
            return {
                "augments": [
                    _cdragon_augment(aug_id=1, name="Prata", rarity=0),
                    _cdragon_augment(aug_id=2, name="Ouro", rarity=1),
                    _cdragon_augment(aug_id=3, name="Prisma", rarity=2),
                    _cdragon_augment(aug_id=4, name="Único", rarity=4),
                    _cdragon_augment(aug_id=5, name="RaridadeDesconhecida", rarity=99),
                    _cdragon_augment(aug_id=0, name="IdInvalido", rarity=0),
                    {"id": 6, "name": "", "rarity": 0},  # nome vazio -> descartado
                ]
            }

        svc._fetch_json = fake_fetch  # type: ignore[method-assign]
        entries = await svc.augment_catalog()
        by_id = {e.id: e for e in entries}
        assert set(by_id) == {1, 2, 3, 4}
        assert by_id[1].rarity == "silver"
        assert by_id[2].rarity == "gold"
        assert by_id[3].rarity == "prismatic"
        assert by_id[4].rarity == "unique"
        assert by_id[1].icon_url == (
            "https://raw.communitydragon.org/latest/game/"
            "assets/ux/cherry/augments/icons/1_small.png"
        )

        # Segunda chamada serve do cache — sem novo fetch.
        await svc.augment_catalog()
        assert calls == 1

    async def test_empty_upstream_returns_empty_list(self) -> None:
        svc = BuildRefService(redis=None, http=None)

        async def fake_fetch(_url: str) -> Any:
            return None

        svc._fetch_json = fake_fetch  # type: ignore[method-assign]
        assert await svc.augment_catalog() == []


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
