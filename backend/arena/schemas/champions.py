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
    # Variação (pontos percentuais) do top-half nos últimos 7d vs os 7d
    # anteriores, do rollup ``champion_daily_stats``. 0 quando não há histórico
    # (rollup vazio) → a UI esconde a seta. Duplo-sinal (seta+cor) no front.
    winrate_delta: int = 0
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


class ChampionSynergyGroup(ArenaModel):
    """A champion subteam (duo or trio) that shared an Arena team, placement-derived.

    Generalizes :class:`ChampionSynergy` from a fixed pair to a ``size``-member
    combo (2 = duo, 3 = trio — Arena teams are 2 or 3). All members share the
    subteam placement, so ``win_rate`` is the combo's top-half rate. ToS: never
    augment/item winrate.
    """

    champions: list[SynergyChampion]  # ordered by championId asc (combo key)
    games: int
    win_rate: int  # 0..100 — top-half finishes / games
    first_rate: int  # 0..100 — 1st-place finishes / games
    avg_place: float


class ChampionSynergyGroupResponse(ArenaModel):
    """Top champion subteams of a given ``size`` (the /winrate rail; duos or trios)."""

    updated_at: str
    season: int
    format: str
    size: int  # subteam size these groups describe (2 duo, 3 trio)
    sample_size: int  # total subteam-games considered
    min_games: int = 0  # sample floor per combo (UI states the criterion)
    groups: list[ChampionSynergyGroup] = Field(default_factory=list)


class SynergyTier(ArenaModel):
    key: ChampTierKey
    label: str
    color: str
    comps: list[ChampionSynergyGroup] = Field(default_factory=list)


class SynergyTierlistResponse(ArenaModel):
    """Synergy comps bucketed S+..D by relative rank — the /sinergias page."""

    updated_at: str
    season: int
    format: str
    size: int  # subteam size (2 duo, 3 trio)
    sample_size: int
    min_games: int = 0
    tiers: list[SynergyTier] = Field(default_factory=list)  # S+, S, A, B, C, D
    table: list[ChampionSynergyGroup] = Field(default_factory=list)  # same list, flat


class ChampionMainsResponse(ArenaModel):
    """Top reference mains for one champion (detail panel)."""

    champion_id: int
    name: str
    champion_icon_url: str | None = None
    players: list[ChampTopPlayer] = Field(default_factory=list)


class ChampionTrendPoint(ArenaModel):
    """One day in a champion's trend (placement-derived; from champion_daily_stats)."""

    date: str  # ISO date "2026-07-20"
    top4: int  # 0..100 — top-half rate that day
    first: int  # 0..100 — 1st-place rate that day
    pick_rate: float  # 0..100 — share of the day's champion-games
    games: int


class ChampionTrendResponse(ArenaModel):
    """A champion's winrate/pick/top4 over the last ``days`` (the champion page charts).

    Empty ``series`` before the rollup has history for this champion → the UI
    degrades the charts. Placement-derived only (ToS)."""

    champion_id: int
    name: str
    champion_icon_url: str | None = None
    days: int
    series: list[ChampionTrendPoint] = Field(default_factory=list)


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
