import { describe, expect, it } from 'vitest';
import fc from 'fast-check';

import { rate } from '../src/rate.js';
import { toCR } from '../src/cr.js';
import { streakMultiplier } from '../src/modifiers/streak.js';
import { DEFAULT_PARAMS } from '../src/params.js';
import type {
  MatchInput,
  ParticipantInput,
  PlayerState,
  RatingParams,
  TeamInput,
} from '../src/types.js';

/**
 * Property suite (spec §3 / §11). fast-check generates structurally valid matches
 * and checks the authoritative invariants:
 *   I1 — σ_after ≤ sqrt(σ_before² + τ²) under rate() (amended spec §3 invariant; D1).
 *   I2 — determinism + permutation invariance.
 *   I5 — better placement ⇒ ≥ base Δμ (monotone base-PL layer).
 *   I6 — streakMult ∈ [lossFloor, winCeil].
 *   I7 — |Δμ_final| ≤ effectiveCap = maxDeltaMu·max(1, σ_before/dispersionSigmaRef) (σ-scaled, §5.6).
 *   I8 — toCR strictly increasing in μ, strictly decreasing in σ.
 *   I9 — no NaN/Infinity for any structurally valid input.
 *   C1 — |finalDeltaMu| ≤ maxDeltaMu·max(1, σ_before/dispersionSigmaRef) (σ-scaled cap, Trinity C1).
 *   C2 — DEC-A σ-freeze: f=0 ⇒ σ_after == PL σ; f=1 ⇒ σ_after == σ_before; monotone in f.
 *   G2 — rate() rejects a NaN in params.placementWeights / params.maxDeltaMu (validateParams door).
 */

const P: RatingParams = DEFAULT_PARAMS;

// --------------------------------------------------------------------------
// Arbitraries: a structurally valid match over N teams × M players.
// --------------------------------------------------------------------------

const muArb = fc.double({ min: 0, max: 3000, noNaN: true, noDefaultInfinity: true });
const sigmaArb = fc.double({ min: 5, max: 400, noNaN: true, noDefaultInfinity: true });
const streakArb = fc.integer({ min: -8, max: 8 });
const provArb = fc.integer({ min: 0, max: 10 });
const boostArb = fc.double({ min: 0, max: 1, noNaN: true, noDefaultInfinity: true });

function mkState(id: string, mu: number, sigma: number, streak: number, prov: number): PlayerState {
  return {
    playerId: id,
    mu,
    sigma,
    cr: toCR(mu, sigma, P),
    currentStreak: streak,
    matchesPlayed: 42,
    placementMatchesRemaining: prov,
    peakCr: toCR(mu, sigma, P),
  };
}

interface ParticipantSeed {
  mu: number;
  sigma: number;
  streak: number;
  prov: number;
  elig: boolean;
  boost: number;
}

const participantSeedArb: fc.Arbitrary<ParticipantSeed> = fc.record({
  mu: muArb,
  sigma: sigmaArb,
  streak: streakArb,
  prov: provArb,
  elig: fc.boolean(),
  boost: boostArb,
});

interface TeamSeed {
  size: number;
  placement: number;
  participants: ParticipantSeed[];
}

/**
 * Build a match seed: 2..6 teams, each 1..3 players, placements 1..T (ties
 * allowed via random placement in [1, T]). At least one eligible participant is
 * forced so the match is not a degenerate all-void (those are covered in unit
 * tests; here we exercise the live pipeline).
 */
const matchSeedArb = fc
  .array(
    fc.record({
      placement: fc.integer({ min: 1, max: 8 }),
      participants: fc.array(participantSeedArb, { minLength: 1, maxLength: 3 }),
    }),
    { minLength: 2, maxLength: 6 },
  )
  .map((teamSeeds) => {
    // Guarantee at least one eligible participant.
    const anyEligible = teamSeeds.some((t) => t.participants.some((p) => p.elig));
    if (!anyEligible) {
      teamSeeds[0].participants[0] = { ...teamSeeds[0].participants[0], elig: true };
    }
    return teamSeeds;
  });

function buildMatch(
  teamSeeds: Array<{ placement: number; participants: ParticipantSeed[] }>,
  matchId = 'P',
): MatchInput {
  const teams: TeamInput[] = teamSeeds.map((t, ti) => ({
    teamId: ti,
    placement: t.placement,
    participants: t.participants.map<ParticipantInput>((p, pi) => ({
      playerId: `t${ti}-p${pi}`,
      state: mkState(`t${ti}-p${pi}`, p.mu, p.sigma, p.streak, p.prov),
      championId: 1,
      eligibleForProgression: p.elig,
      isPremade: false,
      boostingPenaltyFactor: p.boost,
    })),
  }));
  return { matchId, mode: 'DUOS', teams, params: P };
}

