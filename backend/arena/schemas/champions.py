"""Contract §4 — GET /api/v1/champions response DTOs (DTO sample subsystem).

ToS Riot: champion winrate is allowed. Augment/item surfaces are placement-
derived only (top1/top2/top4 rate + average placement from an external global
reference aggregate); a raw augment/item *winrate* is never exposed.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from arena.schemas.common import ArenaModel, AvatarColors

ChampTierKey = Literal["S+", "S", "A", "B", "C", "D"]


class ChampTopPlayer(ArenaModel):
    """The champion's reference main — busiest player on it this season.

    Placement-derived (ToS): ``winrate`` is the top-half ("win") rate on the
    champion, never augment/item winrate.
    """

    name: str  # display name (part before the #)
    handle: str  # "#TAG"
    avatar: AvatarColors  # gradient fallback for the summoner icon
    profile_icon_url: str | None = None  # real ddragon summoner icon; None → gradient
    games: int
    winrate: int  # 0..100 — top-half finishes / games on this champion
    avg_place: float


class ChampRow(ArenaModel):
    rank: int
    champion_id: int
    champion: AvatarColors  # gradient fallback (used until the icon art loads)
    champion_icon_url: str | None = None  # real ddragon square icon; None → gradient
    name: str
    role: str
    games: int  # eligible champion-games sampled this season
    top4: int
    first: int
    avg_place: float
    pick_rate: float
    ban_rate: float
    tier: str
    top_player: ChampTopPlayer | None = None  # reference main; None with no eligible games


class ChampTier(ArenaModel):
    key: ChampTierKey
    label: str
    color: str
    champions: list[ChampRow] = Field(default_factory=list)


class ChampTierlistResponse(ArenaModel):
    updated_at: str
    patch: str
    region: str
    format: str
    metric: str  # top4|first|avgplace|pick|ban
    sample_size: int  # matches sampled
    tiers: list[ChampTier] = Field(default_factory=list)  # S+, S, A, B, C, D
    table: list[ChampRow] = Field(default_factory=list)  # same list, table view


class SynergyChampion(ArenaModel):
    """One champion inside a synergy pair (display fields + gradient fallback)."""

    champion_id: int
    name: str
    champion_icon_url: str | None = None
    colors: AvatarColors


class ChampionSynergy(ArenaModel):
    """A champion duo that shared an Arena subteam, placement-derived (ToS)."""

    champion_a: SynergyChampion
    champion_b: SynergyChampion
    games: int
    win_rate: int  # 0..100 — top-half finishes / games
    first_rate: int  # 0..100 — 1st-place finishes / games
    avg_place: float


class ChampionSynergyResponse(ArenaModel):
    updated_at: str
    season: int
    format: str
    sample_size: int  # total paired subteam-games considered
    min_games: int = 0  # sample floor per pair (transparency: UI states the criterion)
    pairs: list[ChampionSynergy] = Field(default_factory=list)


class ChampionMainsResponse(ArenaModel):
    """Top reference mains for one champion (detail panel)."""

    champion_id: int
    name: str
    champion_icon_url: str | None = None
    players: list[ChampTopPlayer] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Champion build reference (PROVISIONAL — external global aggregate; drops with
# champion_build_ref when native augment ingestion lands)
# ---------------------------------------------------------------------------

BuildTierKey = Literal["S", "A", "B", "C", "D"]


class BuildEntry(ArenaModel):
    """One augment or item in the reference build (placement-derived stats)."""

    id: int
    name: str  # PT-BR display name (CDragon)
    icon_url: str | None = None
    tier: BuildTierKey
    games: int
    avg_place: float
    top1: int  # 0..100 — 1st-place rate with this pick
    top4: int  # 0..100 — top-half rate with this pick
    pick_rate: float  # 0..100


class BuildTeammate(ArenaModel):
    """One reference teammate champion (global aggregate, placement-derived)."""

    champion_id: int
    name: str
    champion_icon_url: str | None = None
    colors: AvatarColors
    tier: BuildTierKey
    games: int
    avg_place: float
    top1: int
    top4: int
    pick_rate: float


class ChampionAugments(ArenaModel):
    """Reference augments grouped by in-game rarity (the three draft rounds)."""

    prismatic: list[BuildEntry] = Field(default_factory=list)
    gold: list[BuildEntry] = Field(default_factory=list)
    silver: list[BuildEntry] = Field(default_factory=list)


class TopBuildResponse(ArenaModel):
    """Global (cross-champion) top augments/items — the /winrate right rail.

    Same GLOBAL external aggregate as the per-champion build; placement-derived
    only. Order = games desc ("em alta"); tier letter = weighted-avg-placement
    bucket; ``pickRate`` = share of the category's games (0..100).
    """

    updated_at: str
    patch: str
    games: int  # total champion-games sampled (0 = no snapshots yet)
    champions: int
    min_games: int  # sample floor per entry
    augments: list[BuildEntry] = Field(default_factory=list)
    items: list[BuildEntry] = Field(default_factory=list)


class ChampionBuildResponse(ArenaModel):
    """Categorized reference build for one champion.

    GLOBAL patch aggregate (external reference snapshot), not our BR ladder —
    the UI must label it as such. ``games == 0`` means no snapshot exists yet.
    """

    champion_id: int
    name: str
    champion_icon_url: str | None = None
    patch: str  # aggregate's patch ("16.14"); "" with no snapshot
    updated_at: str  # snapshot date ("2026-07-19"); "" with no snapshot
    games: int  # champion's global sample in the aggregate
    avg_place: float
    tier: BuildTierKey | None = None  # None with no snapshot
    top1: int
    top4: int
    min_games: int  # sample floor per entry (transparency: UI states the criterion)
    augments: ChampionAugments = Field(default_factory=ChampionAugments)
    items: list[BuildEntry] = Field(default_factory=list)
    boots: list[BuildEntry] = Field(default_factory=list)
    teammates: list[BuildTeammate] = Field(default_factory=list)
