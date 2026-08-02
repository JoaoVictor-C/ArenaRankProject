"""Arena match parsing — Riot match-v5 payload -> normalized Arena result.

Arena is an 8-team mode. Riot exposes two sub-formats via ``queueId``:

- ``1700`` — "2v2v2v2v2v2v2v2": 8 teams of 2 (our **DUOS**, 16 players).
- ``1750`` — Arena 3v3 (6 teams of 3): 6 teams of 3 (our **TRIOS**, 18 players).

Each participant carries a ``placement`` (Riot also calls it
``subteamPlacement``): 1 = first place subteam, 2 = second, ... Tied subteams
share a placement. We expose placement per team so the rating engine ranks all
8 (or 6) subteams in one Plackett-Luce update.

Eligibility gate: a participant only moves rating if
``eligibleForProgression`` holds. Riot does not send that field directly, so we
derive it from AFK / early-surrender / game-too-short signals
(``gameEndedInEarlySurrender``, ``timePlayed``, ``placement`` sanity). The
integrity layer may later veto, but this is the transport-level gate.

Outputs use this package's own dataclasses; the service layer maps them onto
``arena.rating.MatchInput``. We never surface raw Riot fields, mu/sigma, or item
winrate from here — only structural facts (placements, champion ids, teams,
augment/item PICKS). The picks themselves are fine to capture (they're what
backs the placement-derived ``champion_build_stats`` rollup downstream); the
ToS line is never exposing an augment/item *winrate*, same posture as
everywhere else this data surfaces.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Riot Arena queue ids. Riot mints a NEW queue id for each Arena iteration
# (1700 -> 1710 -> ...), so this list grows over patches. To avoid silently
# dropping a whole season the next time that happens, ``_resolve_mode`` ALSO
# accepts any unlisted id whose ``gameMode`` is CHERRY (Riot's Arena mode),
# inferring the format from the actual subteam size.
ARENA_QUEUE_DUOS = 1700  # 8 teams x 2 players (original Arena)
ARENA_QUEUE_DUOS_S2 = 1710  # 8 teams x 2 players (later Arena patch; same shape)
ARENA_QUEUE_TRIOS = 1750  # 6 teams x 3 players
ARENA_QUEUE_TRIOS_BRAVURA = 1740  # 6 teams x 3 players ("Arena 3v3 Bravura", live 2026-07)

# Riot's ``gameMode`` value for every Arena queue, regardless of queue id.
ARENA_GAME_MODE = "CHERRY"

# Minimum seconds a game must last to count (guards against remakes/aborts).
MIN_PLAYED_SECONDS = 90


class ArenaMode(str, Enum):
    """Normalized Arena format, mapped to the rating engine's ``mode`` strings."""

    DUOS = "DUOS"  # 8 teams x 2 (queueId 1700 / 1710)
    TRIOS = "TRIOS"  # 6 teams x 3 (queueId 1740 "Bravura" / 1750)


_QUEUE_TO_MODE: dict[int, ArenaMode] = {
    ARENA_QUEUE_DUOS: ArenaMode.DUOS,
    ARENA_QUEUE_DUOS_S2: ArenaMode.DUOS,
    ARENA_QUEUE_TRIOS: ArenaMode.TRIOS,
    ARENA_QUEUE_TRIOS_BRAVURA: ArenaMode.TRIOS,
}

# Expected team count + size per mode (used to validate payload completeness).
_MODE_SHAPE: dict[ArenaMode, tuple[int, int]] = {
    ArenaMode.DUOS: (8, 2),
    ArenaMode.TRIOS: (6, 3),
}

#: Single source of truth for "which queue ids are Arena". The ingestion worker
#: filter and the backfill discovery import THIS so they never drift from the
#: parser again (the 1710 bug was three copies of this list disagreeing).
ARENA_QUEUE_IDS: frozenset[int] = frozenset(_QUEUE_TO_MODE)


class NotAnArenaMatch(ValueError):
    """Raised when a payload is not a recognized Arena match (queue id + gameMode)."""


