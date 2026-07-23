"""E2E write-path smoke: drive a real Riot Arena fixture through the rating pipeline.

Parses a match-v5 payload, registers its players, builds a RawMatch, runs
RatingService.process_match (with a no-op integrity verdict + no-op lock), then
prints the resulting match_participants + top player_seasons by CR.

Run:  DATABASE_URL=postgresql+asyncpg://arena:arena@localhost:5433/arena \
        python -m scripts.e2e_process_fixture "F:\\arenarank\\BR1_3249589772.json"
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, text

from arena.db import models as m
from arena.db.session import get_sessionmaker
from arena.riot.arena import NotAnArenaMatch, parse_arena_match
from arena.services.protocols import IntegrityVerdict, RawMatch, RawParticipant
from arena.services.rating_service import RatingService

FIXTURE = sys.argv[1] if len(sys.argv) > 1 else r"F:\arenarank\BR1_3249589772.json"


class FakeIntegrity:
    """Clean verdict: no flags, no boosting, eligibility from the parser."""

    def __init__(self, ineligible: set[str]) -> None:
        self._ineligible = set(ineligible)

    async def evaluate(self, match: RawMatch) -> IntegrityVerdict:
        return IntegrityVerdict(
            flags=[], boosting_factors={}, ineligible_player_ids=set(self._ineligible)
        )


@asynccontextmanager
async def noop_lock(player_ids):
    yield


async def main() -> None:
    payload = json.loads(Path(FIXTURE).read_text(encoding="utf-8"))
    try:
        parsed = parse_arena_match(payload)
    except NotAnArenaMatch as exc:
        print("NOT_ARENA:", exc)
        return
    print(
        f"parsed: riot={parsed.match_id} mode={parsed.mode.value} "
        f"queue={parsed.queue_id} subteams={len(parsed.subteams)} complete={parsed.is_complete}"
    )

    factory = get_sessionmaker()
    async with factory() as s:
        season = (
            await s.execute(
                select(m.Season).where(m.Season.status == m.SeasonStatus.ACTIVE).limit(1)
            )
        ).scalar_one_or_none()
        if season is None:
            season = (await s.execute(select(m.Season).limit(1))).scalar_one()
        season_id = str(season.id)

        ineligible: set[str] = set()
        raw_parts: list[RawParticipant] = []
        for st in parsed.subteams:
            for p in st.participants:
                existing = (
                    await s.execute(select(m.Player).where(m.Player.puuid == p.puuid).limit(1))
                ).scalar_one_or_none()
                if existing is None:
                    pl = m.Player(
                        puuid=p.puuid,
                        summoner_name=p.riot_id_game_name or None,
                        tag_line=p.riot_id_tagline or None,
                        region="br",
                        profile_icon_id=p.profile_icon or None,
                    )
                    s.add(pl)
                    await s.flush()
                    pid = str(pl.id)
                else:
                    # Backfill the ddragon profile icon for pre-existing rows.
                    if p.profile_icon and existing.profile_icon_id != p.profile_icon:
                        existing.profile_icon_id = p.profile_icon
                    pid = str(existing.id)
                if not p.eligible_for_progression:
                    ineligible.add(pid)
                raw_parts.append(
                    RawParticipant(
                        player_id=pid,
                        champion_id=p.champion_id,
                        team_id=st.subteam_id,
                        placement=st.placement,
                    )
                )
        await s.commit()

        match_id = str(uuid.uuid4())
        raw = RawMatch(
            match_id=match_id,
            riot_match_id=parsed.match_id,
            season_id=season_id,
            mode=parsed.mode.value,
            queue_id=parsed.queue_id,
            played_at=datetime.now(UTC).isoformat(),
            participants=raw_parts,
            duration_seconds=parsed.game_duration,
        )

        svc = RatingService(FakeIntegrity(ineligible))
        outcome = await svc.process_match(s, noop_lock, raw)
        print(
            f"outcome: status={outcome.status} players_updated={outcome.players_updated} "
            f"flags={outcome.flags_emitted} ineligible={len(ineligible)}"
        )

        mp = (
            await s.execute(
                text("select count(*) from match_participants where match_id=:mid"),
                {"mid": match_id},
            )
        ).scalar()
        snaps = (
            await s.execute(
                text("select count(*) from cr_snapshots where season_id=:sid"),
                {"sid": season_id},
            )
        ).scalar()
        print(f"persisted: match_participants={mp} cr_snapshots={snaps}")

        top = (
            await s.execute(
                select(
                    m.PlayerSeason.player_id,
                    m.PlayerSeason.cr,
                    m.PlayerSeason.mu,
                    m.PlayerSeason.sigma,
                    m.PlayerSeason.current_streak,
                )
                .where(m.PlayerSeason.season_id == season_id)
                .order_by(m.PlayerSeason.cr.desc())
                .limit(6)
            )
        ).all()
        print("top player_seasons by CR:")
        for r in top:
            print(
                f"   {r.player_id}  cr={r.cr:.1f}  mu={r.mu:.1f}  sigma={r.sigma:.1f}  streak={r.current_streak}"
            )


if __name__ == "__main__":
    asyncio.run(main())
