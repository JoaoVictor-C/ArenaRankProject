"""What-if simulator for rating params — NON-destructive, no DB writes.

Replays the stored matches in chronological order through the pure
``arena.rating.rate()`` engine entirely IN MEMORY, under a matrix of candidate
:class:`RatingParams`, and prints the resulting CR / sigma / cr_delta
distribution for each. Lets us quantify a proposed recalibration (e.g. Trinity's)
BEFORE applying it to the database via ``rerate_matches.py``.

Note on the display multiplier ``k`` (CR = mu - k*sigma + offset): the only
feedback from CR back into the engine is ``soft_cap_factor``, which is inert
unless CR > 5000 (never in this dataset). So the (mu, sigma) trajectory is
independent of ``k`` — we therefore sweep ``k`` as a cheap post-process on each
engine trajectory rather than re-running the engine per ``k``.

Run (cwd backend):
    DATABASE_URL=postgresql+asyncpg://arena:arena@localhost:5433/arena \
      python -m scripts.sim_params
"""

from __future__ import annotations

import asyncio
import statistics
from dataclasses import replace

from sqlalchemy import select

from arena.db import models as m
from arena.db.session import get_sessionmaker
from arena.integrity.evaluators import evaluate_premade
from arena.integrity.fingerprint import subteam_pair_keys
from arena.integrity.params import DEFAULT_INTEGRITY_PARAMS
from arena.integrity.types import MatchSnapshot, ParticipantSnapshot
from arena.rating import (
    MatchInput,
    ParticipantInput,
    PlayerState,
    RatingParams,
    TeamInput,
    rate,
)
from arena.rating.params import DEFAULT_PARAMS

# --- candidate variants (engine-level; display k swept separately) ------------
# Each entry: label -> RatingParams. Keep `baseline` first to validate the sim
# against the known production BEFORE numbers.
VARIANTS: dict[str, RatingParams] = {
    "baseline": DEFAULT_PARAMS,
    # Reconciled bundle (Trinity R2/R5 + sim σ0-reduction, viable because we re-rate):
    #   σ0 350→200 (fix 1-game cohort at source), β=σ0/2, τ 3.5→1.5 (let σ converge),
    #   placement_amp 2→1 (kill μ-doubling), revert C1 → flat cap (ref=σ0 so it binds),
    #   streak loss-floor 0.25→0.5 (symmetry). Display kept μ−3σ+250 (honest once σ converges).
    "FINAL_s200_cap80": replace(
        DEFAULT_PARAMS,
        sigma0=200.0,
        beta=100.0,
        tau=1.5,
        placement_amp=1.0,
        max_delta_mu=80.0,
        dispersion_sigma_ref=200.0,
        streak_loss_floor=0.5,
    ),
    "FINAL_s200_cap60": replace(
        DEFAULT_PARAMS,
        sigma0=200.0,
        beta=100.0,
        tau=1.5,
        placement_amp=1.0,
        max_delta_mu=60.0,
        dispersion_sigma_ref=200.0,
        streak_loss_floor=0.5,
    ),
    # More conservative new-player display (σ0=250 → initial CR=500 vs 650).
    "FINAL_s250_cap80": replace(
        DEFAULT_PARAMS,
        sigma0=250.0,
        beta=125.0,
        tau=1.5,
        placement_amp=1.0,
        max_delta_mu=80.0,
        dispersion_sigma_ref=250.0,
        streak_loss_floor=0.5,
    ),
}

# Display multipliers to sweep: CR = (mu - k*sigma)*scale + offset.
K_SWEEP = (3.0,)


def _to_cr(mu: float, sigma: float, k: float, scale: float, offset: float) -> float:
    return (mu - k * sigma) * scale + offset


def _initial(player_id: str, p: RatingParams, k: float) -> PlayerState:
    cr = _to_cr(p.mu0, p.sigma0, k, p.scale_factor, p.base_offset)
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