@dataclass(slots=True)
class ParsedParticipant:
    puuid: str
    riot_id_game_name: str
    riot_id_tagline: str
    champion_id: int
    placement: int  # subteam placement, 1 = best
    subteam_id: int  # Riot ``playerSubteamId`` (1..8 / 1..6)
    eligible_for_progression: bool
    # Data Dragon (ddragon) summoner profile icon id (match-v5 ``profileIcon``).
    # 0 = unknown/missing; surfaced so registration can persist it for the UI.
    profile_icon: int = 0
    # Diagnostics retained for the integrity layer; never UI-exposed.
    time_played: int = 0
    game_ended_in_early_surrender: bool = False
    # Augment picks, draft order (``playerAugment1..6``), 0/missing slots
    # dropped. Usually 4, but an augment-granting effect (e.g. "Transmutar:
    # Caos") can push a 5th/6th real pick into the array — never assume a
    # fixed length. Final items (``item0..6``), 0 (empty slot) dropped.
    augments: list[int] = field(default_factory=list)
    items: list[int] = field(default_factory=list)
    # Combat telemetry (raw Riot primitives; ``kill_participation``/
    # ``damage_per_minute`` are DERIVED downstream from these + subteam
    # grouping, never captured here — see arena/api/routers/match.py). Several
    # Riot participant fields are structurally meaningless in Arena (no lanes,
    # no vision, no map objectives, fixed summoner spells for everyone) and are
    # deliberately NOT captured — see the combat-telemetry plan for the full
    # in/out list.
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    damage_to_champions: int = 0
    gold_earned: int = 0
    champion_level: int = 0
    damage_taken: int = 0
    total_heal: int = 0
    damage_self_mitigated: int = 0
    largest_multi_kill: int = 0
    killing_sprees: int = 0
    time_spent_dead: int = 0


@dataclass(slots=True)
class ParsedSubteam:
    subteam_id: int
    placement: int
    participants: list[ParsedParticipant] = field(default_factory=list)


@dataclass(slots=True)
class ParsedArenaMatch:
    match_id: str
    queue_id: int
    mode: ArenaMode
    game_duration: int
    # Real match start (epoch ms, from Riot ``gameStartTimestamp``). 0 when the
    # payload omits it. The ingestion path must use this as ``played_at`` — NOT
    # the processing clock — or every backfilled match collapses onto the same
    # instant, which breaks delta7d / chronological ordering.
    started_at_ms: int = 0
    subteams: list[ParsedSubteam] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """True when the team count + sizes match the mode's expected shape."""
        teams, size = _MODE_SHAPE[self.mode]
        if len(self.subteams) != teams:
            return False
        return all(len(t.participants) == size for t in self.subteams)


def is_arena_queue(queue_id: int) -> bool:
    return queue_id in _QUEUE_TO_MODE


def mode_for_queue(queue_id: int) -> ArenaMode:
    try:
        return _QUEUE_TO_MODE[queue_id]
    except KeyError as exc:
        raise NotAnArenaMatch(f"queueId {queue_id} is not an Arena queue") from exc


def _resolve_mode(info: dict[str, Any]) -> ArenaMode:
    """Arena mode for a match-v5 ``info`` block.

    Known queue ids map directly. An *unknown* id is still accepted when the
    match's ``gameMode`` is CHERRY (Riot's Arena mode), inferring the format from
    the dominant subteam size — so a brand-new Arena queue id (the next 1710)
    never again silently drops an entire season of matches.
    """
    queue_id = int(info.get("queueId", -1))
    known = _QUEUE_TO_MODE.get(queue_id)
    if known is not None:
        return known
    if str(info.get("gameMode", "")).upper() == ARENA_GAME_MODE:
        per_team = Counter(int(p.get("playerSubteamId", 0)) for p in info.get("participants", []))
        if per_team:
            team_size = Counter(per_team.values()).most_common(1)[0][0]
            for mode, (_teams, size) in _MODE_SHAPE.items():
                if size == team_size:
                    return mode
    raise NotAnArenaMatch(
        f"queueId {queue_id} (gameMode={info.get('gameMode')!r}) is not a recognized Arena queue"
    )


def _picked_ints(p: dict[str, Any], prefix: str, slots: range) -> list[int]:
    """Non-zero ``{prefix}{n}`` values across ``slots``, draft/slot order kept.

    Riot pads unused augment/item slots with ``0`` rather than omitting the
    key — ``playerAugment5``/``6`` are ``0`` on a normal 4-pick game, ``item5``
    is ``0`` on an empty inventory slot. Keeping order (not sorting/deduping)
    matters for augments: a genuine augment-granting effect can repeat an id.
    """
    out: list[int] = []
    for n in slots:
        try:
            v = int(p.get(f"{prefix}{n}", 0) or 0)
        except (TypeError, ValueError):
            continue
        if v > 0:
            out.append(v)
    return out


#: Automatically-equipped Arena trinket(s) — present in ~every game regardless
#: of player choice, not a real build decision. Excluded from capture so
#: champion_build_stats / per-match item displays stay meaningful instead of
#: always showing a ~100%-pick-rate item nobody actually chose.
_EXCLUDED_ITEM_IDS = frozenset({3348})  # "Analisador Arcano" / Arcane Sweeper


