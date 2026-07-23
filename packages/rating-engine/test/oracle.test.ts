import { describe, expect, it } from 'vitest';
import { rate as openskillRate } from 'openskill';
import type { Rating as OsRating } from 'openskill';

import { DEFAULT_PARAMS } from '../src/params.js';
import { ratePlackettLuce } from '../src/model/plackett-luce.js';
import type { ParticipantInput, PlayerState, RatingParams, TeamInput } from '../src/types.js';

/**
 * I10 correctness gate (spec §4): our base Plackett-Luce update must equal the
 * installed `openskill` PlackettLuce model's `rate()` within 1e-9.
 *
 * openskill is configured with OUR DEFAULT_PARAMS:
 *   - beta:    params.beta
 *   - tau:     params.tau      (drives the additive σ² ← σ² + τ² dynamics)
 *   - epsilon: params.kappa    (the σ²-floor; openskill calls it EPSILON / κ)
 *   - limitSigma / preventSigmaIncrease: left default (false) — no σ cap
 *
 * The implementer ported openskill's `models/plackett-luce.js` + `rate.js`
 * (read from node_modules) faithfully; these fixtures lock the parity.
 */

const P: RatingParams = DEFAULT_PARAMS;
const TOL = 1e-9;

// --------------------------------------------------------------------------
// Fixture model: a roster is teams of (playerId, mu, sigma) with a placement.
// --------------------------------------------------------------------------
interface PlayerSpec {
  playerId: string;
  mu: number;
  sigma: number;
}
interface TeamSpec {
  teamId: number;
  placement: number;
  players: PlayerSpec[];
}
interface Fixture {
  name: string;
  teams: TeamSpec[];
}

function makeState(mu: number, sigma: number): PlayerState {
  return {
    playerId: 'x',
    mu,
    sigma,
    cr: 0,
    currentStreak: 0,
    matchesPlayed: 0,
    placementMatchesRemaining: 0,
    peakCr: 0,
  };
}

function toTeamInputs(teams: TeamSpec[]): TeamInput[] {
  return teams.map((t) => ({
    teamId: t.teamId,
    placement: t.placement,
    participants: t.players.map<ParticipantInput>((pl) => ({
      playerId: pl.playerId,
      state: { ...makeState(pl.mu, pl.sigma), playerId: pl.playerId },
      championId: 1,
      eligibleForProgression: true,
      isPremade: false,
      boostingPenaltyFactor: 0,
    })),
  }));
}

/**
 * Reference: run openskill PlackettLuce `rate()` with our hyperparameters and
 * return a flat map playerId -> { deltaMu, sigmaAfter }.
 *
 * openskill returns teams in the SAME order they were passed in, so we keep a
 * parallel playerId array to re-associate. We pass each team's `placement` as
 * its `rank` (lower = better; ties allowed) — openskill handles ordering/ties.
 */
function openskillReference(
  teams: TeamSpec[],
): Map<string, { deltaMu: number; sigmaAfter: number }> {
  const osTeams: OsRating[][] = teams.map((t) =>
    t.players.map((pl) => ({ mu: pl.mu, sigma: pl.sigma })),
  );
  const rank = teams.map((t) => t.placement);
  const out = openskillRate(osTeams, {
    rank,
    beta: P.beta,
    tau: P.tau,
    epsilon: P.kappa,
  });

  const map = new Map<string, { deltaMu: number; sigmaAfter: number }>();
  teams.forEach((t, ti) => {
    t.players.forEach((pl, pi) => {
      const after = out[ti][pi];
      map.set(pl.playerId, {
        deltaMu: after.mu - pl.mu,
        sigmaAfter: after.sigma,
      });
    });
  });
  return map;
}

// --------------------------------------------------------------------------
// Fixtures (>=15): 8-team Duos, 6-team Trios, ties, lopsided rosters.
// --------------------------------------------------------------------------

