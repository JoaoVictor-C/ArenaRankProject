"""``GET /api/v1/match/{matchId}`` — native item/augment resolution + derived
combat telemetry.

Pure unit tests for ``_resolve_items``/``_resolve_augments``/
``_kill_participation``/``_damage_per_minute`` (arena.api.routers.match). No
DB/HTTP — these are plain dict lookups and arithmetic over already-fetched rows.
"""

from __future__ import annotations

from dataclasses import dataclass

from arena.api.routers.match import (
    _damage_per_minute,
    _kill_participation,
    _resolve_augments,
    _resolve_items,
)
from arena.schemas.match import MatchAugmentEntry, MatchLoadoutEntry


@dataclass
class _FakeAugment:
    id: int
    name: str
    icon_url: str | None
    rarity: str
    description: str = ""


_ITEM_MAP = {
    # (name, icon_url, is_boots, gold_total, description)
    3348: ("Analisador Arcano", "https://example/3348.png", 0, 0, ""),
    226609: ("Chuteiras", "https://example/226609.png", 1, 300, "Botas básicas."),
}

_AUGMENT_MAP = {
    23: _FakeAugment(
        id=23, name="Dança Demoníaca", icon_url="https://example/23.png", rarity="gold",
        description="Efeito de exemplo.",
    ),
    238: _FakeAugment(
        id=238, name="Transmutar: Prismático", icon_url="https://example/238.png", rarity="prismatic"
    ),
}


class TestResolveItems:
    def test_resolves_known_ids_in_order(self) -> None:
        out = _resolve_items([3348, 226609], _ITEM_MAP)
        assert out == [
            MatchLoadoutEntry(id=3348, name="Analisador Arcano", icon_url="https://example/3348.png"),
            MatchLoadoutEntry(
                id=226609,
                name="Chuteiras",
                icon_url="https://example/226609.png",
                gold=300,
                description="Botas básicas.",
            ),
        ]

    def test_unmapped_id_is_dropped_not_shown_as_bare_id(self) -> None:
        out = _resolve_items([3348, 999999], _ITEM_MAP)
        assert [e.id for e in out] == [3348]

    def test_none_and_empty_are_both_empty_list(self) -> None:
        assert _resolve_items(None, _ITEM_MAP) == []
        assert _resolve_items([], _ITEM_MAP) == []


class TestResolveAugments:
    def test_resolves_known_ids_with_rarity(self) -> None:
        out = _resolve_augments([23], _AUGMENT_MAP)
        assert out == [
            MatchAugmentEntry(
                id=23,
                name="Dança Demoníaca",
                icon_url="https://example/23.png",
                rarity="gold",
                description="Efeito de exemplo.",
            )
        ]

    def test_a_genuine_repeat_from_an_augment_granting_effect_shows_twice(self) -> None:
        """Unlike the champion_build_stats rollup (which dedupes a repeated pick
        so it isn't double-counted statistically), the per-match loadout display
        must show exactly what the player received — including a real duplicate."""
        out = _resolve_augments([238, 238], _AUGMENT_MAP)
        assert [e.id for e in out] == [238, 238]

    def test_unmapped_id_is_dropped(self) -> None:
        out = _resolve_augments([23, 999999], _AUGMENT_MAP)
        assert [e.id for e in out] == [23]

    def test_none_and_empty_are_both_empty_list(self) -> None:
        assert _resolve_augments(None, _AUGMENT_MAP) == []
        assert _resolve_augments([], _AUGMENT_MAP) == []


@dataclass
class _FakePart:
    kills: int | None = None
    assists: int | None = None
    damage_to_champions: int | None = None


class TestKillParticipation:
    def test_derived_from_own_subteam_not_riot_legacy_team_id(self) -> None:
        """Regression for the gotcha found while planning this feature: Riot's
        own ``challenges.killParticipation`` is computed against the legacy
        2-bucket ``teamId`` (~9 players/side in a 3v3), NOT the real Arena
        subteam. Verified live on participant puuid
        ``fenrirgu#fenfa`` (match BR1_3267965087): Riot reported 31.25% while
        the player's actual 3-person-subteam-scoped kill participation was
        100% (kills=3 + assists=7 == the subteam's total of 10 kills). This
        test locks in the correct (subteam-scoped) formula so nobody
        "simplifies" it back to trusting Riot's field."""
        part = _FakePart(kills=3, assists=7)
        # The real subteam's total kills (3 players), NOT the ~9-player legacy
        # teamId bucket Riot's own challenges.killParticipation would use.
        assert _kill_participation(part, team_kills=10) == 100

    def test_none_when_primitives_not_captured(self) -> None:
        assert _kill_participation(_FakePart(), team_kills=10) is None

    def test_zero_team_kills_is_zero_not_a_crash(self) -> None:
        part = _FakePart(kills=0, assists=0)
        assert _kill_participation(part, team_kills=0) == 0

    def test_partial_participation(self) -> None:
        part = _FakePart(kills=1, assists=2)
        assert _kill_participation(part, team_kills=6) == 50

    def test_rounds_to_a_whole_percentage(self) -> None:
        """Regression: an unrounded float here rendered as "68,966% part." in
        the UI — the frontend's ``nf()`` is a generic thousands-separator
        formatter, not a rate formatter, and the mock fixtures the frontend was
        built against use plain integers (e.g. ``"killParticipation": 78``)."""
        part = _FakePart(kills=2, assists=1)
        result = _kill_participation(part, team_kills=3)
        assert result == 100
        assert isinstance(result, int)


class TestDamagePerMinute:
    def test_uses_match_duration_not_participant_time_played(self) -> None:
        """Verified against a live match: totalDamageDealtToChampions=18770 over
        gameDuration=1519s (25.317min) == 741.4 before rounding, matching Riot's
        own challenges.damagePerMinute exactly — using the MATCH duration, not
        this participant's individual timePlayed."""
        part = _FakePart(damage_to_champions=18770)
        result = _damage_per_minute(part, duration_seconds=1519)
        assert result == 741
        assert isinstance(result, int)

    def test_none_when_damage_not_captured(self) -> None:
        assert _damage_per_minute(_FakePart(), duration_seconds=1519) is None

    def test_none_when_duration_missing_or_zero(self) -> None:
        part = _FakePart(damage_to_champions=18770)
        assert _damage_per_minute(part, duration_seconds=None) is None
        assert _damage_per_minute(part, duration_seconds=0) is None