def _derive_eligibility(p: dict[str, Any], game_duration: int) -> bool:
    """Transport-level ``eligibleForProgression`` gate.

    A participant is ineligible (no rating movement) when the game was too short,
    ended in an early surrender, or the placement is missing/invalid (AFK fills
    routinely surface as placement 0/None upstream).
    """
    if game_duration < MIN_PLAYED_SECONDS:
        return False
    if bool(p.get("gameEndedInEarlySurrender")):
        return False
    # Riot sends ``placement`` and/or ``subteamPlacement``; accept either.
    placement = p.get("subteamPlacement", p.get("placement"))
    if not isinstance(placement, int) or placement < 1:
        return False
    # A long-disconnect heuristic: credited time well below game length.
    time_played = p.get("timePlayed")
    if isinstance(time_played, int) and time_played < MIN_PLAYED_SECONDS:
        return False
    return True


def parse_arena_match(payload: dict[str, Any]) -> ParsedArenaMatch:
    """Parse a match-v5 payload into a normalized Arena result.

    Raises :class:`NotAnArenaMatch` for non-Arena queues. Subteams are grouped by
    ``playerSubteamId`` and ordered by placement (best first). Placement uses
    Riot's ``subteamPlacement`` when present, falling back to ``placement``.
    """
    info = payload.get("info", {})
    metadata = payload.get("metadata", {})
    queue_id = int(info.get("queueId", -1))
    mode = _resolve_mode(info)
    match_id = str(metadata.get("matchId", info.get("gameId", "")))
    game_duration = int(info.get("gameDuration", 0))
    # Real start instant: prefer gameStartTimestamp, then gameCreation, then
    # back-compute from gameEndTimestamp - duration. 0 if none present.
    started_at_ms = int(info.get("gameStartTimestamp") or info.get("gameCreation") or 0)
    if not started_at_ms:
        end_ms = int(info.get("gameEndTimestamp", 0) or 0)
        if end_ms:
            started_at_ms = end_ms - game_duration * 1000

    subteams: dict[int, ParsedSubteam] = {}
    for p in info.get("participants", []):
        subteam_id = int(p.get("playerSubteamId", 0))
        placement = int(p.get("subteamPlacement", p.get("placement", 0)) or 0)
        participant = ParsedParticipant(
            puuid=str(p.get("puuid", "")),
            riot_id_game_name=str(p.get("riotIdGameName", "")),
            riot_id_tagline=str(p.get("riotIdTagline", "")),
            champion_id=int(p.get("championId", 0)),
            placement=placement,
            subteam_id=subteam_id,
            eligible_for_progression=_derive_eligibility(p, game_duration),
            profile_icon=int(p.get("profileIcon", 0) or 0),
            time_played=int(p.get("timePlayed", 0) or 0),
            game_ended_in_early_surrender=bool(p.get("gameEndedInEarlySurrender", False)),
            augments=_picked_ints(p, "playerAugment", range(1, 7)),
            items=[
                i
                for i in _picked_ints(p, "item", range(0, 7))
                if i not in _EXCLUDED_ITEM_IDS
            ],
            kills=int(p.get("kills", 0) or 0),
            deaths=int(p.get("deaths", 0) or 0),
            assists=int(p.get("assists", 0) or 0),
            damage_to_champions=int(p.get("totalDamageDealtToChampions", 0) or 0),
            gold_earned=int(p.get("goldEarned", 0) or 0),
            champion_level=int(p.get("champLevel", 0) or 0),
            damage_taken=int(p.get("totalDamageTaken", 0) or 0),
            total_heal=int(p.get("totalHeal", 0) or 0),
            damage_self_mitigated=int(p.get("damageSelfMitigated", 0) or 0),
            largest_multi_kill=int(p.get("largestMultiKill", 0) or 0),
            killing_sprees=int(p.get("killingSprees", 0) or 0),
            time_spent_dead=int(p.get("totalTimeSpentDead", 0) or 0),
        )
        team = subteams.get(subteam_id)
        if team is None:
            team = ParsedSubteam(subteam_id=subteam_id, placement=placement)
            subteams[subteam_id] = team
        team.participants.append(participant)
        # Subteam placement is uniform across its members; trust the first seen
        # positive value.
        if team.placement < 1 and placement >= 1:
            team.placement = placement

    ordered = sorted(subteams.values(), key=lambda t: (t.placement <= 0, t.placement))
    return ParsedArenaMatch(
        match_id=match_id,
        queue_id=queue_id,
        mode=mode,
        game_duration=game_duration,
        started_at_ms=started_at_ms,
        subteams=ordered,
    )


