"""Contract §2 — GET /api/v1/player/{riotId} response DTOs."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from arena.schemas.common import ArenaModel, AvatarColors, Modifier, PlayerTag, TierKey


class FormDot(ArenaModel):
    place: int  # placement 1..6 / 1..8


class CrHistoryPoint(ArenaModel):
    ts: str
    cr: int
    lo: int  # lower bound of uncertainty band (CR-space, not sigma)
    hi: int  # upper bound


class PlayerMatch(ArenaModel):
    match_id: str
    ts: str
    champion: AvatarColors
    champion_name: str
    # ddragon (v1.1): real champion-square icon URL; ``None`` → gradient fallback.
    champion_icon_url: str | None = None
    place: int
    cr_delta: int
    modifiers: list[Modifier] = Field(default_factory=list)


class PlayerMatchRich(PlayerMatch):
    """PlayerMatch + campos do detalhe (histórico dedicado, contract §2-bis)."""

    cr_before: int
    cr_after: int
    format: str  # "3v3" | "2v2"
    team_count: int  # 6 (3v3) | 8 (2v2)
    duration_sec: int
    premade: bool


class ChampFacet(ArenaModel):
    """Faceta de campeão do histórico (para filtro no cliente)."""

    champion_id: int
    name: str
    champion: AvatarColors
    champion_icon_url: str | None = None
    games: int


class MatchesSummary(ArenaModel):
    """Agregados sobre o conjunto FILTRADO inteiro (não só a página)."""

    games: int
    first_rate: int  # % 1º lugar
    top4: int  # % top-metade
    avg_place: float
    cr_sum: int  # soma de crDelta do conjunto
    placements: list[int] = Field(default_factory=list)  # contagens por colocação, índice 0 → 1º


class PlayerMatchesResponse(ArenaModel):
    """Contract §2-bis — GET /api/v1/player/{riotId}/matches (paginado)."""

    total: int
    offset: int
    limit: int
    summary: MatchesSummary
    champions_facet: list[ChampFacet] = Field(default_factory=list)
    matches: list[PlayerMatchRich] = Field(default_factory=list)


class ChampStat(ArenaModel):
    champion: AvatarColors
    name: str
    # ddragon (v1.1): real champion-square icon URL; ``None`` → gradient fallback.
    champion_icon_url: str | None = None
    games: int
    first_rate: int  # % first place
    top4: int  # % top-4
    avg_place: float
    cr_impact: int  # net CR contribution
    spark: list[int] = Field(default_factory=list)  # sparkline series


class H2HPlayerRef(ArenaModel):
    name: str
    handle: str
    avatar: AvatarColors


class H2HRow(ArenaModel):
    player: H2HPlayerRef
    games: int
    winrate: int
    synergy: Literal["duo", "rival"]


class SeasonArchive(ArenaModel):
    season: int
    peak_cr: int
    final_rank: int
    tier: TierKey


class PlayerProfile(ArenaModel):
    riot_id: str
    name: str
    handle: str
    region: str
    avatar: AvatarColors
    # ddragon (v1.1): real summoner profile-icon URL; ``None`` → gradient fallback.
    profile_icon_url: str | None = None
    cr: int
    rank: int
    tier: TierKey
    provisional: bool
    delta7d: int
    wins: int
    losses: int
    winrate: int
    top4: int
    avg_place: float
    form: list[FormDot] = Field(default_factory=list)  # recent ~6 matches
    cr_history: list[CrHistoryPoint] = Field(default_factory=list)
    tags: list[PlayerTag] = Field(default_factory=list)
    matches: list[PlayerMatch] = Field(default_factory=list)
    champions: list[ChampStat] = Field(default_factory=list)
    h2h: list[H2HRow] = Field(default_factory=list)
    seasons: list[SeasonArchive] = Field(default_factory=list)
