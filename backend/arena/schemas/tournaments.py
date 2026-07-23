"""Contract §5 (+5a..5e-bis) — tournaments DTOs and request bodies.

Mirrors ``frontend/src/lib/types.ts`` (superset of the contract markdown: includes
the optional currency / entry / conduct / prizeSplit fields the frontend consumes).

Persisted subsystem; ``compute_standings`` is the scoring source of truth. These
schemas are RESPONSE DTOs plus the request bodies for the tournament POST endpoints.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from arena.schemas.common import ArenaModel, AvatarColors, Format, arena_camel

BannerTone = Literal["b1", "b2", "b3", "b4"]
TournamentStatus = Literal["upcoming", "live", "ended"]
MatchStatus = Literal["ended", "live", "upcoming"]
Medal = Literal["gold", "silver", "bronze", "none"]
Currency = Literal["BRL", "RP"]


# ---- player slot (real | empty) ----


class PlayerSlotFilled(ArenaModel):
    name: str
    handle: str
    riot_id: str
    avatar: AvatarColors


class PlayerSlotEmpty(ArenaModel):
    # forbid extras so a filled slot never validates as empty under the union
    model_config = ConfigDict(
        alias_generator=arena_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )

    empty: Literal[True] = True


# Slot is real (filled) or vacant ({empty:true}). Try the richer "filled" shape
# first; fall back to the strict "empty" shape (which forbids the filled keys).
PlayerSlot = Annotated[
    PlayerSlotFilled | PlayerSlotEmpty,
    Field(union_mode="left_to_right"),
]


# ---- scoring / rules value objects ----


class ScoringEntry(ArenaModel):
    place: int
    points: int


class PrizeSplitEntry(ArenaModel):
    place: int
    pct: float


class ConductEntry(ArenaModel):
    icon: str
    title: str
    desc: str


class TournamentEntry(ArenaModel):
    fee: str | None = None
    pix: str | None = None


class TournamentRules(ArenaModel):
    format: list[str] = Field(default_factory=list)
    scoring: list[ScoringEntry] = Field(default_factory=list)
    tiebreak: list[str] = Field(default_factory=list)
    currency: str | None = None
    conduct: list[ConductEntry] | None = None
    entry: TournamentEntry | None = None
    schedule: str | None = None
    prize_note: str | None = None


# ---- list / detail ----


class TournamentListItem(ArenaModel):
    id: str
    title: str
    format: str
    starts_at: str
    teams: int
    prize_rp: int
    banner_tone: BannerTone
    tag: str
    amount_label: str
    when_label: str


class TournamentMatchResultEntry(ArenaModel):
    team_id: str
    placement: int
    bravura: int


class TournamentMatch(ArenaModel):
    n: int
    status: MatchStatus
    winner_team_id: str | None = None
    starts_at: str | None = None
    lobby_max: int
    lobby_count: int
    magnetic_link: str
    result: list[TournamentMatchResultEntry] | None = None


class StandingRow(ArenaModel):
    team_id: str
    seed: int
    team_name: str
    players: list[PlayerSlot] = Field(default_factory=list)
    per_match: list[int] = Field(default_factory=list)  # only ended matches
    penalties: int
    bonus: int
    total: int
    is_you: bool | None = None


class TeamRoster(ArenaModel):
    team_id: str
    team_name: str
    seed: int
    captain: str
    is_you: bool | None = None
    players: list[PlayerSlot] = Field(default_factory=list)


class PrizeRow(ArenaModel):
    place: int
    rp: int
    per_player: int
    medal: Medal


class TournamentMatchResultRow(ArenaModel):
    team_name: str
    points: int
    place: int


class TournamentMatchResult(ArenaModel):
    n: int
    status: MatchStatus
    results: list[TournamentMatchResultRow] = Field(default_factory=list)


class TournamentDetail(ArenaModel):
    id: str
    title: str
    format: str
    prize_rp: int
    prize_label: str
    currency: str | None = None  # "BRL" | "RP"
    status: TournamentStatus
    current_match: int  # 1..3
    matches: list[TournamentMatch] = Field(default_factory=list)
    standings: list[StandingRow] = Field(default_factory=list)
    rules: TournamentRules
    prizes: list[PrizeRow] = Field(default_factory=list)
    registrations: list[TeamRoster] = Field(default_factory=list)
    history: list[TournamentMatchResult] = Field(default_factory=list)
    access_key: str | None = None  # only present in Admin responses


# ---- request bodies ----


class TournamentCreate(ArenaModel):
    """POST /api/v1/admin/tournaments body → 201 TournamentDetail."""

    title: str = Field(min_length=2, max_length=80)
    format: Format = "3v3"
    num_teams: int = Field(default=6, ge=2, le=16)
    num_matches: int = Field(default=3, ge=1, le=10)
    prize_rp: int = Field(default=5000, ge=0)
    starts_at: str | None = None
    banner_tone: BannerTone | None = None
    tag: str | None = None
    scoring: list[ScoringEntry] | None = None  # absent → default (1º=numTeams..último=1)
    currency: Currency | None = None
    entry_fee: float | None = None
    pix_info: str | None = None
    schedule: str | None = None
    prize_note: str | None = None
    prize_split: list[PrizeSplitEntry] | None = None
    conduct: list[ConductEntry] | None = None
    tiebreak: list[str] | None = None
    format_lines: list[str] | None = None
    access_key: str | None = None  # if omitted → backend generates ARENA-XXXXXX


# §5a-bis — POST /tournament/{id}/access
class AccessRequest(ArenaModel):
    key: str


class AccessTeamSlot(ArenaModel):
    team_id: str
    team_name: str
    open_slots: int


class AccessResponse(ArenaModel):
    tournament_id: str
    teams: list[AccessTeamSlot] = Field(default_factory=list)


# §5b-bis — POST /tournament/{id}/team
class CreateTeamRequest(ArenaModel):
    key: str
    team_name: str
    riot_id: str


class CreateTeamResponse(ArenaModel):
    team_id: str


# §5c-bis — POST /tournament/{id}/join
class JoinTeamRequest(ArenaModel):
    key: str
    team_id: str
    riot_id: str


class JoinTeamResponse(ArenaModel):
    team_id: str


# §5d-bis — POST /admin/tournament/{id}/match/{n}/link
class SetMatchLinkRequest(ArenaModel):
    magnetic_link: str
    status: MatchStatus


# §5e-bis — POST /admin/tournament/{id}/match/{n}/result
class ResultPenalty(ArenaModel):
    team_id: str
    value: int


class SubmitResultRequest(ArenaModel):
    results: list[TournamentMatchResultEntry] = Field(default_factory=list)
    penalties: list[ResultPenalty] | None = None
