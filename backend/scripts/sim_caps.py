"""What-if simulator for the PDL cap layer — NON-destructive, no DB writes.

Replays the stored matches through the rating engine under (a) no caps and (b) each
candidate base-cap curve, with caps ENABLED IN THE ENGINE (option B-pure: mu is
clamped to hit the capped cr_delta, so the clamp COMPOUNDS across the season — this
is the true trajectory, not a first-order post-process). Tabulates the per-match
cr_delta by placement so the symmetric-vs-asymmetric PO decision is data-driven.

Run (cwd backend):
    DATABASE_URL=postgresql+asyncpg://arena:arena@localhost:5433/arena \
      python -m scripts.sim_caps
"""

from __future__ import annotations

import asyncio
import statistics
from dataclasses import replace

from sqlalchemy import select

from arena.db import models as m
from arena.db.session import get_sessionmaker
from arena.rating import MatchInput, ParticipantInput, PlayerState, TeamInput, rate
from arena.rating.caps import ASYMMETRIC_CAPS_6, CAPS_8, SYMMETRIC_CAPS_6, CapParams
from arena.rating.params import DEFAULT_PARAMS


def _initial(player_id: str, p) -> PlayerState:
    cr = (p.mu0 - 3.0 * p.sigma0) * p.scale_factor + p.base_offset
    return PlayerState(
        player_id=player_id,
        mu=p.mu0,
        sigma=p.sigma0,
        cr=cr,
        current_streak=0,
        matches_played=0,
        placement_matches_remaining=p.placement_match_count,
        peak_cr=cr,
    )


def _simulate(replay, p) -> list[tuple[int, float, bool, int]]:
    """Replay through the engine with params `p`; return
    [(placement, cr_delta, clamped, games_before)] per eligible participation, in
    deterministic engine order. `clamped` is the TRUE per-match clamp flag: capped vs
    uncapped delta from the IDENTICAL pre-state (so the compounded-trajectory
    divergence does not inflate the rate)."""
    p_nocap = replace(p, caps=None) if p.caps is not None else None
    states: dict[str, PlayerState] = {}
    out: list[tuple[int, float, bool]] = []
    for parts in replay:  # parts: list[(player_id, team_id, placement)]
        by_team: dict[int, list[str]] = {}
        placement_by_team: dict[int, int] = {}
        for pid, team_id, placement in parts:
            by_team.setdefault(team_id, []).append(pid)
            placement_by_team[team_id] = placement
            if pid not in states:
                states[pid] = _initial(pid, p)
        placement_of = {pid: placement_by_team[tid] for tid, mem in by_team.items() for pid in mem}
        teams = [
            TeamInput(
                team_id=tid,
                placement=placement_by_team[tid],
                participants=[
                    ParticipantInput(
                        player_id=pid,
                        state=states[pid],
                        champion_id=0,
                        eligible_for_progression=True,
                    )
                    for pid in members
                ],
            )
            for tid, members in by_team.items()
        ]
        mi = MatchInput(match_id="sim", mode="TRIOS", teams=teams, params=p)
        result = rate(mi)
        # uncapped deltas from the SAME pre-state, for an honest per-match clamp flag
        raw_delta = {}
        if p_nocap is not None:
            for pr in rate(replace(mi, params=p_nocap)).players:
                raw_delta[pr.player_id] = pr.cr_delta
        for pr in result.players:
            st = states[pr.player_id]
            if pr.eligible:
                clamped = (
                    pr.player_id in raw_delta and abs(pr.cr_delta - raw_delta[pr.player_id]) > 0.05
                )
                out.append((placement_of[pr.player_id], pr.cr_delta, clamped, st.matches_played))
            states[pr.player_id] = replace(
                st,
                mu=pr.mu_after,
                sigma=pr.sigma_after,
                cr=pr.cr_after,
                current_streak=pr.new_streak,
                matches_played=st.matches_played + 1,
                placement_matches_remaining=max(0, st.placement_matches_remaining - 1),
                peak_cr=max(st.peak_cr, pr.cr_after),
            )
    return out