# ---------------------------------------------------------------------------
# Codec de persistência (match_backlog)
#
# Um refill estaciona a partida JÁ PARSEADA em vez do payload cru da match-v5:
# ~2,5 kB contra ~75 kB, e a drenagem não precisa voltar à Riot (o cache de
# payload dura 24 h — curto demais para uma janela de 20 dias). O ida-e-volta
# tem de ser EXATO: o que sai de ``parsed_from_json`` alimenta exatamente o
# mesmo caminho de escrita que uma partida ao vivo.
# ---------------------------------------------------------------------------


def parsed_to_json(parsed: ParsedArenaMatch) -> dict[str, Any]:
    """``ParsedArenaMatch`` -> dict JSON-serializável (coluna JSONB)."""
    return {
        "matchId": parsed.match_id,
        "queueId": parsed.queue_id,
        "mode": parsed.mode.value,
        "gameDuration": parsed.game_duration,
        "startedAtMs": parsed.started_at_ms,
        "subteams": [
            {
                "subteamId": t.subteam_id,
                "placement": t.placement,
                "participants": [
                    {
                        "puuid": p.puuid,
                        "gameName": p.riot_id_game_name,
                        "tagLine": p.riot_id_tagline,
                        "championId": p.champion_id,
                        "placement": p.placement,
                        "subteamId": p.subteam_id,
                        "eligible": p.eligible_for_progression,
                        "profileIcon": p.profile_icon,
                        "timePlayed": p.time_played,
                        "earlySurrender": p.game_ended_in_early_surrender,
                        "augments": p.augments,
                        "items": p.items,
                        "kills": p.kills,
                        "deaths": p.deaths,
                        "assists": p.assists,
                        "damageToChampions": p.damage_to_champions,
                        "goldEarned": p.gold_earned,
                        "championLevel": p.champion_level,
                        "damageTaken": p.damage_taken,
                        "totalHeal": p.total_heal,
                        "damageSelfMitigated": p.damage_self_mitigated,
                        "largestMultiKill": p.largest_multi_kill,
                        "killingSprees": p.killing_sprees,
                        "timeSpentDead": p.time_spent_dead,
                    }
                    for p in t.participants
                ],
            }
            for t in parsed.subteams
        ],
    }


def parsed_from_json(data: dict[str, Any]) -> ParsedArenaMatch:
    """Inverso de :func:`parsed_to_json`. Preserva a ordem dos subteams."""
    return ParsedArenaMatch(
        match_id=str(data["matchId"]),
        queue_id=int(data["queueId"]),
        mode=ArenaMode(data["mode"]),
        game_duration=int(data["gameDuration"]),
        started_at_ms=int(data.get("startedAtMs", 0)),
        subteams=[
            ParsedSubteam(
                subteam_id=int(t["subteamId"]),
                placement=int(t["placement"]),
                participants=[
                    ParsedParticipant(
                        puuid=str(p["puuid"]),
                        riot_id_game_name=str(p.get("gameName", "")),
                        riot_id_tagline=str(p.get("tagLine", "")),
                        champion_id=int(p["championId"]),
                        placement=int(p["placement"]),
                        subteam_id=int(p["subteamId"]),
                        eligible_for_progression=bool(p["eligible"]),
                        profile_icon=int(p.get("profileIcon", 0)),
                        time_played=int(p.get("timePlayed", 0)),
                        game_ended_in_early_surrender=bool(p.get("earlySurrender", False)),
                        augments=[int(a) for a in p.get("augments", [])],
                        items=[int(i) for i in p.get("items", [])],
                        kills=int(p.get("kills", 0)),
                        deaths=int(p.get("deaths", 0)),
                        assists=int(p.get("assists", 0)),
                        damage_to_champions=int(p.get("damageToChampions", 0)),
                        gold_earned=int(p.get("goldEarned", 0)),
                        champion_level=int(p.get("championLevel", 0)),
                        damage_taken=int(p.get("damageTaken", 0)),
                        total_heal=int(p.get("totalHeal", 0)),
                        damage_self_mitigated=int(p.get("damageSelfMitigated", 0)),
                        largest_multi_kill=int(p.get("largestMultiKill", 0)),
                        killing_sprees=int(p.get("killingSprees", 0)),
                        time_spent_dead=int(p.get("timeSpentDead", 0)),
                    )
                    for p in t["participants"]
                ],
            )
            for t in data["subteams"]
        ],
    )
