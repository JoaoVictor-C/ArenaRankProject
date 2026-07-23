"""Contract §3 — GET /api/v1/match/{matchId} response DTOs.

Arena 3v3 = 6 subteams of 3 (placement 1..6); 2v2 = 8 of 2 (1..8).
"""

from __future__ import annotations

from pydantic import Field

from arena.schemas.common import ArenaModel, AvatarColors, Modifier, Severity


class MatchIntegrityFlag(ArenaModel):
    kind: Severity
    label: str


class MatchPlayer(ArenaModel):
    riot_id: str
    name: str
    handle: str
    avatar: AvatarColors
    # ddragon (v1.1): real summoner profile-icon URL; ``None`` → gradient fallback.
    profile_icon_url: str | None = None
    champion: AvatarColors
    champion_name: str
    # ddragon (v1.1): real champion-square icon URL; ``None`` → gradient fallback.
    champion_icon_url: str | None = None
    cr_before: int
    cr_after: int
    cr_delta: int
    modifiers: list[Modifier] = Field(default_factory=list)
    integrity: list[MatchIntegrityFlag] | None = None


class SubTeam(ArenaModel):
    placement: int  # 1..6 (3v3) / 1..8 (2v2)
    players: list[MatchPlayer] = Field(default_factory=list)


class MatchDetail(ArenaModel):
    match_id: str
    format: str
    queue_label: str  # "Arena 3v3"
    played_at: str
    duration_sec: int
    patch: str
    processed_at: str  # processing metadata
    subteams: list[SubTeam] = Field(default_factory=list)  # ordered by placement
