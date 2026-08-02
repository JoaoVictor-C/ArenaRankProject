"""Contract §3 — GET /api/v1/match/{matchId} response DTOs.

Arena 3v3 = 6 subteams of 3 (placement 1..6); 2v2 = 8 of 2 (1..8).
"""

from __future__ import annotations

from pydantic import Field

from arena.schemas.common import ArenaModel, AvatarColors, Modifier, Severity


class MatchIntegrityFlag(ArenaModel):
    kind: Severity
    label: str


class MatchLoadoutEntry(ArenaModel):
    """One resolved item/augment (name+icon, never a bare id) — CDragon display."""

    id: int
    name: str
    icon_url: str | None = None
    # Item shop total cost (CDragon `priceTotal`) — always ``None`` for
    # augments, which have no gold cost (draft picks, not purchases).
    gold: int | None = None
    description: str | None = None


class MatchAugmentEntry(MatchLoadoutEntry):
    rarity: str  # "prismatic" | "gold" | "silver" | "unique" | "unknown"


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
    # Native picks (v1.2) — resolved from the participant's captured Riot
    # payload, never fabricated. Empty list, not None, when nothing was
    # captured (pre-migration rows) — the UI degrades on absence, not on shape.
    items: list[MatchLoadoutEntry] = Field(default_factory=list)
    augments: list[MatchAugmentEntry] = Field(default_factory=list)
    # Combat telemetry (v1.3) — raw Riot primitives, ``None`` (not 0) when the
    # participant predates this capture; the frontend's own CombatStats
    # contract already treats absence, not a fake zero, as "aguardando
    # ingestão". kill_participation/damage_per_minute are DERIVED at read time
    # (arena/api/routers/match.py) from these + subteam grouping — Riot's own
    # challenges.killParticipation uses the wrong (legacy 2-bucket teamId)
    # grouping for Arena and must never be trusted here.
    level: int | None = None
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    damage_to_champions: int | None = None
    gold_earned: int | None = None
    kill_participation: int | None = None
    damage_per_minute: int | None = None
    # Extras (v1.3) — no frontend consumer yet, captured now (during the same
    # Riot re-fetch as the fields above) so a future UI addition needs zero
    # backend work / no second historical re-fetch.
    damage_taken: int | None = None
    total_heal: int | None = None
    damage_self_mitigated: int | None = None
    largest_multi_kill: int | None = None
    killing_sprees: int | None = None
    time_spent_dead: int | None = None


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