// --------------------------------------------------------------------------
// I9 — no NaN / Infinity for any structurally valid input.
// --------------------------------------------------------------------------

describe('I9 — finite output for all valid inputs', () => {
  it('every numeric field is finite', () => {
    fc.assert(
      fc.property(matchSeedArb, (seeds) => {
        const res = rate(buildMatch(seeds));
        for (const p of res.players) {
          const nums = [
            p.muBefore,
            p.muAfter,
            p.sigmaBefore,
            p.sigmaAfter,
            p.crBefore,
            p.crAfter,
            p.crDelta,
            p.newStreak,
            p.modifiers.plBaseDeltaMu,
            p.modifiers.placementWeight,
            p.modifiers.placementAmp,
            p.modifiers.streakMult,
            p.modifiers.softCapFactor,
            p.modifiers.boostingFactor,
            p.modifiers.finalDeltaMu,
          ];
          for (const n of nums) {
            expect(Number.isFinite(n)).toBe(true);
          }
        }
      }),
      { numRuns: 400 },
    );
  });
});

// --------------------------------------------------------------------------
// I1 (AMENDED, authoritative) — σ_after ≤ sqrt(σ_before² + τ²) for every player
// under rate() (spec §3, amended invariant).
//
// This is the AUTHORITATIVE bound. The τ-dynamics step (spec §4.1: σ² ← σ² + τ²)
// injects τ²-worth of variance before the PL shrink, so the information-theoretic
// ceiling on a single rate() step is exactly sqrt(σ_before² + τ²): σ may legitimately
// sit anywhere up to that bound and never beyond it (σ rises further only via
// softReset). The current implementation shrinks more aggressively (it clamps the
// clean-account PL result to ≤ σ_before and the DEC-A freeze keeps the flagged-account
// result in [PL, σ_before]), so in practice every account lands at or below σ_before
// — comfortably inside this bound. The property asserts the bound the spec mandates,
// for clean (f=0) and flagged (f>0) accounts alike, with no tolerance slack.
// --------------------------------------------------------------------------

describe('I1 — σ_after ≤ sqrt(σ_before² + τ²) under rate() (amended spec §3; D1)', () => {
  it('σ stays within the amended τ-dynamics bound for ANY player over the fuzz space', () => {
    fc.assert(
      fc.property(matchSeedArb, (seeds) => {
        const res = rate(buildMatch(seeds));
        for (const p of res.players) {
          const bound = Math.sqrt(p.sigmaBefore * p.sigmaBefore + P.tau * P.tau);
          expect(p.sigmaAfter).toBeLessThanOrEqual(bound);
        }
      }),
      { numRuns: 500 },
    );
  });

  it('a low-σ player on a high-σ team stays within the amended bound (τ-reinflation)', () => {
    // The τ-dynamics step inflates σ² by τ² before the PL shrink, so a
    // low-information player (tiny variance share — here σ=6 sharing a team with
    // σ=400) could surface σ just above σ_before in the raw PL layer
    // (σ² ← 36 + τ² = 48.25, √ = 6.946). The amended I1 bound sqrt(σ²+τ²) is the
    // authoritative ceiling and holds; rate() in fact clamps even tighter.
    const teams: TeamInput[] = [
      {
        teamId: 0,
        placement: 1,
        participants: [
          {
            playerId: 'low',
            state: mkState('low', 1000, 6, 0, 0),
            championId: 1,
            eligibleForProgression: true,
            isPremade: false,
            boostingPenaltyFactor: 0,
          },
          {
            playerId: 'high',
            state: mkState('high', 1000, 400, 0, 0),
            championId: 1,
            eligibleForProgression: true,
            isPremade: false,
            boostingPenaltyFactor: 0,
          },
        ],
      },
      {
        teamId: 1,
        placement: 2,
        participants: [
          {
            playerId: 'foeA',
            state: mkState('foeA', 1000, 200, 0, 0),
            championId: 1,
            eligibleForProgression: true,
            isPremade: false,
            boostingPenaltyFactor: 0,
          },
          {
            playerId: 'foeB',
            state: mkState('foeB', 1000, 200, 0, 0),
            championId: 1,
            eligibleForProgression: true,
            isPremade: false,
            boostingPenaltyFactor: 0,
          },
        ],
      },
    ];
    const res = rate({ matchId: 'I1-counterexample', mode: 'DUOS', teams, params: P });
    const low = res.players.find((p) => p.playerId === 'low')!;
    expect(low.sigmaBefore).toBe(6);
    // Amended I1: σ_after never exceeds the τ-dynamics ceiling sqrt(σ²+τ²).
    for (const p of res.players) {
      const bound = Math.sqrt(p.sigmaBefore * p.sigmaBefore + P.tau * P.tau);
      expect(p.sigmaAfter).toBeLessThanOrEqual(bound);
    }
  });

  it('ineligible/frozen players keep σ EXACTLY unchanged (modifiers never touch σ, D1)', () => {
    fc.assert(
      fc.property(matchSeedArb, (seeds) => {
        const res = rate(buildMatch(seeds));
        for (const p of res.players) {
          if (!p.eligible || res.voided) {
            expect(p.sigmaAfter).toBe(p.sigmaBefore);
          }
        }
      }),
      { numRuns: 300 },
    );
  });
});

