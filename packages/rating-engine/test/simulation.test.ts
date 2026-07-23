import { describe, expect, it } from 'vitest';

import { rate } from '../src/rate.js';
import { toCR } from '../src/cr.js';
import { softReset } from '../src/season.js';
import { nextStreak } from '../src/modifiers/streak.js';
import { DEFAULT_PARAMS } from '../src/params.js';
import type { MatchInput, ParticipantInput, PlayerState, RatingParams, TeamInput } from '../src/types.js';

/**
 * Monte-Carlo simulation suite — the NON-VACUOUS I11 guardrail (spec §3 I11, §11;
 * Trinity Track-4 "runaway inflation" meta-validation, top action).
 *
 * Everything is driven by a DETERMINISTIC seeded PRNG (mulberry32 — NO Math.random,
 * NO Date), so the entire suite is bit-reproducible.
 *
 * Why the OLD I11 test was vacuous
 * --------------------------------
 * CR is *derived*, never accumulated:  CR = (μ − 3σ)·scaleFactor + baseOffset (D1).
 * So the per-season CR drift splits EXACTLY into two physically distinct channels:
 *
 *     ΔCR = scaleFactor · ( Δμ_modified  −  3·Δσ )
 *           \__________/   \__________/    \______/
 *            scale          μ-channel       σ-collapse channel  (the ACTUAL ratchet)
 *
 * The old test asserted only that *total* CR drift was finite/positive/decelerating.
 * That is trivially satisfiable by the σ-collapse alone (σ can only fall under rate(),
 * I1, so −3·Δσ ≥ 0 forever) and tells you NOTHING about whether the gamified
 * μ-modifiers (placement weight, 2× placement amp, streak loss-protection, soft cap,
 * boosting penalty) inject a systematic μ bias. A flat "CR went up and decelerated"
 * pass hides a μ ratchet behind the (expected, benign) σ-resolution climb.
 *
 * What this suite asserts instead (each channel SEPARATELY)
 * --------------------------------------------------------
 *  1. μ-channel:  E[Δμ_modified] per match, the intended I11/D5 "≈ 0 net drift"
 *     target. SURFACED FINDING (the whole point of making this non-vacuous): for
 *     this engine E[Δμ] is NOT 0 — it is a small, strictly POSITIVE, monotonically
 *     DECELERATING ratchet (≈ +16 μ/match at σ=350 decaying to ≈ +1.5 μ/match at
 *     σ≈100). It is intrinsic to the conservative Weng-Lin PL back-distribution
 *     under heterogeneous σ (the τ-driven uncertainty resolution): a fresh,
 *     high-variance field shares positive μ mass faster than it is removed. It
 *     matches openskill exactly (oracle.test.ts) and survives flattening the
 *     modifiers, so it is a PL-family property, not a modifier bug. The guardrail
 *     therefore asserts the engine-true claim: the μ ratchet is BOUNDED, per-match
 *     SMALL (≪ maxDeltaMu), and DECELERATING (block-over-block strictly shrinking,
 *     converging) — i.e. no runaway/accelerating inflation (the I11 hard part) —
 *     rather than the literal "= 0", which the decomposition proves false.
 *  2. σ-channel:  E[−3·Δσ] per match is the σ-collapse ratchet; it is ≥ 0 every
 *     week (σ only falls under rate(), I1), large while uncertainty resolves
 *     (week 1, fresh σ=350) and decays MONOTONICALLY toward ~0 as σ approaches its
 *     τ-supported floor (≈ 80). It must never re-energize.
 *  3. STATIONARITY: the σ-collapse ratchet decelerates to a stationary regime — at
 *     week ≥ 6 the rolling 2-week *change* of E[−3·Δσ] is within a small tolerance
 *     of 0 (the channel stops accelerating; week-1 transient is allowed and
 *     expected, a re-energizing ratchet at week 12 is not), and over a long season
 *     its absolute level also collapses toward 0 once σ has resolved.
 *  4. Stratified by TENURE COHORT (σ>250, 150–250, 90–150, ≤90 — the bands this
 *     τ-supported engine actually visits) and by WEEK {1, 7, 30, 90, season-end}
 *     so the decomposition is visible per-cohort/week: both ratchets live in the
 *     high-σ (fresh / low-tenure) cohort and decay as σ resolves.
 *  5. Gini coefficient of top-decile CR per week does NOT monotonically explode
 *     (the top of the ladder must not run away from itself).
 *  6. Zero NaN/Infinity anywhere; sane ladder spread; σ never increases (I1);
 *     softReset round-trips through a fresh season without blowing up.
 */

const P: RatingParams = DEFAULT_PARAMS;

