"""Contract §1 — GET /api/v1/leaderboard response DTOs.

camelCase wire format; ``cr`` is the gamified display rating (never mu/sigma).
"""

from __future__ import annotations

from pydantic import Field

from arena.schemas.common import ArenaModel, AvatarColors, PlayerTag, TierKey


class LeaderboardChampion(ArenaModel):
    """Per-champion mini-stats for a player's main (podium hover card).

    Placement-derived from ``champion_stats`` for the row's ``(player, season)``.
    Parallels ``LeaderboardRow.champions`` / ``champion_icon_urls`` by index.
    """

    champion_id: int
    name: str
    icon_url: str | None = None
    games: int
    winrate: int  # 0..100 (wins / games)
    top_half: int  # 0..100 (top-half finishes / games)
    avg_place: float  # média de colocação (1 casa)


class LeaderboardRow(ArenaModel):
    rank: int  # 1-based, within scope
    riot_id: str  # "Nome#TAG"
    name: str  # part before the #
    handle: str  # "#TAG"
    avatar: AvatarColors
    # ddragon (v1.1): real summoner profile-icon URL when the player's icon id is
    # known; ``None`` → frontend keeps the ``avatar`` gradient fallback.
    profile_icon_url: str | None = None
    cr: int  # CR / Pontos
    delta7d: int  # signed CR change over 7d; 0 = stable
    wins: int
    losses: int
    winrate: int  # 0..100
    top4: int  # 0..100 (% top-4)
    top1: int = 0  # 0..100 (% de 1º lugar — placement==1)
    top1_streak: int = 0  # consecutive 1st-place finishes from latest match; >=3 → "on fire"
    tier: TierKey
    tags: list[PlayerTag] = Field(default_factory=list)
    in_game: bool | None = None  # only relevant for podium
    champions: list[AvatarColors] = Field(default_factory=list)  # up to 4 mains
    # ddragon (v1.1): real champion-square icon URLs (parallels ``champions``);
    # empty → frontend keeps the gradient placeholders.
    champion_icon_urls: list[str] = Field(default_factory=list)
    # Per-champion mini-stats (same order/index as ``champions``) — powers the
    # podium hover card. Empty when the player has no eligible champion games.
    champions_stats: list[LeaderboardChampion] = Field(default_factory=list)


class LeaderboardResponse(ArenaModel):
    updated_at: str  # ISO; last global update
    total: int  # total ranked players in scope
    season: int
    format: str
    rows: list[LeaderboardRow] = Field(default_factory=list)