// --------------------------------------------------------------------------
// I2 — determinism + permutation invariance.
// --------------------------------------------------------------------------

describe('I2 — determinism & permutation invariance', () => {
  it('rate(x) deep-equals rate(x)', () => {
    fc.assert(
      fc.property(matchSeedArb, (seeds) => {
        const a = rate(buildMatch(seeds));
        const b = rate(buildMatch(seeds));
        expect(a).toEqual(b);
      }),
      { numRuns: 300 },
    );
  });

  it('invariant to permutation of team order and intra-team player order', () => {
    fc.assert(
      fc.property(matchSeedArb, fc.integer(), (seeds, seed) => {
        const canonical = buildMatch(seeds); // stable ids by original position
        const original = rate(canonical);

        // Deterministic team-order shuffle driven by `seed` (NOT Math.random),
        // plus a reverse of intra-team player order. Player IDENTITY (playerId,
        // teamId, placement, state) is preserved — only array order changes.
        const shuffledTeams = [...canonical.teams]
          .map((t, i) => ({ t, k: hash(i + 1, seed) }))
          .sort((x, y) => x.k - y.k)
          .map(({ t }) => ({ ...t, participants: [...t.participants].reverse() }));

        const permuted = rate({ ...canonical, teams: shuffledTeams });

        const sortById = <T extends { playerId: string }>(arr: T[]): T[] =>
          [...arr].sort((x, y) => (x.playerId < y.playerId ? -1 : 1));

        expect(sortById(permuted.players)).toEqual(sortById(original.players));
        expect(permuted.voided).toBe(original.voided);
      }),
      { numRuns: 250 },
    );
  });
});

/** Small deterministic integer hash for shuffling (NOT Math.random). */
function hash(n: number, seed: number): number {
  let x = (n * 2654435761 + seed * 40503) >>> 0;
  x ^= x >>> 15;
  x = (x * 2246822519) >>> 0;
  x ^= x >>> 13;
  return x >>> 0;
}

// --------------------------------------------------------------------------
// I5 — better placement ⇒ ≥ base Δμ (monotone base-PL layer).
// --------------------------------------------------------------------------

describe('I5 — base Δμ monotone in placement (ceteris paribus)', () => {
  it('a better-placed identical team gets ≥ base Δμ than a worse-placed one', () => {
    // Ceteris paribus: identical singleton teams, only placement differs. The
    // better placement must yield a base Δμ ≥ the worse one.
    fc.assert(
      fc.property(
        muArb,
        sigmaArb,
        fc.integer({ min: 1, max: 4 }),
        fc.integer({ min: 5, max: 8 }),
        (mu, sigma, goodPlace, badPlace) => {
          const teams: TeamInput[] = [
            singletonTeam(0, goodPlace, 'good', mu, sigma),
            singletonTeam(1, badPlace, 'bad', mu, sigma),
            // A third anchor team so the field is non-trivial.
            singletonTeam(2, Math.min(goodPlace, badPlace) + 0, 'anchor', mu, sigma),
          ];
          const res = rate({ matchId: 'I5', mode: 'DUOS', teams, params: P });
          const good = res.players.find((p) => p.playerId === 'good')!;
          const bad = res.players.find((p) => p.playerId === 'bad')!;
          expect(good.modifiers.plBaseDeltaMu).toBeGreaterThanOrEqual(
            bad.modifiers.plBaseDeltaMu - 1e-9,
          );
        },
      ),
      { numRuns: 300 },
    );
  });
});

