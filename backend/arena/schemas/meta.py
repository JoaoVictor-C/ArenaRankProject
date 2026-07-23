"""Contract §7 — GET /api/v1/meta/* response DTOs (last-update, activity, records)."""

from __future__ import annotations

from pydantic import Field

from arena.schemas.common import ArenaModel, AvatarColors


class LastUpdateGlobal(ArenaModel):
    last_ts: str
    cycle_sec: int  # full-ranking cycle (~1h)
    eta_sec: int


class LastUpdateTier(ArenaModel):
    rank: int
    label: str
    cadence_sec: int  # 5min if top-1000, 1h otherwise
    eta_sec: int


class LastUpdate(ArenaModel):
    global_: LastUpdateGlobal  # serializes as "global" (Python keyword guard)
    tier: LastUpdateTier


# -- GET /meta/activity — ranked matches processed per day (rail chart) --------
class ActivityDay(ArenaModel):
    label: str  # day-of-month, e.g. "18"
    count: int  # ranked matches processed that day


class ActivityResponse(ArenaModel):
    days: list[ActivityDay] = Field(default_factory=list)
    max: int = 0  # max count across days (chart scaling); 0 when no data


# -- GET /meta/records — season highlight records (rail rotating card) ---------
class SeasonRecord(ArenaModel):
    key: str  # stable id: streak | first_rate | top4_rate | biggest_gain | most_today
    label: str  # PT-BR display label
    value: str  # formatted value ("14", "42%", "+72")
    name: str  # player display name ("" when no data yet)
    handle: str  # "#TAG"
    avatar: AvatarColors  # gradient fallback (used until the icon art loads)
    profile_icon_url: str | None = None  # real ddragon summoner icon; None → gradient
    accent: str  # accent color hint for the UI


class RecordsResponse(ArenaModel):
    records: list[SeasonRecord] = Field(default_factory=list)
