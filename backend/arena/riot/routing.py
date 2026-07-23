"""Riot API host routing + URL builders.

Riot splits its API across two host families:

- **Regional routing** (``americas`` / ``europe`` / ``asia``) — used by
  ``account-v1`` and ``match-v5``. We default to ``americas`` because Arena is
  launching for BR/LAN/LAS/NA, all of which route to AMERICAS.
- **Platform routing** (``br1`` / ``na1`` / ``euw1`` / ...) — used by the
  per-shard endpoints (summoner-v4, league-v4). Kept here for completeness even
  though the Arena client only needs the regional endpoints today.

All path segments are percent-encoded; query params are appended explicitly.
"""

from __future__ import annotations

from enum import Enum
from urllib.parse import quote


class Region(str, Enum):
    """Regional routing value for account-v1 / match-v5."""

    AMERICAS = "americas"
    EUROPE = "europe"
    ASIA = "asia"
    SEA = "sea"

    @property
    def host(self) -> str:
        return f"https://{self.value}.api.riotgames.com"


class Platform(str, Enum):
    """Platform (shard) routing value for per-shard endpoints."""

    BR1 = "br1"
    NA1 = "na1"
    LA1 = "la1"
    LA2 = "la2"
    EUW1 = "euw1"
    EUN1 = "eun1"
    KR = "kr"

    @property
    def host(self) -> str:
        return f"https://{self.value}.api.riotgames.com"

    @property
    def region(self) -> Region:
        """The regional routing value this platform maps to."""
        return _PLATFORM_TO_REGION[self]


_PLATFORM_TO_REGION: dict[Platform, Region] = {
    Platform.BR1: Region.AMERICAS,
    Platform.NA1: Region.AMERICAS,
    Platform.LA1: Region.AMERICAS,
    Platform.LA2: Region.AMERICAS,
    Platform.EUW1: Region.EUROPE,
    Platform.EUN1: Region.EUROPE,
    Platform.KR: Region.ASIA,
}


def account_by_riot_id_url(game_name: str, tag_line: str, region: Region) -> str:
    gn = quote(game_name, safe="")
    tl = quote(tag_line, safe="")
    return f"{region.host}/riot/account/v1/accounts/by-riot-id/{gn}/{tl}"


def match_ids_by_puuid_url(
    puuid: str,
    region: Region,
    *,
    start: int = 0,
    count: int = 20,
    queue: int | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
) -> str:
    pu = quote(puuid, safe="")
    params = [f"start={start}", f"count={count}"]
    if queue is not None:
        params.append(f"queue={queue}")
    if start_time is not None:
        params.append(f"startTime={start_time}")
    if end_time is not None:
        params.append(f"endTime={end_time}")
    qs = "&".join(params)
    return f"{region.host}/lol/match/v5/matches/by-puuid/{pu}/ids?{qs}"


def match_detail_url(match_id: str, region: Region) -> str:
    mid = quote(match_id, safe="")
    return f"{region.host}/lol/match/v5/matches/{mid}"