function singletonTeam(
  teamId: number,
  placement: number,
  playerId: string,
  mu: number,
  sigma: number,
): TeamInput {
  return {
    teamId,
    placement,
    participants: [
      {
        playerId,
        state: mkState(playerId, mu, sigma, 0, 0),
        championId: 1,
        eligibleForProgression: true,
        isPremade: false,
        boostingPenaltyFactor: 0,
      },
    ],
  };
}

// --------------------------------------------------------------------------
// I6 — streakMult ∈ [lossFloor, winCeil] (direct + through rate).
// --------------------------------------------------------------------------

describe('I6 — streak multiplier bounded [lossFloor, winCeil]', () => {
  it('direct streakMultiplier stays within bounds for any streak/sign', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: -50, max: 50 }),
        fc.constantFrom(-1, 0, 1),
        (streak, sign) => {
          const m = streakMultiplier(streak, sign, P);
          expect(m).toBeGreaterThanOrEqual(P.streakLossFloor - 1e-12);
          expect(m).toBeLessThanOrEqual(P.streakWinCeil + 1e-12);
        },
      ),
      { numRuns: 400 },
    );
  });

  it('every applied streakMult in a live match is within bounds', () => {
    fc.assert(
      fc.property(matchSeedArb, (seeds) => {
        const res = rate(buildMatch(seeds));
        for (const p of res.players) {
          expect(p.modifiers.streakMult).toBeGreaterThanOrEqual(P.streakLossFloor - 1e-12);
          expect(p.modifiers.streakMult).toBeLessThanOrEqual(P.streakWinCeil + 1e-12);
        }
      }),
      { numRuns: 300 },
    );
  });
});

// --------------------------------------------------------------------------
// I7 (σ-scaled, §5.6) — |Δμ_final| ≤ effectiveCap = maxDeltaMu·max(1, σ_before/ref).
// --------------------------------------------------------------------------

describe('I7 — final Δμ bounded by the σ-scaled effectiveCap (§5.6)', () => {
  it('|finalDeltaMu| ≤ maxDeltaMu·max(1, σ/ref) for every player, incl. tiny caps', () => {
    fc.assert(
      fc.property(
        matchSeedArb,
        fc.double({ min: 1, max: 300, noNaN: true, noDefaultInfinity: true }),
        (seeds, cap) => {
          const params: RatingParams = { ...P, maxDeltaMu: cap };
          const base = buildMatch(seeds);
          const res = rate({ ...base, params });
          for (const p of res.players) {
            // The bound is the player's OWN σ-scaled cap, not the flat maxDeltaMu.
            const effCap = cap * Math.max(1, p.sigmaBefore / params.dispersionSigmaRef);
            expect(Math.abs(p.modifiers.finalDeltaMu)).toBeLessThanOrEqual(effCap + 1e-9);
            // μ moved exactly by finalDeltaMu (eligible) or 0 (frozen).
            expect(p.muAfter - p.muBefore).toBeCloseTo(p.modifiers.finalDeltaMu, 9);
          }
        },
      ),
      { numRuns: 300 },
    );
  });
});

// --------------------------------------------------------------------------
// C1 (Trinity) — the dispersion cap is σ-SCALED: for ANY player the final Δμ is
// bounded by `maxDeltaMu·max(1, σ_before/dispersionSigmaRef)`. This is the
// invariant the σ-scaled cap (§5.6) exists to provide — a high-σ newcomer gets a
// proportionally wider cap so the PL signal, not a σ-blind flat cap, drives the
// placement climb (C1 root-cause fix). At/below the reference σ the bound is
// exactly maxDeltaMu (it never SHRINKS the cap below the floor).
// --------------------------------------------------------------------------