def _simulate(
    replay: list[list[tuple[str, int, int]]],
    p: RatingParams,
    k: float,
    *,
    model_premades: bool = True,
) -> tuple[list[float], list[float], dict[str, PlayerState], list[float], list[float]]:
    """Replay `replay` through the engine for params `p`, display `k`.

    Returns ``(finals, deltas, states, solo_deltas, premade_deltas)``. When
    ``model_premades`` is set, premades are inferred from an incremental
    co-occurrence counter (a pair's count rises each time it shares a subteam, and
    the current match is included before scoring — mirroring the Redis store's
    observe-then-count), and each eligible cr_delta is bucketed solo vs premade.
    """
    states: dict[str, PlayerState] = {}
    deltas: list[float] = []
    solo_deltas: list[float] = []
    premade_deltas: list[float] = []
    pair_counts: dict[str, int] = {}
    for parts in replay:  # parts: list[(player_id, team_id, placement)]
        # build teams
        by_team: dict[int, list[tuple[str, int]]] = {}
        placement_by_team: dict[int, int] = {}
        for pid, team_id, placement in parts:
            by_team.setdefault(team_id, []).append((pid, placement))
            placement_by_team[team_id] = placement
            if pid not in states:
                states[pid] = _initial(pid, p, k)

        # Premade factors: bump co-occurrence (this match included), then score.
        factors: dict[str, float] = {}
        if model_premades:
            for _tid, members in by_team.items():
                for pk in subteam_pair_keys([pid for pid, _pl in members]):
                    pair_counts[pk] = pair_counts.get(pk, 0) + 1
            snap = MatchSnapshot(
                match_id="sim",
                mode="TRIOS",
                team_size=3,
                duration_seconds=600,
                participants=[
                    ParticipantSnapshot(
                        player_id=pid, team_id=tid, champion_id=0, cr=states[pid].cr
                    )
                    for tid, members in by_team.items()
                    for pid, _pl in members
                ],
            )
            factors = evaluate_premade(snap, pair_counts, DEFAULT_INTEGRITY_PARAMS)

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
                        is_premade=factors.get(pid, 0.0) > 0.0,
                        party_id=None,
                        boosting_penalty_factor=0.0,
                        party_penalty_factor=factors.get(pid, 0.0),
                    )
                    for pid, _pl in members
                ],
            )
            for tid, members in by_team.items()
        ]
        result = rate(MatchInput(match_id="sim", mode="TRIOS", teams=teams, params=p))
        for pr in result.players:
            # recompute CR with display k (engine's pr.cr_* use hardcoded 3.0)
            cr_before = _to_cr(pr.mu_before, pr.sigma_before, k, p.scale_factor, p.base_offset)
            cr_after = _to_cr(pr.mu_after, pr.sigma_after, k, p.scale_factor, p.base_offset)
            if pr.eligible:
                d = cr_after - cr_before
                deltas.append(d)
                (premade_deltas if factors.get(pr.player_id, 0.0) > 0.0 else solo_deltas).append(d)
            st = states[pr.player_id]
            states[pr.player_id] = replace(
                st,
                mu=pr.mu_after,
                sigma=pr.sigma_after,
                cr=cr_after,
                current_streak=pr.new_streak,
                matches_played=st.matches_played + 1,
                placement_matches_remaining=max(0, st.placement_matches_remaining - 1),
                peak_cr=max(st.peak_cr, cr_after),
            )
    finals = [_to_cr(s.mu, s.sigma, k, p.scale_factor, p.base_offset) for s in states.values()]
    return finals, deltas, states, solo_deltas, premade_deltas


def _fmt(finals: list[float], deltas: list[float], states_sigma: list[float] | None = None) -> str:
    n = len(finals)
    neg = sum(1 for c in finals if c < 0)
    finals_s = sorted(finals)
    p50 = finals_s[n // 2]
    dmin = min(deltas) if deltas else 0.0
    dmax = max(deltas) if deltas else 0.0
    dsd = statistics.pstdev(deltas) if len(deltas) > 1 else 0.0
    dmean = statistics.fmean(deltas) if deltas else 0.0
    return (
        f"neg={neg:4d}/{n} ({100 * neg / n:4.1f}%)  "
        f"crMin={min(finals):7.1f} crMed={p50:6.1f} crMax={max(finals):7.1f}  "
        f"d:min={dmin:7.1f} max={dmax:6.1f} mean={dmean:5.1f} sd={dsd:5.1f}"
    )


def _fmt_split(solo: list[float], premade: list[float]) -> str:
    """Solo-vs-premade WIN comparison (positive deltas only — the dampener is gains-only)."""
    solo_w = [d for d in solo if d > 0]
    prem_w = [d for d in premade if d > 0]
    solo_m = statistics.fmean(solo_w) if solo_w else 0.0
    prem_m = statistics.fmean(prem_w) if prem_w else 0.0
    gap = (prem_m - solo_m) / solo_m * 100 if solo_m else 0.0
    return (
        f"  win cr_delta: solo n={len(solo_w):5d} mean={solo_m:5.1f}  "
        f"premade n={len(prem_w):5d} mean={prem_m:5.1f}  premade vs solo {gap:+5.1f}%"
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

    print(
        f"season={season_id}  matches={len(replay)}  participations={sum(len(r) for r in replay)}\n"
    )
    header = f"{'variant':18s} {'k':>4s}  result"
    print(header)
    print("-" * len(header) + "-" * 40)
    for label, p in VARIANTS.items():
        for k in K_SWEEP:
            finals, deltas, _, solo_d, premade_d = _simulate(replay, p, k)
            print(f"{label:18s} {k:>4.1f}  {_fmt(finals, deltas)}")
            print(f"{'':18s} {'':>4s}  {_fmt_split(solo_d, premade_d)}")
        print()

    # σ-convergence detail for the leading final (invariant 2): final σ binned by
    # games played — must drop well below σ0 for the multi-game cohort.
    lead = "FINAL_s200_cap80"
    _, _, states, _, _ = _simulate(replay, VARIANTS[lead], 3.0)
    buckets: dict[int, list[float]] = {}
    for st in states.values():
        buckets.setdefault(st.matches_played, []).append(st.sigma)
    print(f"σ-by-games for {lead} (σ0={VARIANTS[lead].sigma0:.0f}):")
    for g in sorted(buckets):
        if g > 12:
            break
        sigs = buckets[g]
        print(f"  games={g:2d} n={len(sigs):4d} avg_sigma={statistics.fmean(sigs):6.1f}")


if __name__ == "__main__":
    asyncio.run(main())
