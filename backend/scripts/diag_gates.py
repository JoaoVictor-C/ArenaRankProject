"""Trinity Phase-2 empirical gates (T2/T3/T6) — NON-destructive, no DB writes.

Runs the falsifiable gates the Trinity inflation run put on record, so its decision
matrix can select a branch:
  T3  P95(|loss|): does the recalibration's 77 swing-ceiling bind the loss clamp?
      (adjudicates cap-only-restores vs partial-restoration regime)
  T2  mu-channel attribution: replay with tau=0 — does Sigma_dmu/match collapse to 0?
      (tests the "tau pre-inflation drives mu non-conservation" hypothesis, weight 0.6)
  T6  per-CR-band + per-cohort mean cr_delta with Dmu vs -3Dsig decomposition, vs the
      per-band soft-reset budget ~= 0.5*|CR - 1250| (the cap-only vs engine-surgery call)

Run (cwd backend):
    DATABASE_URL=postgresql+asyncpg://arena:arena@localhost:5433/arena \
      PYTHONIOENCODING=utf-8 python -m scripts.diag_gates
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

BANDS = [(-1e9, 1000), (1000, 1250), (1250, 1400), (1400, 1600), (1600, 1850), (1850, 1e9)]


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


def _band(cr: float) -> tuple[float, float]:
    for lo, hi in BANDS:
        if lo <= cr < hi:
            return (lo, hi)
    return BANDS[-1]


async def _load_replay():
    factory = get_sessionmaker()
    async with factory() as s:
        season = (
            await s.execute(
                select(m.Season).where(m.Season.status == m.SeasonStatus.ACTIVE).limit(1)
            )
        ).scalar_one_or_none() or (await s.execute(select(m.Season).limit(1))).scalar_one()
        sid = str(season.id)
        mrows = (
            await s.execute(
                select(m.Match.id, m.Match.played_at, m.Match.riot_match_id)
                .where(m.Match.season_id == sid)
                .order_by(m.Match.played_at, m.Match.riot_match_id)
            )
        ).all()
        replay = []
        for mr in mrows:
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
    return replay


def _replay(replay, p):
    """Return (rows, match_sum_dmu). rows: dict per eligible participation."""
    states: dict[str, PlayerState] = {}
    rows = []
    match_sum_dmu = []
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
        s_dmu = 0.0
        for pr in res.players:
            st = states[pr.player_id]
            if pr.eligible:
                d_mu = pr.mu_after - pr.mu_before
                s_dmu += d_mu
                rows.append(
                    {
                        "cr_before": pr.cr_before,
                        "cr_delta": pr.cr_delta,
                        "d_mu": d_mu,
                        "m3dsig": -3.0 * (pr.sigma_after - pr.sigma_before),
                        "games_before": st.matches_played,
                        "pid": pr.player_id,
                    }
                )
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
        match_sum_dmu.append(s_dmu)
    return rows, match_sum_dmu


def _pctl(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, int(q * len(sorted_vals)))
    return sorted_vals[i]


async def main() -> None:
    replay = await _load_replay()
    total_games: dict[str, int] = {}
    for parts in replay:
        for pid, _t, _pl in parts:
            total_games[pid] = total_games.get(pid, 0) + 1

    base = replace(DEFAULT_PARAMS, caps=None)  # gates analyze the uncapped baseline
    rows, msum = _replay(replay, base)
    print(f"participations={len(rows)} matches={len(msum)}\n")

    # ---- T3: P95(|loss|) ----
    losses = sorted(-r["cr_delta"] for r in rows if r["cr_delta"] < 0)
    print("=== T3: loss magnitude (|negative cr_delta|) ===")
    print(
        f"  n_losses={len(losses)} P50={_pctl(losses, 0.50):.1f} P95={_pctl(losses, 0.95):.1f} "
        f"P99={_pctl(losses, 0.99):.1f} max={losses[-1] if losses else 0:.1f}"
    )
    p95 = _pctl(losses, 0.95)
    print(
        f"  loss_clamp = min(P95, 77) = {min(p95, 77.0):.1f}  "
        f"-> 77 ceiling {'BINDS' if p95 > 77 else 'does NOT bind (P95<77, cap-only restores)'}"
    )

    # ---- T2: mu-channel counterfactual (tau=0) ----
    _rows0, msum0 = _replay(replay, replace(base, tau=0.0))
    print("\n=== T2: mu non-conservation, tau counterfactual ===")
    print(f"  mean Sigma_dmu/match  tau=1.5 (prod) = {statistics.fmean(msum):+.2f}")
    print(f"  mean Sigma_dmu/match  tau=0.0 (c-fac) = {statistics.fmean(msum0):+.2f}")
    print(
        f"  -> tau explains {100 * (1 - statistics.fmean(msum0) / statistics.fmean(msum)):.0f}% "
        f"of mu injection"
        if statistics.fmean(msum)
        else ""
    )

    # ---- T6: per-band + per-cohort ----
    print("\n=== T6: per-CR-band mean cr_delta + decomposition + soft-reset budget ===")
    print(
        f"{'band':>14} {'n':>4} {'mean_crd':>9} {'mean_dmu':>9} {'mean_-3ds':>10} {'budget':>7} {'flag':>6}"
    )
    for lo, hi in BANDS:
        br = [r for r in rows if lo <= r["cr_before"] < hi]
        if not br:
            continue
        mid = (lo if lo > -1e8 else 800) + (min(hi, 2100) - (lo if lo > -1e8 else 800)) / 2
        budget = 0.5 * abs(mid - 1250)
        mc = statistics.fmean(r["cr_delta"] for r in br)
        flag = "RISK" if mc * 5 > budget and budget < 120 else ""
        lbl = f"[{int(lo) if lo > -1e8 else '-inf'},{int(hi) if hi < 1e8 else 'inf'})"
        print(
            f"{lbl:>14} {len(br):>4} {mc:>9.2f} "
            f"{statistics.fmean(r['d_mu'] for r in br):>9.2f} "
            f"{statistics.fmean(r['m3dsig'] for r in br):>10.2f} {budget:>7.0f} {flag:>6}"
        )

    print(
        "\n  cohorts (Trinity predictions: single +6..+8 [Bayesian signal], multi +2.5..+3.5 [artifact]):"
    )
    for name, pred in (("single (total==1)", "+6..+8"), ("multi (total>=2)", "+2.5..+3.5")):
        single = name.startswith("single")
        cr = [r for r in rows if (total_games[r["pid"]] == 1) == single]
        if cr:
            print(
                f"    {name:>20} n={len(cr):>4} mean_crd={statistics.fmean(r['cr_delta'] for r in cr):+.2f} "
                f"(mean_dmu={statistics.fmean(r['d_mu'] for r in cr):+.2f} "
                f"mean_-3ds={statistics.fmean(r['m3dsig'] for r in cr):+.2f})  pred {pred}"
            )


if __name__ == "__main__":
    asyncio.run(main())
