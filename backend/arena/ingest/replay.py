"""Feeds crawled matches through the SAME rating service the online write
path uses, in the one order that's actually correct: real play order.

The crawler yields matches roughly in discovery order (BFS layer by layer),
not chronological order — a later-discovered match can easily have an
earlier ``gameStartTimestamp``. Rating a lobby out of order would corrupt
both the Plackett-Luce mu/sigma trajectory (each match's update depends on
the players' state going INTO it) and the premade/party-tracking heuristics
(they reason about who queued with whom over time). ``replay_chronological``
sorts once by ``started_at_ms`` and replays sequentially through
``rating_service.process_match`` — sequentially on purpose: offline replay
has no concurrent writers to guard against, so it uses ``_noop_lock`` instead
of the online path's real per-player Redis lock.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from arena.core.logging import get_logger
from arena.riot.arena import ParsedArenaMatch
from arena.services.match_pipeline import PremadeIntegrity
from arena.services.protocols import RawMatch, RawParticipant

_log = get_logger("arena.ingest.replay")


@dataclass
class ReplayStats:
    """Running tally returned by :func:`replay_chronological`; grow this
    (not a bare int return) as replay gains more to report."""

    processed: int = 0


def _noop_lock(_ids: Any) -> Any:
    """Stand-in for the online path's per-player Redis lock — replay is
    strictly sequential, so there's never a concurrent writer to guard
    against; `rating_service.process_match` still expects a lock-shaped
    async context manager, so this satisfies that shape without doing
    anything."""

    @asynccontextmanager
    async def cm() -> AsyncIterator[None]:
        yield
    return cm()


async def replay_chronological(
    session: Any, matches: Sequence[ParsedArenaMatch], *,
    season_id: str, party_store: Any, id_map: dict[str, str], rating_service: Any,
) -> ReplayStats:
    """Replay matches through the rating service in true gameStartTimestamp order
    so the premade co-occurrence ramp and Plackett-Luce updates match real history."""
    ordered = sorted(matches, key=lambda p: p.started_at_ms or 0)
    stats = ReplayStats()
    for parsed in ordered:
        # Verify all participant puuids are present in id_map; a match with
        # any missing puuid (e.g. empty puuid skipped by PlayerRegistry) cannot
        # be rated, so skip it entirely rather than crashing with KeyError.
        all_participants = [(st, pp) for st in parsed.subteams for pp in st.participants]
        if any(not pp.puuid or pp.puuid not in id_map for _, pp in all_participants):
            _log.warning("ingest.replay_skip_missing_puuid", match_id=parsed.match_id)
            continue
        ineligible: set[str] = set()
        raw_parts: list[RawParticipant] = []
        for st, pp in all_participants:
            pid = id_map[pp.puuid]
            if not pp.eligible_for_progression:
                ineligible.add(pid)
            raw_parts.append(RawParticipant(
                player_id=pid, champion_id=pp.champion_id,
                team_id=st.subteam_id, placement=st.placement,
                augments=pp.augments, items=pp.items,
                kills=pp.kills, deaths=pp.deaths, assists=pp.assists,
                damage_to_champions=pp.damage_to_champions, gold_earned=pp.gold_earned,
                champion_level=pp.champion_level, damage_taken=pp.damage_taken,
                total_heal=pp.total_heal, damage_self_mitigated=pp.damage_self_mitigated,
                largest_multi_kill=pp.largest_multi_kill, killing_sprees=pp.killing_sprees,
                time_spent_dead=pp.time_spent_dead,
            ))
        rating_service._integrity = PremadeIntegrity(ineligible, party_store)
        played_at = (
            datetime.fromtimestamp(parsed.started_at_ms / 1000, UTC).isoformat()
            if parsed.started_at_ms else datetime.now(UTC).isoformat()
        )
        raw = RawMatch(
            match_id=str(uuid.uuid4()), riot_match_id=parsed.match_id,
            season_id=season_id, mode=parsed.mode.value, queue_id=parsed.queue_id,
            played_at=played_at, participants=raw_parts,
            duration_seconds=parsed.game_duration,
        )
        await rating_service.process_match(session, _noop_lock, raw)
        stats.processed += 1
    return stats