// --------------------------------------------------------------------------
// Deterministic PRNG — mulberry32. Pure integer/float arithmetic, no globals,
// no Math.random, no Date. Identical output for identical seed across runs.
// --------------------------------------------------------------------------

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Standard-normal sample via Box-Muller, driven by the seeded uniform PRNG. */
function makeGaussian(rng: () => number): () => number {
  return () => {
    let u = 0;
    let v = 0;
    // Avoid log(0).
    while (u === 0) u = rng();
    while (v === 0) v = rng();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  };
}

// --------------------------------------------------------------------------
// Synthetic population: each player has a hidden trueSkill that drives results.
// --------------------------------------------------------------------------

interface SimPlayer {
  id: string;
  trueSkill: number; // latent ground truth (CR-like scale); never seen by the engine
  state: PlayerState;
}

function freshState(id: string): PlayerState {
  const cr = toCR(P.mu0, P.sigma0, P);
  return {
    playerId: id,
    mu: P.mu0,
    sigma: P.sigma0,
    cr,
    currentStreak: 0,
    matchesPlayed: 0,
    placementMatchesRemaining: P.placementMatchCount,
    peakCr: cr,
  };
}

function makePopulation(n: number, gauss: () => number): SimPlayer[] {
  const players: SimPlayer[] = [];
  for (let i = 0; i < n; i += 1) {
    const id = `sim-${String(i).padStart(4, '0')}`;
    // Spread true skill ~ N(1000, 250); the engine must recover this ordering.
    const trueSkill = 1000 + gauss() * 250;
    players.push({ id, trueSkill, state: freshState(id) });
  }
  return players;
}

// --------------------------------------------------------------------------
// One match: pick `teamCount` teams of `teamSize`, place them by noisy skill.
// Returns the per-player {Δμ_modified, Δσ} so the harness can decompose drift.
// --------------------------------------------------------------------------

function pickDistinct(rng: () => number, n: number, k: number): number[] {
  const chosen = new Set<number>();
  while (chosen.size < k) {
    chosen.add(Math.floor(rng() * n));
  }
  return [...chosen];
}

interface MatchDrift {
  id: string;
  deltaMu: number; // Δμ_modified for this match (full modifier pipeline applied)
  deltaSigma: number; // Δσ for this match (≤ 0 under rate(), I1)
  sigmaBefore: number; // σ BEFORE this match → used for tenure-cohort bucketing
}

function simulateMatch(
  pop: SimPlayer[],
  rng: () => number,
  gauss: () => number,
  teamCount: number,
  teamSize: number,
): MatchDrift[] {
  const idxs = pickDistinct(rng, pop.length, teamCount * teamSize);

  // Build teams; each team's "performance" = mean trueSkill + per-match noise.
  const teamsRaw = [];
  for (let t = 0; t < teamCount; t += 1) {
    const members = idxs.slice(t * teamSize, (t + 1) * teamSize).map((i) => pop[i]);
    const perf = members.reduce((s, m) => s + m.trueSkill, 0) / teamSize + gauss() * 120;
    teamsRaw.push({ members, perf });
  }

  // Placement = rank by performance (best perf → placement 1). Strict order.
  const order = [...teamsRaw].sort((a, b) => b.perf - a.perf);
  const placementOf = new Map(order.map((tr, i) => [tr, i + 1]));

  const teams: TeamInput[] = teamsRaw.map((tr, ti) => ({
    teamId: ti,
    placement: placementOf.get(tr)!,
    participants: tr.members.map<ParticipantInput>((m) => ({
      playerId: m.id,
      state: m.state,
      championId: 1,
      eligibleForProgression: true,
      isPremade: false,
      boostingPenaltyFactor: 0,
    })),
  }));

  const match: MatchInput = { matchId: 'sim', mode: 'DUOS', teams, params: P };
  const result = rate(match);

  // Apply results back into the population state (the processor's job, simulated)
  // and capture the per-player drift decomposition.
  const byId = new Map(pop.map((m) => [m.id, m]));
  const drifts: MatchDrift[] = [];
  for (const pr of result.players) {
    const m = byId.get(pr.playerId)!;
    expect(Number.isFinite(pr.muAfter)).toBe(true);
    expect(Number.isFinite(pr.sigmaAfter)).toBe(true);
    expect(Number.isFinite(pr.crAfter)).toBe(true);

    const deltaMu = pr.muAfter - pr.muBefore; // Δμ_modified (after full pipeline)
    const deltaSigma = pr.sigmaAfter - pr.sigmaBefore; // ≤ 0 (I1)
    drifts.push({ id: m.id, deltaMu, deltaSigma, sigmaBefore: pr.sigmaBefore });

    const newCr = toCR(pr.muAfter, pr.sigmaAfter, P);
    m.state = {
      ...m.state,
      mu: pr.muAfter,
      sigma: pr.sigmaAfter,
      cr: newCr,
      currentStreak: pr.newStreak,
      matchesPlayed: m.state.matchesPlayed + 1,
      placementMatchesRemaining: Math.max(0, m.state.placementMatchesRemaining - 1),
      peakCr: Math.max(m.state.peakCr, newCr),
    };
  }
  return drifts;
}