/** Generate an N-team roster of M-player teams, distinct ratings, given placements. */
function roster(
  prefix: string,
  teamCount: number,
  teamSize: number,
  placements: number[],
  base: (team: number, slot: number) => PlayerSpec,
): TeamSpec[] {
  const teams: TeamSpec[] = [];
  for (let t = 0; t < teamCount; t += 1) {
    const players: PlayerSpec[] = [];
    for (let s = 0; s < teamSize; s += 1) {
      players.push(base(t, s));
    }
    teams.push({ teamId: t, placement: placements[t], players });
  }
  void prefix;
  return teams;
}

const fixtures: Fixture[] = [];

// 1: 8-team Duos, fresh-ish ladder, strict 1..8 placement.
fixtures.push({
  name: '8-team Duos — fresh ladder, strict placement',
  teams: roster('d1', 8, 2, [1, 2, 3, 4, 5, 6, 7, 8], (t, s) => ({
    playerId: `d1-t${t}-p${s}`,
    mu: 1000,
    sigma: 350,
  })),
});

// 2: 8-team Duos, mixed ratings, strict placement.
fixtures.push({
  name: '8-team Duos — mixed ratings, strict placement',
  teams: roster('d2', 8, 2, [3, 1, 8, 4, 2, 7, 5, 6], (t, s) => ({
    playerId: `d2-t${t}-p${s}`,
    mu: 800 + t * 90 + s * 37,
    sigma: 120 + t * 11 + s * 5,
  })),
});

// 3: 8-team Duos, lopsided — one elite team, rest fresh.
fixtures.push({
  name: '8-team Duos — lopsided (one elite vs fresh)',
  teams: roster('d3', 8, 2, [8, 1, 2, 3, 4, 5, 6, 7], (t, s) =>
    t === 1
      ? { playerId: `d3-t${t}-p${s}`, mu: 1800, sigma: 70 }
      : { playerId: `d3-t${t}-p${s}`, mu: 950, sigma: 340 },
  ),
});

// 4: 8-team Duos with a two-way tie for 1st.
fixtures.push({
  name: '8-team Duos — tie for 1st (placements 1,1,3,4,5,6,7,8)',
  teams: roster('d4', 8, 2, [1, 1, 3, 4, 5, 6, 7, 8], (t, s) => ({
    playerId: `d4-t${t}-p${s}`,
    mu: 1100 - t * 30 + s * 12,
    sigma: 200 - t * 7 + s * 3,
  })),
});

// 5: 8-team Duos with two separate tie groups.
fixtures.push({
  name: '8-team Duos — two tie groups (1,1,3,3,5,6,6,8)',
  teams: roster('d5', 8, 2, [1, 1, 3, 3, 5, 6, 6, 8], (t, s) => ({
    playerId: `d5-t${t}-p${s}`,
    mu: 1000 + t * 25 - s * 8,
    sigma: 150 + t * 9 + s * 4,
  })),
});

// 6: 8-team Duos, all tied (full draw).
fixtures.push({
  name: '8-team Duos — all tied (full draw)',
  teams: roster('d6', 8, 2, [1, 1, 1, 1, 1, 1, 1, 1], (t, s) => ({
    playerId: `d6-t${t}-p${s}`,
    mu: 980 + t * 17 + s * 9,
    sigma: 130 + t * 6,
  })),
});

// 7: 8-team Duos, reversed placement (worst-rated win).
fixtures.push({
  name: '8-team Duos — upset (placements reversed vs ratings)',
  teams: roster('d7', 8, 2, [8, 7, 6, 5, 4, 3, 2, 1], (t, s) => ({
    playerId: `d7-t${t}-p${s}`,
    mu: 700 + t * 110,
    sigma: 90 + t * 8 + s * 3,
  })),
});