describe('C1 — σ-scaled dispersion cap bounds finalDeltaMu by maxDeltaMu·max(1, σ/ref)', () => {
  it('|finalDeltaMu| ≤ maxDeltaMu·max(1, σ_before/dispersionSigmaRef) under default params', () => {
    fc.assert(
      fc.property(matchSeedArb, (seeds) => {
        const res = rate(buildMatch(seeds));
        for (const p of res.players) {
          const effCap = P.maxDeltaMu * Math.max(1, p.sigmaBefore / P.dispersionSigmaRef);
          expect(Math.abs(p.modifiers.finalDeltaMu)).toBeLessThanOrEqual(effCap + 1e-9);
        }
      }),
      { numRuns: 400 },
    );
  });

  it('the cap never floors BELOW maxDeltaMu (a low-σ player is bounded by exactly maxDeltaMu)', () => {
    // For any player with σ_before ≤ dispersionSigmaRef the effective bound is the
    // flat maxDeltaMu — the σ-scaling only ever WIDENS, never tightens, the cap.
    fc.assert(
      fc.property(matchSeedArb, (seeds) => {
        const res = rate(buildMatch(seeds));
        for (const p of res.players) {
          if (p.sigmaBefore <= P.dispersionSigmaRef) {
            expect(Math.abs(p.modifiers.finalDeltaMu)).toBeLessThanOrEqual(P.maxDeltaMu + 1e-9);
          }
        }
      }),
      { numRuns: 300 },
    );
  });
});

// --------------------------------------------------------------------------
// C2 (Trinity / DEC-A §5.5) — flagged-only σ-freeze.
//   f = 0 (clean)  ⇒ σ_after == the §4 PL σ (D1 σ-sacrosanct preserved).
//   f = 1 (booster) ⇒ σ_after == σ_before (σ fully frozen, M4 countermeasure).
//   monotone in f  ⇒ a larger f keeps σ wider (shrinks less).
//
// The freeze is exercised on a controlled 2-team duel where exactly one player's
// boostingPenaltyFactor varies; the PL σ-shrink is identical across runs (same
// μ/σ/placement/opponent), so the σ-after differences are attributable solely to f.
// --------------------------------------------------------------------------

describe('C2 — DEC-A flagged-only σ-freeze (§5.5)', () => {
  /** A 2-team duel; the focus player on team 0 wins (σ shrinks in raw PL). */
  function duelWithBoost(boost: number) {
    const focus: ParticipantInput = {
      playerId: 'focus',
      state: mkState('focus', 1000, 200, 0, 0),
      championId: 1,
      eligibleForProgression: true,
      isPremade: false,
      boostingPenaltyFactor: boost,
    };
    const mate: ParticipantInput = {
      playerId: 'mate',
      state: mkState('mate', 1000, 200, 0, 0),
      championId: 1,
      eligibleForProgression: true,
      isPremade: false,
      boostingPenaltyFactor: 0,
    };
    const foe: ParticipantInput = {
      playerId: 'foe',
      state: mkState('foe', 1000, 200, 0, 0),
      championId: 1,
      eligibleForProgression: true,
      isPremade: false,
      boostingPenaltyFactor: 0,
    };
    const teams: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [focus, mate] },
      { teamId: 1, placement: 2, participants: [foe] },
    ];
    const res = rate({ matchId: 'C2', mode: 'DUOS', teams, params: P });
    return res.players.find((p) => p.playerId === 'focus')!;
  }

  it('f = 0 ⇒ σ_after equals the clean PL σ (mate on the same team is the control)', () => {
    // The clean teammate (boost 0) yields the unmodified PL σ; the f=0 focus
    // player must match it exactly (same μ/σ/share), proving f=0 is a no-op.
    const teams: TeamInput[] = [
      {
        teamId: 0,
        placement: 1,
        participants: [
          {
            playerId: 'focus', state: mkState('focus', 1000, 200, 0, 0), championId: 1,
            eligibleForProgression: true, isPremade: false, boostingPenaltyFactor: 0,
          },
          {
            playerId: 'mate', state: mkState('mate', 1000, 200, 0, 0), championId: 1,
            eligibleForProgression: true, isPremade: false, boostingPenaltyFactor: 0,
          },
        ],
      },
      {
        teamId: 1, placement: 2, participants: [
          {
            playerId: 'foe', state: mkState('foe', 1000, 200, 0, 0), championId: 1,
            eligibleForProgression: true, isPremade: false, boostingPenaltyFactor: 0,
          },
        ],
      },
    ];
    const res = rate({ matchId: 'C2-f0', mode: 'DUOS', teams, params: P });
    const focus = res.players.find((p) => p.playerId === 'focus')!;
    const mate = res.players.find((p) => p.playerId === 'mate')!;
    // f=0: σ shrank (clean PL), and equals the identical clean teammate's σ.
    expect(focus.sigmaAfter).toBeLessThan(focus.sigmaBefore);
    expect(focus.sigmaAfter).toBe(mate.sigmaAfter);
  });

  it('f = 1 ⇒ σ_after == σ_before exactly (σ fully frozen)', () => {
    const focus = duelWithBoost(1);
    expect(focus.sigmaAfter).toBe(focus.sigmaBefore);
  });

  it('σ_after is monotone non-decreasing in f (more flagged ⇒ σ stays wider)', () => {
    fc.assert(
      fc.property(
        fc.double({ min: 0, max: 1, noNaN: true, noDefaultInfinity: true }),
        fc.double({ min: 0, max: 1, noNaN: true, noDefaultInfinity: true }),
        (f1, f2) => {
          const lo = Math.min(f1, f2);
          const hi = Math.max(f1, f2);
          const sigmaLo = duelWithBoost(lo).sigmaAfter;
          const sigmaHi = duelWithBoost(hi).sigmaAfter;
          // Larger f freezes more shrink ⇒ σ_after at hi ≥ σ_after at lo.
          expect(sigmaHi).toBeGreaterThanOrEqual(sigmaLo - 1e-12);
        },
      ),
      { numRuns: 300 },
    );
  });

  it('the freeze blend stays within [PL σ, σ_before] (never inflates σ; amended I1 holds)', () => {
    fc.assert(
      fc.property(
        fc.double({ min: 0, max: 1, noNaN: true, noDefaultInfinity: true }),
        (f) => {
          const focus = duelWithBoost(f);
          const cleanPl = duelWithBoost(0).sigmaAfter; // the f=0 PL σ (lower bound)
          expect(focus.sigmaAfter).toBeGreaterThanOrEqual(cleanPl - 1e-12);
          expect(focus.sigmaAfter).toBeLessThanOrEqual(focus.sigmaBefore + 1e-12);
        },
      ),
      { numRuns: 300 },
    );
  });
});