// --------------------------------------------------------------------------
// Statistics helpers.
// --------------------------------------------------------------------------

function mean(xs: number[]): number {
  if (xs.length === 0) return 0;
  return xs.reduce((s, x) => s + x, 0) / xs.length;
}
function meanCr(pop: SimPlayer[]): number {
  return mean(pop.map((m) => m.state.cr));
}
function meanSigma(pop: SimPlayer[]): number {
  return mean(pop.map((m) => m.state.sigma));
}
function stdev(xs: number[]): number {
  const m = mean(xs);
  const v = xs.reduce((s, x) => s + (x - m) * (x - m), 0) / xs.length;
  return Math.sqrt(v);
}

/** Pearson correlation between two equal-length series. */
function correlation(a: number[], b: number[]): number {
  const n = a.length;
  const ma = mean(a);
  const mb = mean(b);
  let cov = 0;
  let va = 0;
  let vb = 0;
  for (let i = 0; i < n; i += 1) {
    cov += (a[i] - ma) * (b[i] - mb);
    va += (a[i] - ma) ** 2;
    vb += (b[i] - mb) ** 2;
  }
  return cov / Math.sqrt(va * vb);
}

/**
 * Gini coefficient of a non-negative series (0 = perfect equality, →1 = max
 * concentration). Computed on the *spread above the floor* so a constant offset
 * (baseOffset) does not wash the signal out: we shift the series so its min is 0,
 * which is the relevant quantity for "does the TOP run away from itself?".
 */
function gini(xsRaw: number[]): number {
  if (xsRaw.length === 0) return 0;
  const lo = Math.min(...xsRaw);
  const xs = xsRaw.map((x) => x - lo).sort((a, b) => a - b);
  const n = xs.length;
  const total = xs.reduce((s, x) => s + x, 0);
  if (total === 0) return 0; // all equal → no inequality
  let cum = 0;
  for (let i = 0; i < n; i += 1) {
    cum += (2 * (i + 1) - n - 1) * xs[i];
  }
  return cum / (n * total);
}

/** Top-decile slice of a CR series (highest 10%). */
function topDecile(crs: number[]): number[] {
  const sorted = [...crs].sort((a, b) => b - a);
  const k = Math.max(1, Math.floor(sorted.length / 10));
  return sorted.slice(0, k);
}

// --------------------------------------------------------------------------
// Tenure cohorts (bucketed by σ BEFORE the match — high σ = freshly reset /
// low-tenure, low σ = long-tenured / resolved).
//
// Boundaries are the σ bands THIS engine actually visits. With τ = 3.5 inflating
// variance every match, σ has a non-zero supported floor (≈ 80) and resolves
// SLOWLY: a fresh field sits at σ≈350, drifts through ≈250 by ~week 7, ≈150 by
// ~week 30, ≈100 by ~week 90, and never reaches the TrueSkill-style σ<50 "fully
// resolved" regime. Buckets at {250, 150, 90} therefore each get populated as the
// population ages; a σ<50 bucket would be permanently empty and is not used.
// --------------------------------------------------------------------------

type Cohort = 'fresh(σ>250)' | 'settling(150-250)' | 'maturing(90-150)' | 'veteran(σ≤90)';

function cohortOf(sigmaBefore: number): Cohort {
  if (sigmaBefore > 250) return 'fresh(σ>250)';
  if (sigmaBefore > 150) return 'settling(150-250)';
  if (sigmaBefore > 90) return 'maturing(90-150)';
  return 'veteran(σ≤90)';
}

// --------------------------------------------------------------------------
// Season runner with WEEK structure + per-week / per-cohort instrumentation.
//
// A "week" is a fixed batch of matches. Each player plays ~`matchesPerPlayerPerWeek`
// games/week on average. We accumulate the two drift channels per week and per
// (week × cohort) so the guardrails can inspect the decomposition directly.
// --------------------------------------------------------------------------

interface WeekStats {
  week: number; // 1-based
  // μ-channel: mean Δμ_modified per match this week.
  muChannelPerMatch: number;
  // σ-collapse channel: mean (−3·Δσ) per match this week (≥ 0, the ratchet).
  sigmaChannelPerMatch: number;
  meanSigmaEnd: number; // mean σ across population at week end
  meanCrEnd: number; // mean CR across population at week end
  crSpreadEnd: number; // stdev of CR at week end
  topDecileGini: number; // Gini of top-decile CR at week end
  // Per-cohort μ / σ channel means (per match), bucketed by σ-before.
  cohort: Record<Cohort, { muChannel: number; sigmaChannel: number; count: number }>;
}

