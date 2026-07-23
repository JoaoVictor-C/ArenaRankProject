import type { RatingParams, TeamInput } from '../types.js';

/**
 * Per-player base output of the Weng-Lin Plackett-Luce update (spec §4).
 */
export interface PlBaseResult {
  playerId: string;
  deltaMu: number;
  sigmaAfter: number;
}

/**
 * Internal per-player working state after the dynamics (τ²) step.
 */
interface PlayerWork {
  playerId: string;
  mu: number;
  sigmaSq: number; // σ² AFTER adding τ²
}

/**
 * Internal per-team aggregate used by the Plackett-Luce update.
 */
interface TeamWork {
  /** Σ μ over team members. */
  muTeam: number;
  /** Σ σ² over team members (post-dynamics). */
  sigmaSqTeam: number;
  /** Contiguous, tie-aware 0-based rank index (Weng-Lin). */
  rank: number;
  /** Players in this team, sorted by playerId. */
  players: PlayerWork[];
}

/**
 * ratePlackettLuce — Weng & Lin (2011) Plackett-Luce full-ranking update.
 *
 * Faithful port of openskill's `PlackettLuce` model (v4.x) combined with the
 * `rate()` driver's additive-dynamics step, configured with our parameters:
 *   - dynamics: σ² ← σ² + τ²        (always applied; matches `rate({ tau })`)
 *   - normalizer: c = sqrt(Σ (σ²_team + β²))
 *   - Plackett-Luce Ω_team / Δ_team terms with Weng-Lin tie handling (÷ a)
 *   - back-distribution variance-weighted to players
 *   - floor: σ²_after = σ² · max(1 − (σ²/c²)·Δ_team, κ)
 *
 * DETERMINISTIC (spec §8): teams are sorted by (placement, teamId) and players
 * by playerId before any summation, so f64 op order is fixed and the result is
 * invariant to input permutation.
 *
 * The σ-cap (openskill `preventSigmaIncrease` / `LIMIT_SIGMA`) is intentionally
 * NOT applied here — the spec's `max(…, κ)` floor is the only sigma guard, which
 * matches openskill's default `limitSigma = false`.
 */
export function ratePlackettLuce(
  teams: TeamInput[],
  params: RatingParams,
): PlBaseResult[] {
  const { beta, tau, kappa } = params;
  const betaSq = beta * beta;
  const tauSq = tau * tau;

  // --- Step 1+2: dynamics + team aggregation, deterministically ordered. -----
  // Sort teams by (placement, teamId); players by playerId. Pure, stable.
  const sortedTeams = [...teams].sort((x, y) =>
    x.placement !== y.placement
      ? x.placement - y.placement
      : x.teamId - y.teamId,
  );

  const teamWork: TeamWork[] = sortedTeams.map((team) => {
    const players: PlayerWork[] = [...team.participants]
      // playerIds are unique within a match → two-way comparator is a total,
      // stable order; no equal-key branch needed (keeps the sum order fixed, §8).
      .sort((p1, p2) => (p1.playerId < p2.playerId ? -1 : 1))
      .map((p) => ({
        playerId: p.playerId,
        mu: p.state.mu,
        // Dynamics: inflate variance by τ² before the update (spec §4.1).
        sigmaSq: p.state.sigma * p.state.sigma + tauSq,
      }));

    let muTeam = 0;
    let sigmaSqTeam = 0;
    for (const p of players) {
      muTeam += p.mu;
      sigmaSqTeam += p.sigmaSq;
    }

    return { muTeam, sigmaSqTeam, rank: 0, players };
  });

  // --- Contiguous, tie-aware rank indices (openskill `rankings`). ------------
  // teamWork is already sorted ascending by placement. Map distinct placements
  // to the index of their first occurrence (Weng-Lin tie convention): equal
  // placement ⇒ equal rank index.
  let s = 0;
  for (let j = 0; j < sortedTeams.length; j += 1) {
    if (j > 0 && sortedTeams[j - 1].placement < sortedTeams[j].placement) {
      s = j;
    }
    teamWork[j].rank = s;
  }

  // --- Step 3: match normalizer c = sqrt(Σ (σ²_team + β²)). ------------------
  let cSq = 0;
  for (const t of teamWork) {
    cSq += t.sigmaSqTeam + betaSq;
  }
  const c = Math.sqrt(cSq);

  // --- Plackett-Luce shared terms (openskill utilSumQ / utilA). -------------
  // sumQ[q] = Σ_{rank(i) >= rank(q)} exp(μ_team[i] / c)
  const expMuOverC = teamWork.map((t) => Math.exp(t.muTeam / c));
  const sumQ = teamWork.map((_, q) => {
    const qRank = teamWork[q].rank;
    let acc = 0;
    for (let i = 0; i < teamWork.length; i += 1) {
      if (teamWork[i].rank >= qRank) {
        acc += expMuOverC[i];
      }
    }
    return acc;
  });
  // a[i] = number of teams sharing rank(i) (tie multiplicity).
  const a = teamWork.map((_, i) => {
    const iRank = teamWork[i].rank;
    let count = 0;
    for (let j = 0; j < teamWork.length; j += 1) {
      if (teamWork[j].rank === iRank) {
        count += 1;
      }
    }
    return count;
  });

  // --- Step 4+5: per-team Ω/Δ, then variance-weighted back-distribution. -----
  const results: PlBaseResult[] = [];
  for (let i = 0; i < teamWork.length; i += 1) {
    const t = teamWork[i];
    const iMuOverCe = expMuOverC[i];
    const iRank = t.rank;

    let omegaSum = 0;
    let deltaSum = 0;
    for (let q = 0; q < teamWork.length; q += 1) {
      if (teamWork[q].rank <= iRank) {
        const quotient = iMuOverCe / sumQ[q];
        omegaSum += (i === q ? 1 - quotient : -quotient) / a[q];
        deltaSum += (quotient * (1 - quotient)) / a[q];
      }
    }

    // gamma default = sqrt(σ²_team) / c  (openskill default gamma).
    const iGamma = Math.sqrt(t.sigmaSqTeam) / c;
    const iOmega = omegaSum * (t.sigmaSqTeam / c);
    const iDelta = iGamma * deltaSum * (t.sigmaSqTeam / cSq);

    for (const p of t.players) {
      const share = p.sigmaSq / t.sigmaSqTeam;
      const deltaMu = share * iOmega;
      const sigmaSqAfter = p.sigmaSq * Math.max(1 - share * iDelta, kappa);
      results.push({
        playerId: p.playerId,
        deltaMu,
        sigmaAfter: Math.sqrt(sigmaSqAfter),
      });
    }
  }

  return results;
}
