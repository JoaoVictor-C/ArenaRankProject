"""Re-rate every stored match through the CURRENT rating engine (params.py).

Repairs historical rating data after a params/engine change. Replays the matches
already in the DB — in chronological ``(played_at, riot_match_id)`` order —
through the SAME :class:`RatingService` write path used by ingestion, WITHOUT
touching the Riot API (each :class:`RawMatch` is reconstructed from the stored
``matches`` + ``match_participants`` rows). Whatever ``arena.rating`` does at run
time (params + pipeline) is what gets applied, so this picks up any param or
structural change automatically.

Destructive with ``--apply``: it wipes the season's DERIVED rating state
(``player_seasons``, ``match_participants``, ``cr_snapshots``, ``champion_stats``)
and rebuilds it from the immutable match facts (placement / team / champion /
played_at), which are captured in memory BEFORE the wipe. The ``matches`` and
``players`` rows themselves are preserved (only ``matches.processed`` is reset).
ALWAYS ``pg_dump`` first — see workaround.md.

``--dry-run`` (default) mutates nothing: it reconstructs the replay set and prints
the BEFORE distribution so you can sanity-check scope.

Run (cwd backend):
    DATABASE_URL=postgresql+asyncpg://arena:arena@localhost:5433/arena \
      python -m scripts.rerate_matches --apply
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select, text

from arena.db import models as m
from arena.db.session import get_sessionmaker
from arena.services.protocols import IntegrityVerdict, RawMatch, RawParticipant
from arena.services.rating_service import RatingService


class _Clean:
    """Integrity stub mirroring backfill: only the per-match ineligible set."""

    def __init__(self, ineligible: set[str]) -> None:
        self._ineligible = ineligible

    async def evaluate(self, match: RawMatch, states: object = None) -> IntegrityVerdict:
        return IntegrityVerdict(ineligible_player_ids=set(self._ineligible))


def _noop_lock(_ids):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def cm():
        yield

    return cm()


async def _distribution(s, season_id: str) -> str:
    """One-line CR / sigma / cr_delta summary for before/after comparison."""
    cr = (
        await s.execute(
            text(
                "SELECT count(*) n, round(min(cr)::numeric,1) mn, "
                "round(max(cr)::numeric,1) mx, round(avg(cr)::numeric,1) av, "
                "count(*) FILTER (WHERE cr<0) neg FROM player_seasons "
                "WHERE season_id=:s"
            ),
            {"s": season_id},
        )
    ).one()
    sig = (
        await s.execute(
            text(
                "SELECT round(avg(sigma)::numeric,1) av_sig, "
                "round(min(sigma)::numeric,1) mn_sig FROM player_seasons "
                "WHERE season_id=:s"
            ),
            {"s": season_id},
        )
    ).one()
    dl = (
        await s.execute(
            text(
                "SELECT count(*) n, round(min(cr_delta)::numeric,1) mn, "
                "round(max(cr_delta)::numeric,1) mx, round(avg(cr_delta)::numeric,2) av, "
                "round(stddev(cr_delta)::numeric,1) sd FROM match_participants mp "
                "JOIN matches mt ON mt.id=mp.match_id WHERE mt.season_id=:s "
                "AND mp.cr_delta IS NOT NULL"
            ),
            {"s": season_id},
        )
    ).one()
    return (
        f"  CR: n={cr.n} min={cr.mn} max={cr.mx} avg={cr.av} neg={cr.neg} "
        f"({0 if not cr.n else round(100 * cr.neg / cr.n, 1)}%)\n"
        f"  sigma: avg={sig.av_sig} min={sig.mn_sig}\n"
        f"  cr_delta: n={dl.n} min={dl.mn} max={dl.mx} avg={dl.av} sd={dl.sd}"
    )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually wipe+rebuild (default dry-run)")
    ap.add_argument("--season", default=None, help="season UUID (default: active, else first)")
    args = ap.parse_args()

    factory = get_sessionmaker()
    async with factory() as s:
        if args.season:
            season_id = args.season
        else:
            season = (
                await s.execute(
                    select(m.Season).where(m.Season.status == m.SeasonStatus.ACTIVE).limit(1)
                )
            ).scalar_one_or_none() or (await s.execute(select(m.Season).limit(1))).scalar_one()
            season_id = str(season.id)

        # 1) Reconstruct the replay set from immutable facts BEFORE any mutation.
        match_rows = (
            await s.execute(
                select(
                    m.Match.id,
                    m.Match.riot_match_id,
                    m.Match.mode,
                    m.Match.queue_id,
                    m.Match.played_at,
                    m.Match.duration_seconds,
                )
                .where(m.Match.season_id == season_id)
                .order_by(m.Match.played_at, m.Match.riot_match_id)
            )
        ).all()

        replay: list[tuple[RawMatch, set[str]]] = []
        for mr in match_rows:
            parts = (
                await s.execute(
                    select(
                        m.MatchParticipant.player_id,
                        m.MatchParticipant.champion_id,
                        m.MatchParticipant.team_id,
                        m.MatchParticipant.placement,
                        m.MatchParticipant.eligible,
                    ).where(m.MatchParticipant.match_id == mr.id)
                )
            ).all()
            if not parts:
                continue
            ineligible = {str(p.player_id) for p in parts if p.eligible is False}
            raw_parts = [
                RawParticipant(
                    player_id=str(p.player_id),
                    champion_id=p.champion_id,
                    team_id=p.team_id,
                    placement=p.placement,
                )
                for p in parts
            ]
            raw = RawMatch(
                match_id=str(mr.id),
                riot_match_id=mr.riot_match_id,
                season_id=season_id,
                mode=mr.mode.value if hasattr(mr.mode, "value") else str(mr.mode),
                queue_id=mr.queue_id,
                played_at=mr.played_at.isoformat(),  # preserve original timestamp
                participants=raw_parts,
                duration_seconds=mr.duration_seconds,
            )
            replay.append((raw, ineligible))

        print(f"season={season_id}")
        print(
            f"replay set: {len(replay)} matches, "
            f"{sum(len(r.participants) for r, _ in replay)} participations"
        )
        print("BEFORE:")
        print(await _distribution(s, season_id))

        if not args.apply:
            print("\n[dry-run] no changes. Re-run with --apply to wipe+rebuild.")
            return

        # 2) Wipe derived state for the season (facts in matches/players are kept).
        print("\n[apply] wiping derived rating state ...")
        await s.execute(text("DELETE FROM cr_snapshots WHERE season_id=:s"), {"s": season_id})
        await s.execute(text("DELETE FROM champion_stats WHERE season_id=:s"), {"s": season_id})
        await s.execute(
            text(
                "DELETE FROM match_participants WHERE match_id IN "
                "(SELECT id FROM matches WHERE season_id=:s)"
            ),
            {"s": season_id},
        )
        await s.execute(text("DELETE FROM player_seasons WHERE season_id=:s"), {"s": season_id})
        await s.execute(
            text("UPDATE matches SET processed=false, processed_at=NULL WHERE season_id=:s"),
            {"s": season_id},
        )
        await s.commit()

        # 3) Replay through the canonical write path (commits per match).
        svc = RatingService(_Clean(set()))
        done = 0
        for raw, ineligible in replay:
            svc._integrity = _Clean(ineligible)
            await svc.process_match(s, _noop_lock, raw)
            done += 1
            if done % 25 == 0:
                print(f"  re-rated {done}/{len(replay)}")

        print(f"\n[apply] done: re-rated {done} matches")
        print("AFTER:")
        print(await _distribution(s, season_id))


if __name__ == "__main__":
    asyncio.run(main())
