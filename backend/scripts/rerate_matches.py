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
import time
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from arena.core.config import settings
from arena.db import models as m
from arena.services.protocols import IntegrityVerdict, RawMatch, RawParticipant
from arena.services.rating_service import RatingService


def _get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Direct-to-Postgres engine, deliberately separate from
    ``arena.db.session.get_engine()``.

    The shared engine sets ``connect_args={"statement_cache_size": 0}``
    because the API tier goes through PgBouncer in *transaction* mode, where
    a prepared statement can silently outlive the physical connection it was
    prepared on. This script always opens one long-lived session straight
    against Postgres (or a session-mode pooler) — never a tx-mode pooler —
    so that restriction doesn't apply, and disabling asyncpg's client-side
    statement cache is pure cost here: every query pays a full extra
    parse+describe round trip instead of reusing the cached plan. Measured
    locally (Docker Desktop networking) that's the difference between
    ~0.6ms and ~44ms per query — with ~8-10 queries per match in the replay
    write path, THAT was the ~1 match/sec bottleneck, not disk/fsync.
    """
    engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


class Progress:
    """Time-boxed progress reporter for a long, single-threaded loop.

    Prints at most once per ``min_interval_s`` (never more often, so a fast
    phase doesn't spam), but ALWAYS ``flush=True`` — without it, Python
    line-buffers stdout when it isn't a TTY (i.e. whenever output is piped or
    redirected to a file, which is exactly how a long background run gets
    watched), so nothing appears until the process exits. That silence is
    indistinguishable from a hang from the outside.
    """

    def __init__(self, total: int, label: str, min_interval_s: float = 3.0) -> None:
        self.total = total
        self.label = label
        self.min_interval_s = min_interval_s
        self.start = time.monotonic()
        self._last_print = 0.0
        self._last_done = 0

    def tick(self, done: int, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last_print) < self.min_interval_s:
            return
        elapsed = now - self.start
        # Rate over the whole run so far — steady per-match cost here (no
        # network/rate-limit bursts like live ingestion has), so this is a
        # more stable ETA than a short rolling window would give.
        rate = done / elapsed if elapsed > 0 else 0.0
        remaining = self.total - done
        eta_s = remaining / rate if rate > 0 else float("inf")
        pct = 100 * done / self.total if self.total else 100.0
        print(
            f"  [{self.label}] {done}/{self.total} ({pct:.1f}%) "
            f"| {rate:.2f}/s | elapsed {_fmt_hms(elapsed)} | ETA {_fmt_hms(eta_s)}",
            flush=True,
        )
        self._last_print = now
        self._last_done = done

    def done(self, done: int) -> None:
        self.tick(done, force=True)


def _fmt_hms(seconds: float) -> str:
    if seconds == float("inf"):
        return "?"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    mnt, s = divmod(rem, 60)
    return f"{h}h{mnt:02d}m{s:02d}s" if h else f"{mnt}m{s:02d}s"


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

    factory = _get_sessionmaker()
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

        print(f"season={season_id}", flush=True)
        print(f"reconstructing replay set from {len(match_rows)} matches ...", flush=True)

        # ONE bulk scan of match_participants for the whole season, grouped by
        # match_id in memory, instead of one query per match. match_participants
        # is HASH-partitioned by player_id and matches is range-partitioned by
        # time — a plain (non-self-join) scan across that partition mismatch is
        # the known-safe pattern here (see StatsService.rebuild_champion_versus'
        # docstring for the self-join catastrophe this avoids); a per-match
        # round trip x83k was the actual bottleneck, not this join shape.
        print("  bulk-fetching participants ...", flush=True)
        t_fetch = time.monotonic()
        all_parts = (
            await s.execute(
                select(
                    m.MatchParticipant.match_id,
                    m.MatchParticipant.player_id,
                    m.MatchParticipant.champion_id,
                    m.MatchParticipant.team_id,
                    m.MatchParticipant.placement,
                    m.MatchParticipant.eligible,
                    m.MatchParticipant.is_premade,
                    m.MatchParticipant.party_id,
                    m.MatchParticipant.augments,
                    m.MatchParticipant.items,
                    m.MatchParticipant.kills,
                    m.MatchParticipant.deaths,
                    m.MatchParticipant.assists,
                    m.MatchParticipant.damage_to_champions,
                    m.MatchParticipant.gold_earned,
                    m.MatchParticipant.champion_level,
                    m.MatchParticipant.damage_taken,
                    m.MatchParticipant.total_heal,
                    m.MatchParticipant.damage_self_mitigated,
                    m.MatchParticipant.largest_multi_kill,
                    m.MatchParticipant.killing_sprees,
                    m.MatchParticipant.time_spent_dead,
                )
                .select_from(m.MatchParticipant.__table__.join(
                    m.Match.__table__, m.Match.__table__.c.id == m.MatchParticipant.match_id
                ))
                .where(m.Match.__table__.c.season_id == season_id)
            )
        ).all()
        parts_by_match: dict[object, list[Any]] = {}
        for row in all_parts:
            parts_by_match.setdefault(row.match_id, []).append(row)
        print(
            f"  bulk-fetch done: {len(all_parts)} rows in {_fmt_hms(time.monotonic() - t_fetch)}",
            flush=True,
        )

        reconstruct_progress = Progress(len(match_rows), "reconstruct")

        replay: list[tuple[RawMatch, set[str]]] = []
        for i, mr in enumerate(match_rows, start=1):
            reconstruct_progress.tick(i)
            parts = parts_by_match.get(mr.id, [])
            if not parts:
                continue
            ineligible = {str(p.player_id) for p in parts if p.eligible is False}
            # is_premade/party_id/augments/items/combat telemetry are immutable
            # facts about the match, not rating outputs — _persist rewrites the
            # whole row on every rerate, so leaving these out here silently
            # resets them to False/None/[]/0 on every run (see
            # arena/services/replay.py, which carries the same fields for
            # exactly this reason).
            raw_parts = [
                RawParticipant(
                    player_id=str(p.player_id),
                    champion_id=p.champion_id,
                    team_id=p.team_id,
                    placement=p.placement,
                    is_premade=bool(p.is_premade),
                    party_id=p.party_id,
                    augments=list(p.augments or []),
                    items=list(p.items or []),
                    kills=int(p.kills or 0),
                    deaths=int(p.deaths or 0),
                    assists=int(p.assists or 0),
                    damage_to_champions=int(p.damage_to_champions or 0),
                    gold_earned=int(p.gold_earned or 0),
                    champion_level=int(p.champion_level or 0),
                    damage_taken=int(p.damage_taken or 0),
                    total_heal=int(p.total_heal or 0),
                    damage_self_mitigated=int(p.damage_self_mitigated or 0),
                    largest_multi_kill=int(p.largest_multi_kill or 0),
                    killing_sprees=int(p.killing_sprees or 0),
                    time_spent_dead=int(p.time_spent_dead or 0),
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
        reconstruct_progress.done(len(match_rows))

        print(
            f"replay set: {len(replay)} matches, "
            f"{sum(len(r.participants) for r, _ in replay)} participations",
            flush=True,
        )
        print("BEFORE:", flush=True)
        print(await _distribution(s, season_id), flush=True)

        if not args.apply:
            print("\n[dry-run] no changes. Re-run with --apply to wipe+rebuild.", flush=True)
            return

        # 2) Wipe derived state for the season (facts in matches/players are kept).
        print("\n[apply] wiping derived rating state ...", flush=True)
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
        print("[apply] wipe complete — replaying ...", flush=True)

        # 3) Replay through the canonical write path (commits per match).
        svc = RatingService(_Clean(set()))
        replay_progress = Progress(len(replay), "replay")
        done = 0
        for raw, ineligible in replay:
            svc._integrity = _Clean(ineligible)
            await svc.process_match(s, _noop_lock, raw)
            done += 1
            replay_progress.tick(done)

        replay_progress.done(done)
        print(f"\n[apply] done: re-rated {done} matches", flush=True)
        print("AFTER:", flush=True)
        print(await _distribution(s, season_id), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