// 8: 8-team Duos, lopsided roster sizes (uneven team sizes).
fixtures.push({
  name: '8-team — uneven roster sizes (3,1,2,2,1,2,3,2)',
  teams: [
    { teamId: 0, placement: 4, players: [s('u0', 0), s('u0', 1), s('u0', 2)] },
    { teamId: 1, placement: 1, players: [s('u1', 0)] },
    { teamId: 2, placement: 2, players: [s('u2', 0), s('u2', 1)] },
    { teamId: 3, placement: 7, players: [s('u3', 0), s('u3', 1)] },
    { teamId: 4, placement: 3, players: [s('u4', 0)] },
    { teamId: 5, placement: 6, players: [s('u5', 0), s('u5', 1)] },
    { teamId: 6, placement: 5, players: [s('u6', 0), s('u6', 1), s('u6', 2)] },
    { teamId: 7, placement: 8, players: [s('u7', 0), s('u7', 1)] },
  ],
});

// 9: 6-team Trios, fresh ladder, strict placement.
fixtures.push({
  name: '6-team Trios — fresh ladder, strict placement',
  teams: roster('t1', 6, 3, [1, 2, 3, 4, 5, 6], (t, s) => ({
    playerId: `t1-t${t}-p${s}`,
    mu: 1000,
    sigma: 350,
  })),
});

// 10: 6-team Trios, mixed ratings, scrambled placement.
fixtures.push({
  name: '6-team Trios — mixed ratings, scrambled placement',
  teams: roster('t2', 6, 3, [4, 1, 6, 2, 5, 3], (t, s) => ({
    playerId: `t2-t${t}-p${s}`,
    mu: 850 + t * 95 + s * 41,
    sigma: 110 + t * 13 + s * 7,
  })),
});

// 11: 6-team Trios with a three-way tie for 1st.
fixtures.push({
  name: '6-team Trios — three-way tie for 1st (1,1,1,4,5,6)',
  teams: roster('t3', 6, 3, [1, 1, 1, 4, 5, 6], (t, s) => ({
    playerId: `t3-t${t}-p${s}`,
    mu: 1050 - t * 22 + s * 15,
    sigma: 170 + t * 8 + s * 5,
  })),
});

// 12: 6-team Trios, tie in the middle (1,2,2,2,5,6).
fixtures.push({
  name: '6-team Trios — middle tie (1,2,2,2,5,6)',
  teams: roster('t4', 6, 3, [1, 2, 2, 2, 5, 6], (t, s) => ({
    playerId: `t4-t${t}-p${s}`,
    mu: 1000 + t * 30 - s * 10,
    sigma: 140 + t * 10 + s * 6,
  })),
});

// 13: 6-team Trios, lopsided (one stack of veterans).
fixtures.push({
  name: '6-team Trios — lopsided (veteran stack)',
  teams: roster('t5', 6, 3, [1, 6, 2, 5, 3, 4], (t, s) =>
    t === 0
      ? { playerId: `t5-t${t}-p${s}`, mu: 1600 + s * 50, sigma: 65 + s * 3 }
      : { playerId: `t5-t${t}-p${s}`, mu: 980 + t * 20 + s * 12, sigma: 300 - t * 15 },
  ),
});

// 14: 6-team Trios, high-variance newcomers vs settled.
fixtures.push({
  name: '6-team Trios — high-variance newcomers vs settled',
  teams: roster('t6', 6, 3, [2, 4, 1, 6, 3, 5], (t, s) =>
    t % 2 === 0
      ? { playerId: `t6-t${t}-p${s}`, mu: 1000 + s * 20, sigma: 349 - s * 2 }
      : { playerId: `t6-t${t}-p${s}`, mu: 1100 + t * 15, sigma: 80 + s * 4 },
  ),
});

// 15: 6-team Trios, all tied (full draw).
fixtures.push({
  name: '6-team Trios — all tied (full draw)',
  teams: roster('t7', 6, 3, [2, 2, 2, 2, 2, 2], (t, s) => ({
    playerId: `t7-t${t}-p${s}`,
    mu: 1000 + t * 18 - s * 6,
    sigma: 160 + t * 7 + s * 3,
  })),
});