// --------------------------------------------------------------------------
// G2 — rate() rejects a corrupt params object at the validateParams door BEFORE
// any computation. A NaN in params.placementWeights or params.maxDeltaMu would
// otherwise poison every eligible output (I9) or silently disable the I7 cap;
// validateParams (called first in rate()) must throw on both.
// --------------------------------------------------------------------------

describe('G2 — rate() throws on a NaN in params (validateParams door)', () => {
  it('throws when params.maxDeltaMu is NaN', () => {
    fc.assert(
      fc.property(matchSeedArb, (seeds) => {
        const base = buildMatch(seeds);
        const params: RatingParams = { ...P, maxDeltaMu: NaN };
        expect(() => rate({ ...base, params })).toThrow();
      }),
      { numRuns: 100 },
    );
  });

  it('throws when a params.placementWeights entry is NaN', () => {
    fc.assert(
      fc.property(
        matchSeedArb,
        fc.integer({ min: 0, max: 7 }),
        (seeds, idx) => {
          const base = buildMatch(seeds);
          const eight = [...P.placementWeights[8]];
          eight[idx % eight.length] = NaN;
          const params: RatingParams = {
            ...P,
            placementWeights: { ...P.placementWeights, 8: eight },
          };
          expect(() => rate({ ...base, params })).toThrow();
        },
      ),
      { numRuns: 100 },
    );
  });
});

// --------------------------------------------------------------------------
// I8 — toCR strictly increasing in μ, strictly decreasing in σ.
// --------------------------------------------------------------------------

describe('I8 — toCR monotonicity', () => {
  it('strictly increasing in μ (σ fixed)', () => {
    fc.assert(
      fc.property(
        muArb,
        sigmaArb,
        fc.double({ min: 1e-3, max: 500, noNaN: true, noDefaultInfinity: true }),
        (mu, sigma, dMu) => {
          expect(toCR(mu + dMu, sigma, P)).toBeGreaterThan(toCR(mu, sigma, P));
        },
      ),
      { numRuns: 400 },
    );
  });

  it('strictly decreasing in σ (μ fixed)', () => {
    fc.assert(
      fc.property(
        muArb,
        sigmaArb,
        fc.double({ min: 1e-3, max: 200, noNaN: true, noDefaultInfinity: true }),
        (mu, sigma, dSigma) => {
          expect(toCR(mu, sigma + dSigma, P)).toBeLessThan(toCR(mu, sigma, P));
        },
      ),
      { numRuns: 400 },
    );
  });
});