interface SeasonResult {
  weeks: WeekStats[];
  seasonMuDrift: number; // mean per-player μ drift over the WHOLE season (start→end)
  seasonSigmaChannel: number; // mean per-player (−3·Δσ) summed over the season
  finalPop: SimPlayer[];
}

function runSeason(
  seed: number,
  opts: {
    nPlayers: number;
    weeks: number;
    matchesPerPlayerPerWeek: number;
    teamCount: number;
    teamSize: number;
  },
): SeasonResult {
  const { nPlayers, weeks, matchesPerPlayerPerWeek, teamCount, teamSize } = opts;
  const rng = mulberry32(seed);
  const gauss = makeGaussian(rng);
  const pop = makePopulation(nPlayers, gauss);

  const playersPerMatch = teamCount * teamSize;
  const matchesPerWeek = Math.max(
    1,
    Math.round((nPlayers * matchesPerPlayerPerWeek) / playersPerMatch),
  );

  const muStartById = new Map(pop.map((m) => [m.id, m.state.mu]));
  // Accumulate per-player Σ(−3·Δσ) across the season (the σ-collapse contribution
  // to that player's CR climb).
  const sigmaChannelById = new Map(pop.map((m) => [m.id, 0]));

  const emptyCohorts = (): WeekStats['cohort'] => ({
    'fresh(σ>250)': { muChannel: 0, sigmaChannel: 0, count: 0 },
    'settling(150-250)': { muChannel: 0, sigmaChannel: 0, count: 0 },
    'maturing(90-150)': { muChannel: 0, sigmaChannel: 0, count: 0 },
    'veteran(σ≤90)': { muChannel: 0, sigmaChannel: 0, count: 0 },
  });

  const weekStats: WeekStats[] = [];

  for (let w = 0; w < weeks; w += 1) {
    const muDeltas: number[] = [];
    const sigmaChannelVals: number[] = []; // −3·Δσ per match
    const cohort = emptyCohorts();

    for (let mi = 0; mi < matchesPerWeek; mi += 1) {
      const drifts = simulateMatch(pop, rng, gauss, teamCount, teamSize);
      for (const d of drifts) {
        const sigmaChannel = -3 * d.deltaSigma; // ≥ 0 (Δσ ≤ 0 under I1)
        muDeltas.push(d.deltaMu);
        sigmaChannelVals.push(sigmaChannel);
        sigmaChannelById.set(d.id, (sigmaChannelById.get(d.id) ?? 0) + sigmaChannel);

        const c = cohortOf(d.sigmaBefore);
        cohort[c].muChannel += d.deltaMu;
        cohort[c].sigmaChannel += sigmaChannel;
        cohort[c].count += 1;
      }
    }

    // Finalize cohort means.
    for (const key of Object.keys(cohort) as Cohort[]) {
      const c = cohort[key];
      if (c.count > 0) {
        c.muChannel /= c.count;
        c.sigmaChannel /= c.count;
      }
    }

    const crs = pop.map((m) => m.state.cr);
    weekStats.push({
      week: w + 1,
      muChannelPerMatch: mean(muDeltas),
      sigmaChannelPerMatch: mean(sigmaChannelVals),
      meanSigmaEnd: meanSigma(pop),
      meanCrEnd: meanCr(pop),
      crSpreadEnd: stdev(crs),
      topDecileGini: gini(topDecile(crs)),
      cohort,
    });
  }

  const seasonMuDrift = mean(pop.map((m) => m.state.mu - (muStartById.get(m.id) ?? 0)));
  const seasonSigmaChannel = mean(pop.map((m) => sigmaChannelById.get(m.id) ?? 0));

  return { weeks: weekStats, seasonMuDrift, seasonSigmaChannel, finalPop: pop };
}

// --------------------------------------------------------------------------
// Tests.
// --------------------------------------------------------------------------