def _report(label: str, deltas: list[tuple[int, float, bool, int]]) -> None:
    print(f"\n=== {label} ===")
    print(f"{'place':>5} {'n':>4} {'min':>7} {'mean':>7} {'max':>7}  {'%clamped':>8}")
    by_place: dict[int, list[float]] = {}
    clamp_by_place: dict[int, int] = {}
    for pl, d, clamped, _g in deltas:
        by_place.setdefault(pl, []).append(d)
        if clamped:
            clamp_by_place[pl] = clamp_by_place.get(pl, 0) + 1
    allv = [d for _pl, d, _c, _g in deltas]
    nclamp = sum(clamp_by_place.values())
    for pl in sorted(by_place):
        vals = by_place[pl]
        pct = 100 * clamp_by_place.get(pl, 0) / len(vals)
        print(
            f"{pl:>5} {len(vals):>4} {min(vals):>7.1f} {statistics.fmean(vals):>7.1f} "
            f"{max(vals):>7.1f}  {pct:>7.1f}%"
        )
    print(
        f"GLOBAL n={len(allv)} min={min(allv):.1f} max={max(allv):.1f} "
        f"mean={statistics.fmean(allv):.1f} sd={statistics.pstdev(allv):.1f} "
        f"clamped={nclamp} ({100 * nclamp / len(allv):.1f}%)"
    )


def _report_by_games(label: str, deltas: list[tuple[int, float, bool, int]]) -> None:
    """Mean cr_delta bucketed by games-played-before — is inflation a provisional
    (sigma-convergence) artifact that fades for established players, or a real drift?"""
    print(f"\n--- {label}: mean cr_delta by games_before ---")
    by_g: dict[int, list[float]] = {}
    for _pl, d, _c, g in deltas:
        bucket = g if g <= 5 else 6  # 0..5, then 6+ lumped
        by_g.setdefault(bucket, []).append(d)
    for b in sorted(by_g):
        vals = by_g[b]
        tag = f"{b}+" if b == 6 else str(b)
        print(f"  games={tag:>3} n={len(vals):>4} mean={statistics.fmean(vals):>6.2f}")


async def main() -> None:
    factory = get_sessionmaker()
    async with factory() as s:
        season = (
            await s.execute(
                select(m.Season).where(m.Season.status == m.SeasonStatus.ACTIVE).limit(1)
            )
        ).scalar_one_or_none() or (await s.execute(select(m.Season).limit(1))).scalar_one()
        season_id = str(season.id)
        match_rows = (
            await s.execute(
                select(m.Match.id, m.Match.played_at, m.Match.riot_match_id)
                .where(m.Match.season_id == season_id)
                .order_by(m.Match.played_at, m.Match.riot_match_id)
            )
        ).all()
        replay = []
        for mr in match_rows:
            parts = (
                await s.execute(
                    select(
                        m.MatchParticipant.player_id,
                        m.MatchParticipant.team_id,
                        m.MatchParticipant.placement,
                    ).where(m.MatchParticipant.match_id == mr.id)
                )
            ).all()
            if parts:
                replay.append([(str(p.player_id), p.team_id, p.placement) for p in parts])

    print(
        f"season={season_id}  matches={len(replay)}  participations={sum(len(r) for r in replay)}"
    )

    raw = _simulate(replay, replace(DEFAULT_PARAMS, caps=None))
    _report("RAW (no cap baseline)", raw)

    sym = replace(
        DEFAULT_PARAMS, caps=CapParams(base_cap_by_placement={**SYMMETRIC_CAPS_6, **CAPS_8})
    )
    asym = replace(
        DEFAULT_PARAMS, caps=CapParams(base_cap_by_placement={**ASYMMETRIC_CAPS_6, **CAPS_8})
    )
    # RECOMMENDED: gain table symmetric, loss decoupled to ~P95 (painful, low-inflation)
    aloss = replace(
        DEFAULT_PARAMS,
        caps=CapParams(base_cap_by_placement={**SYMMETRIC_CAPS_6, **CAPS_8}, loss_clamp=68.0),
    )
    sym_d = _simulate(replay, sym)
    _report("SYMMETRIC {40,34,26,26,34,40} (loss=-40)", sym_d)
    _report("ASYMMETRIC table {40,34,28,22,34,40}", _simulate(replay, asym))
    _report("GAIN-CAP + LOSS-CLAMP 68 (recommended)", _simulate(replay, aloss))

    # inflation diagnosis: provisional (sigma-convergence) vs persistent drift
    _report_by_games("RAW", raw)
    _report_by_games("SYMMETRIC", sym_d)


if __name__ == "__main__":
    asyncio.run(main())
