"""Diagnose the pre-existing CR injection (~+75 CR/match) — NON-destructive.

Decomposes mean cr_delta into its two channels via the identity
    cr_delta = Δμ − 3·Δσ
and reports per-match SUM of each (is mu conserved by the PL update? is the
injection the sigma-convergence dividend?), plus the sigma trajectory by games.
No caps. Feeds the Trinity Phase-2 escalation.

Run (cwd backend):
    DATABASE_URL=postgresql+asyncpg://arena:arena@localhost:5433/arena \
      python -m scripts.diag_inflation
"""

from __future__ import annotations

import asyncio
import statistics
from dataclasses import replace

from sqlalchemy import select

from arena.db import models as m
from arena.db.session import get_sessionmaker
from arena.rating import MatchInput, ParticipantInput, PlayerState, TeamInput, rate
from arena.rating.params import DEFAULT_PARAMS


def _initial(pid: str, p) -> PlayerState:
    cr = (p.mu0 - 3.0 * p.sigma0) * p.scale_factor + p.base_offset
    return PlayerState(
        player_id=pid,
        mu=p.mu0,
        sigma=p.sigma0,
        cr=cr,
        current_streak=0,
        matches_played=0,
        placement_matches_remaining=p.placement_match_count,
        peak_cr=cr,
    )


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

    p = replace(DEFAULT_PARAMS, caps=None)  # diagnose the pre-existing (uncapped) injection
    states: dict[str, PlayerState] = {}
    dmu, dsig_term, crd = [], [], []  # per participation
    match_sum_mu, match_sum_crd = [], []  # per match
    sigma_by_games: dict[int, list[float]] = {}

    for parts in replay:
        by_team: dict[int, list[str]] = {}
        pbt: dict[int, int] = {}
        for pid, tid, pl in parts:
            by_team.setdefault(tid, []).append(pid)
            pbt[tid] = pl
            if pid not in states:
                states[pid] = _initial(pid, p)
        teams = [
            TeamInput(
                team_id=tid,
                placement=pbt[tid],
                participants=[
                    ParticipantInput(
                        player_id=pid,
                        state=states[pid],
                        champion_id=0,
                        eligible_for_progression=True,
                    )
                    for pid in mem
                ],
            )
            for tid, mem in by_team.items()
        ]
        res = rate(MatchInput(match_id="d", mode="TRIOS", teams=teams, params=p))
        s_mu = s_crd = 0.0
        for pr in res.players:
            if pr.eligible:
                d_mu = pr.mu_after - pr.mu_before
                d_si = pr.sigma_after - pr.sigma_before
                dmu.append(d_mu)
                dsig_term.append(-3.0 * d_si)
                crd.append(pr.cr_delta)
                s_mu += d_mu
                s_crd += pr.cr_delta
                sigma_by_games.setdefault(states[pr.player_id].matches_played, []).append(
                    pr.sigma_after
                )
            st = states[pr.player_id]
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
        match_sum_mu.append(s_mu)
        match_sum_crd.append(s_crd)

    print(f"participations={len(crd)}  matches={len(match_sum_crd)}\n")
    print("DECOMPOSITION (per participation):")
    print(f"  mean Δμ          = {statistics.fmean(dmu):+.3f}")
    print(f"  mean (−3·Δσ)     = {statistics.fmean(dsig_term):+.3f}")
    print(f"  mean cr_delta    = {statistics.fmean(crd):+.3f}   (= Δμ − 3Δσ)")
    print("\nPER-MATCH SUM (conservation check):")
    print(
        f"  mean Σ Δμ / match      = {statistics.fmean(match_sum_mu):+.2f}  (≈0 ⇒ PL conserves μ)"
    )
    print(
        f"  mean Σ cr_delta / match = {statistics.fmean(match_sum_crd):+.2f}  (the real injection)"
    )
    print("\nσ TRAJECTORY by games_before (does σ converge or stall near σ0=200?):")
    for g in sorted(sigma_by_games):
        if g > 10:
            break
        v = sigma_by_games[g]
        print(f"  games={g:>2} n={len(v):>4} mean_sigma_after={statistics.fmean(v):6.1f}")


if __name__ == "__main__":
    asyncio.run(main())