// 16: tiny edge — 2-team Duos (minimum valid match).
fixtures.push({
  name: '2-team Duos — minimum valid match',
  teams: roster('m1', 2, 2, [1, 2], (t, s) => ({
    playerId: `m1-t${t}-p${s}`,
    mu: 1000 + t * 200 + s * 50,
    sigma: 200 - t * 30 + s * 10,
  })),
});

// 17: 4-team mixed sizes with a tie (stress determinism + ties + uneven).
fixtures.push({
  name: '4-team — uneven sizes with a tie (2,2,1,3 players; placements 1,1,3,4)',
  teams: [
    { teamId: 0, placement: 1, players: [s('z0', 0), s('z0', 1)] },
    { teamId: 1, placement: 1, players: [s('z1', 0), s('z1', 1)] },
    { teamId: 2, placement: 3, players: [s('z2', 0)] },
    { teamId: 3, placement: 4, players: [s('z3', 0), s('z3', 1), s('z3', 2)] },
  ],
});

/** Deterministic per-slot player spec used by the uneven-roster fixtures. */
function s(tag: string, slot: number): PlayerSpec {
  // Hash-free deterministic spread so each player differs.
  const code = tag.charCodeAt(tag.length - 1) - 48; // last char numeric-ish
  return {
    playerId: `${tag}-p${slot}`,
    mu: 900 + code * 37 + slot * 53,
    sigma: 120 + code * 9 + slot * 17,
  };
}

describe('Plackett-Luce oracle parity (I10) vs openskill', () => {
  it('has at least 15 fixtures spanning Duos, Trios, ties, and lopsided rosters', () => {
    expect(fixtures.length).toBeGreaterThanOrEqual(15);
  });

  for (const fx of fixtures) {
    it(`matches openskill within 1e-9 — ${fx.name}`, () => {
      const ref = openskillReference(fx.teams);
      const ours = ratePlackettLuce(toTeamInputs(fx.teams), P);

      // Same set of players.
      expect(new Set(ours.map((r) => r.playerId))).toEqual(new Set(ref.keys()));
      expect(ours.length).toBe(ref.size);

      for (const r of ours) {
        const expected = ref.get(r.playerId);
        expect(expected, `missing ref for ${r.playerId}`).toBeDefined();
        if (!expected) continue;
        expect(Number.isFinite(r.deltaMu)).toBe(true);
        expect(Number.isFinite(r.sigmaAfter)).toBe(true);
        expect(Math.abs(r.deltaMu - expected.deltaMu)).toBeLessThanOrEqual(TOL);
        expect(Math.abs(r.sigmaAfter - expected.sigmaAfter)).toBeLessThanOrEqual(TOL);
      }
    });
  }

  it('is invariant to input permutation of teams and intra-team players (I2)', () => {
    const fx = fixtures[1]; // mixed-ratings Duos
    const forward = ratePlackettLuce(toTeamInputs(fx.teams), P);

    // Reverse team order and reverse players within each team.
    const permuted: TeamSpec[] = [...fx.teams]
      .reverse()
      .map((t) => ({ ...t, players: [...t.players].reverse() }));
    const backward = ratePlackettLuce(toTeamInputs(permuted), P);

    const sortById = (rs: typeof forward) =>
      [...rs].sort((x, y) => (x.playerId < y.playerId ? -1 : 1));

    const f = sortById(forward);
    const b = sortById(backward);
    expect(f.length).toBe(b.length);
    for (let i = 0; i < f.length; i += 1) {
      expect(f[i].playerId).toBe(b[i].playerId);
      expect(f[i].deltaMu).toBe(b[i].deltaMu);
      expect(f[i].sigmaAfter).toBe(b[i].sigmaAfter);
    }
  });
});