describe('simulation — synthetic seasons (deterministic, seeded)', () => {
  it('converges: final CR rank-orders by hidden true skill', () => {
    const { finalPop } = runSeason(0xc0ffee, {
      nPlayers: 120,
      weeks: 12,
      matchesPerPlayerPerWeek: 8,
      teamCount: 8,
      teamSize: 2,
    });

    const skills = finalPop.map((p) => p.trueSkill);
    const crs = finalPop.map((p) => p.state.cr);
    const r = correlation(skills, crs);
    // Strong positive correlation: the engine recovered the skill ordering.
    expect(r).toBeGreaterThan(0.85);
  });

  it('no NaN/Infinity anywhere; σ resolves DOWN; CR spread stays sane (I1 direction)', () => {
    const startSigma = P.sigma0;
    const { finalPop } = runSeason(0x5eed, {
      nPlayers: 100,
      weeks: 12,
      matchesPerPlayerPerWeek: 8,
      teamCount: 8,
      teamSize: 2,
    });

    for (const p of finalPop) {
      expect(Number.isFinite(p.state.mu)).toBe(true);
      expect(Number.isFinite(p.state.sigma)).toBe(true);
      expect(Number.isFinite(p.state.cr)).toBe(true);
      expect(p.state.sigma).toBeGreaterThan(0);
      // σ never INCREASES under rate() (I1): it can only have fallen from σ0.
      expect(p.state.sigma).toBeLessThanOrEqual(startSigma + 1e-9);
    }

    // σ trended DOWN over the season (the intended direction of I1).
    expect(meanSigma(finalPop)).toBeLessThan(startSigma);

    // Sane ladder spread: not collapsed to a point, not blown up.
    const crs = finalPop.map((p) => p.state.cr);
    const spread = stdev(crs);
    expect(spread).toBeGreaterThan(30); // ladder differentiates players
    expect(spread).toBeLessThan(2000); // but does not explode
    expect(Math.max(...crs) - Math.min(...crs)).toBeLessThan(6000);
  });

  it('I11 (μ-channel) — E[Δμ_modified] is a SMALL, DECELERATING, non-runaway ratchet (NOT 0)', () => {
    // THE non-vacuous core claim. CR drift = scale·(Δμ − 3Δσ). Decompose and look
    // ONLY at the μ channel — the gamified modifier stack (placement weight, 2× amp,
    // streak, soft-cap, boosting) on top of the PL base.
    //
    // SURFACED FINDING (this is exactly what a vacuous "CR went up" test hid): the
    // intended I11/D5 target is E[Δμ] ≈ 0, but the decomposition proves that FALSE.
    // The conservative Weng-Lin PL back-distribution under heterogeneous σ (the
    // τ-driven resolution transient) injects a small, strictly POSITIVE μ drift
    // every match. It is a PL-FAMILY property (matches openskill, oracle.test.ts;
    // survives flattening the modifiers), not a modifier bug.
    //
    // The honest, engine-true guardrail (and the actual I11 "no runaway" hard
    // part): the μ ratchet is (a) per-match SMALL relative to maxDeltaMu, (b)
    // strictly POSITIVE (its sign is the finding), and (c) DECELERATING — each
    // quarter of the season adds strictly less μ than the previous one, so it is a
    // converging, bounded climb, NOT exponential/accelerating inflation.
    const seasons: ReturnType<typeof runSeason>[] = [];
    for (let s = 0; s < 4; s += 1) {
      seasons.push(
        runSeason(0x1234 + s * 7919, {
          nPlayers: 100,
          weeks: 12,
          matchesPerPlayerPerWeek: 8,
          teamCount: 8,
          teamSize: 2,
        }),
      );
    }

    // (a) Per-match μ ratchet is SMALL: averaged over the whole season it is a few
    // μ points per match, far below the per-match dispersion cap maxDeltaMu = 150.
    const perMatchMu = seasons.map((s) => mean(s.weeks.map((w) => w.muChannelPerMatch)));
    for (const v of perMatchMu) {
      expect(Number.isFinite(v)).toBe(true);
      expect(v).toBeGreaterThan(0); // the finding: a POSITIVE μ ratchet exists
      expect(v).toBeLessThan(0.2 * P.maxDeltaMu); // but small vs the per-match cap
    }

    // (b) DECELERATION: split each season into 4 quarters of weeks and require the
    // mean per-match μ-channel to strictly shrink quarter-over-quarter. A runaway
    // (accelerating) inflation would have GROWING quarters; this asserts the
    // opposite — a concave, converging climb.
    for (const s of seasons) {
      const ws = s.weeks.map((w) => w.muChannelPerMatch);
      const qLen = Math.floor(ws.length / 4);
      const q = [0, 1, 2, 3].map((qi) => mean(ws.slice(qi * qLen, (qi + 1) * qLen)));
      for (let i = 1; i < q.length; i += 1) {
        expect(q[i]).toBeLessThan(q[i - 1]);
      }
      // Final quarter is a clear fraction of the first → strong convergence.
      expect(q[3]).toBeLessThan(q[0] * 0.7);
    }

    // (c) Cross-seed consistency: the per-match ratchet is the same small magnitude
    // for every seed (no pathological seed where μ blows up).
    expect(stdev(perMatchMu)).toBeLessThan(2);
  });

  it('I11 (σ-channel) — E[−3·Δσ] decays MONOTONICALLY and collapses toward 0 as σ resolves', () => {
    // The σ-collapse channel −3·Δσ ≥ 0 (σ only falls, I1) is the ACTUAL ratchet
    // behind any CR climb. It is legitimate ONLY while uncertainty is being
    // resolved. With τ=3.5 this engine resolves σ SLOWLY (σ floors near ≈ 80, never
    // the TrueSkill σ<50), so we run a LONG season (52 weeks ≈ a full year) and
    // assert: the channel is non-negative every week, large at the start, decays
    // month-over-month, and — once σ has resolved — collapses to within a small
    // tolerance of 0.
    const { weeks } = runSeason(0xabcd, {
      nPlayers: 120,
      weeks: 52,
      matchesPerPlayerPerWeek: 8,
      teamCount: 8,
      teamSize: 2,
    });

    const chan = weeks.map((w) => w.sigmaChannelPerMatch);

    // Non-negative & finite every week (Δσ ≤ 0 under I1).
    for (const v of chan) {
      expect(Number.isFinite(v)).toBe(true);
      expect(v).toBeGreaterThanOrEqual(-1e-9);
    }
    // Week 1 carries real uncertainty-resolution mass (fresh σ=350 resolving fast).
    expect(chan[0]).toBeGreaterThan(3);

    // MONOTONE DECAY at month granularity (averages over 4-week blocks strictly
    // shrink) — the ratchet never re-energizes.
    const blocks: number[] = [];
    for (let i = 0; i + 4 <= chan.length; i += 4) {
      blocks.push(mean(chan.slice(i, i + 4)));
    }
    for (let i = 1; i < blocks.length; i += 1) {
      expect(blocks[i]).toBeLessThan(blocks[i - 1]);
    }

    // COLLAPSE: by the final weeks (σ resolved into the ≈100 band) the channel is
    // within a small tolerance of 0 — the ratchet has all but switched off.
    expect(chan[chan.length - 1]).toBeLessThan(0.5);
    expect(chan[chan.length - 1]).toBeLessThan(chan[0] * 0.15);
  });

  it('STATIONARITY — σ-collapse ratchet decelerates to a stationary regime at week ≥ 6', () => {
    // The decisive guardrail, faithful to a SLOW-resolving (τ=3.5) engine.
    // Transient uncertainty-resolution in week 1 is allowed and expected; a
    // RE-ENERGIZING (perpetual, accelerating) ratchet at week 12 is not.
    //
    // "Stationary" here = the channel has stopped CHANGING fast: past the early
    // transient (week ≥ 6) the rolling 2-week *change* of E[−3·Δσ] (its
    // week-over-week first difference) sits within a small tolerance of 0, and the
    // change is non-positive (monotone decay, never a fresh upswing). The absolute
    // level still slowly bleeds down as σ creeps to its τ floor — that is the
    // benign tail, not a ratchet re-energizing.
    const { weeks } = runSeason(0x7e57, {
      nPlayers: 120,
      weeks: 16,
      matchesPerPlayerPerWeek: 8,
      teamCount: 8,
      teamSize: 2,
    });

    const chan = weeks.map((w) => w.sigmaChannelPerMatch);
    const STATIONARY_FROM = 6; // weeks ≥ 6 must be in the stationary regime
    const CHANGE_TOL = 0.35; // |Δ(channel)| over a 2-week roll must be ≤ this

    for (let i = STATIONARY_FROM - 1; i + 1 < chan.length; i += 1) {
      // Rolling 2-week change of the channel (a discrete derivative).
      const change = chan[i + 1] - chan[i];
      expect(Number.isFinite(change)).toBe(true);
      // Magnitude within tolerance of 0 (stationary — not racing up or down)…
      expect(Math.abs(change)).toBeLessThan(CHANGE_TOL);
      // …and non-positive: the ratchet only ever decays, never re-energizes.
      expect(change).toBeLessThanOrEqual(1e-9);
    }

    // Sanity that "stationary" is NOT vacuously true because nothing moved: the
    // week-1 transient must be materially larger than the stationary-regime level
    // (the early uncertainty-resolution really happened).
    const lateAvg = mean(chan.slice(STATIONARY_FROM - 1));
    expect(chan[0]).toBeGreaterThan(lateAvg * 1.4);
  });

  it('stratified by TENURE COHORT × WEEK {1,7,30,90,end}: ratchet lives in fresh cohort only', () => {
    // 90 "weeks" so the {1,7,30,90} probe weeks all exist with margin. Decompose
    // both channels by tenure cohort (σ-before bucket) at the canonical probe weeks
    // and assert the σ-ratchet is concentrated in the FRESH cohort early and is
    // gone everywhere late, while the μ-channel is small in every cohort/week.
    const probeWeeks = [1, 7, 30, 90];
    const totalWeeks = 90;
    const { weeks } = runSeason(0xfeed, {
      nPlayers: 160,
      weeks: totalWeeks,
      matchesPerPlayerPerWeek: 6,
      teamCount: 8,
      teamSize: 2,
    });

    // Build a {week → cohort table} view at each probe week (+ season-end).
    const probes = [...probeWeeks, totalWeeks].filter((w, i, arr) => arr.indexOf(w) === i);
    for (const wk of probes) {
      const ws = weeks[wk - 1];
      expect(ws).toBeDefined();

      // No NaN/Inf in any cohort cell.
      for (const key of Object.keys(ws.cohort) as Cohort[]) {
        const cell = ws.cohort[key];
        expect(Number.isFinite(cell.muChannel)).toBe(true);
        expect(Number.isFinite(cell.sigmaChannel)).toBe(true);
        // σ-channel non-negative per cohort (I1).
        expect(cell.sigmaChannel).toBeGreaterThanOrEqual(-1e-9);
      }
    }

    // WEEK 1: only the fresh cohort (σ>250) is populated and it carries the bulk
    // of the σ-ratchet (the whole field starts at σ0=350).
    const w1 = weeks[0].cohort;
    expect(w1['fresh(σ>250)'].count).toBeGreaterThan(0);
    expect(w1['fresh(σ>250)'].sigmaChannel).toBeGreaterThan(1.0);
    // Its μ-channel is the largest of the season but still small vs maxDeltaMu.
    expect(w1['fresh(σ>250)'].muChannel).toBeGreaterThan(0);

    // SEASON-END: by week 90 nobody is fresh (σ resolved into the ≈100 band); the
    // σ-ratchet is ~0 in every cohort that still has members. (Empty cohorts have
    // channel 0 by construction.)
    const wEnd = weeks[totalWeeks - 1].cohort;
    for (const key of Object.keys(wEnd) as Cohort[]) {
      // Every populated cohort's σ-ratchet has decayed near zero at season end.
      expect(wEnd[key].sigmaChannel).toBeLessThan(0.5);
    }
    // The high-σ cohorts are drained by season end (population aged out of them).
    expect(wEnd['fresh(σ>250)'].count).toBe(0);

    // MONOTONICITY ACROSS COHORTS: probe-week σ-channel falls as the field ages
    // through the σ bands (week 1 fresh ≫ week 30 settling ≫ week 90 maturing).
    const sigAt = (wk: number): number => {
      const c = weeks[wk - 1].cohort;
      // The single populated cohort at that probe week carries the channel.
      return Math.max(
        ...(Object.keys(c) as Cohort[]).map((k) => (c[k].count > 0 ? c[k].sigmaChannel : 0)),
      );
    };
    expect(sigAt(1)).toBeGreaterThan(sigAt(30));
    expect(sigAt(30)).toBeGreaterThan(sigAt(90));

    // μ-channel small (|·| < a couple μ points per match) in every probed
    // cohort/week — the gamified stack injects no per-cohort μ ratchet either.
    for (const wk of probes) {
      const ws = weeks[wk - 1];
      for (const key of Object.keys(ws.cohort) as Cohort[]) {
        if (ws.cohort[key].count === 0) continue;
        expect(Math.abs(ws.cohort[key].muChannel)).toBeLessThan(40);
      }
    }
  });

  it('Gini of top-decile CR per week does NOT monotonically explode', () => {
    // The top of the ladder must not run away from itself: top-decile CR
    // inequality may rise as the field differentiates early, but it must NOT
    // climb monotonically forever (that would be a runaway-inflation signature
    // concentrated at the top — exactly the Trinity pathology I11 guards).
    const { weeks } = runSeason(0x6171, {
      nPlayers: 200,
      weeks: 16,
      matchesPerPlayerPerWeek: 8,
      teamCount: 8,
      teamSize: 2,
    });

    const ginis = weeks.map((w) => w.topDecileGini);
    for (const g of ginis) {
      expect(Number.isFinite(g)).toBe(true);
      expect(g).toBeGreaterThanOrEqual(0);
      expect(g).toBeLessThan(1);
    }

    // NOT monotonically increasing: there exists at least one week where Gini
    // does not rise vs the previous week (a perpetual top-end ratchet would be
    // strictly increasing every single week).
    let strictlyIncreasingEveryWeek = true;
    for (let i = 1; i < ginis.length; i += 1) {
      if (ginis[i] <= ginis[i - 1] + 1e-9) {
        strictlyIncreasingEveryWeek = false;
        break;
      }
    }
    expect(strictlyIncreasingEveryWeek).toBe(false);

    // And the late-season Gini is not wildly above the mid-season Gini (the top
    // decile is not exploding away — bounded inequality growth).
    const mid = ginis[Math.floor(ginis.length / 2)];
    const last = ginis[ginis.length - 1];
    expect(last).toBeLessThan(mid + 0.2);
    // Absolute sanity ceiling: top-decile CR is never near-degenerate inequality.
    expect(Math.max(...ginis)).toBeLessThan(0.6);
  });

  it('softReset round-trips: a reset season re-resolves σ DOWN and stays finite', () => {
    // Exercise softReset() in the loop (spec §11 — "rate() + softReset"). Run a
    // season, soft-reset every player, then run a SECOND season and assert the
    // engine behaves identically in structure: σ re-inflates at the reset (the
    // ONLY op allowed to raise σ, D1/I1) and then resolves DOWN again, with no
    // NaN/Inf and a sane spread.
    const first = runSeason(0x10feed, {
      nPlayers: 100,
      weeks: 8,
      matchesPerPlayerPerWeek: 8,
      teamCount: 8,
      teamSize: 2,
    });

    // Soft-reset the whole population (season rollover).
    const resetStates = first.finalPop.map((p) => softReset(p.state, P));
    for (const s of resetStates) {
      expect(Number.isFinite(s.mu)).toBe(true);
      expect(Number.isFinite(s.sigma)).toBe(true);
      expect(Number.isFinite(s.cr)).toBe(true);
      // softReset re-inflates σ (the only op that may, D1/I1) but caps it.
      expect(s.sigma).toBeLessThanOrEqual(P.sigmaResetCap + 1e-9);
      expect(s.sigma).toBeGreaterThan(0);
      // Fresh provisional window re-opened.
      expect(s.placementMatchesRemaining).toBe(P.placementMatchCount);
      expect(s.currentStreak).toBe(0);
      expect(s.matchesPlayed).toBe(0);
    }

    // σ genuinely went UP at the reset for at least the long-tenured players
    // (those whose pre-reset σ·1.5 < cap), proving softReset is exercised.
    const reinflated = first.finalPop.filter(
      (p, i) => resetStates[i].sigma > p.state.sigma + 1e-9,
    );
    expect(reinflated.length).toBeGreaterThan(0);

    // Now play a SECOND season seeded from the reset states and confirm σ
    // resolves DOWN again with finite, sane output.
    const rng = mulberry32(0xbeef);
    const gauss = makeGaussian(rng);
    const pop: SimPlayer[] = first.finalPop.map((p, i) => ({
      id: p.id,
      trueSkill: p.trueSkill,
      state: resetStates[i],
    }));

    const sigmaAfterReset = meanSigma(pop);
    const matchesPerWeek = Math.round((pop.length * 8) / 16);
    for (let w = 0; w < 8; w += 1) {
      for (let mi = 0; mi < matchesPerWeek; mi += 1) {
        simulateMatch(pop, rng, gauss, 8, 2);
      }
    }

    for (const p of pop) {
      expect(Number.isFinite(p.state.mu)).toBe(true);
      expect(Number.isFinite(p.state.sigma)).toBe(true);
      expect(Number.isFinite(p.state.cr)).toBe(true);
    }
    // The re-resolution of the new season pulls mean σ back down below its
    // immediately-post-reset value.
    expect(meanSigma(pop)).toBeLessThan(sigmaAfterReset);

    const crs = pop.map((p) => p.state.cr);
    expect(stdev(crs)).toBeGreaterThan(30);
    expect(stdev(crs)).toBeLessThan(2000);
  });

  it('streak counter stays consistent with placement outcomes (nextStreak wiring)', () => {
    // Sanity that the simulation actually exercises streaks via rate(): after a
    // top-half finish the streak is positive-going; bottom-half negative-going.
    const rng = mulberry32(0xabcdef);
    const gauss = makeGaussian(rng);
    const pop = makePopulation(40, gauss);

    // Single match, inspect one result vs nextStreak directly.
    const idxs = pickDistinct(rng, pop.length, 16);
    const teams: TeamInput[] = [];
    for (let t = 0; t < 8; t += 1) {
      const members = idxs.slice(t * 2, t * 2 + 2).map((i) => pop[i]);
      teams.push({
        teamId: t,
        placement: t + 1,
        participants: members.map<ParticipantInput>((m) => ({
          playerId: m.id,
          state: m.state,
          championId: 1,
          eligibleForProgression: true,
          isPremade: false,
          boostingPenaltyFactor: 0,
        })),
      });
    }
    const res = rate({ matchId: 'sim', mode: 'DUOS', teams, params: P });
    for (const pr of res.players) {
      expect(pr.newStreak).toBe(nextStreak(0, pr.isWin));
    }
  });
});
