import { describe, expect, it } from 'vitest';

import { rate } from '../src/rate.js';
import { DEFAULT_PARAMS } from '../src/params.js';
import { toCR } from '../src/cr.js';
import type {
  MatchInput,
  ParticipantInput,
  PlayerState,
  RatingParams,
  TeamInput,
} from '../src/types.js';

const P: RatingParams = DEFAULT_PARAMS;

// --------------------------------------------------------------------------
// Tiny fixture builders (deterministic; CR materialized via toCR like the DB).
// --------------------------------------------------------------------------

interface PlayerOpts {
  streak?: number;
  matchesPlayed?: number;
  prov?: number; // placementMatchesRemaining
  peakCr?: number;
  champ?: number;
  elig?: boolean;
  premade?: boolean;
  partyId?: string;
  boost?: number; // boostingPenaltyFactor
  params?: RatingParams;
}

function mkState(id: string, mu: number, sigma: number, o: PlayerOpts = {}): PlayerState {
  const params = o.params ?? P;
  const cr = toCR(mu, sigma, params);
  return {
    playerId: id,
    mu,
    sigma,
    cr,
    currentStreak: o.streak ?? 0,
    matchesPlayed: o.matchesPlayed ?? 50,
    placementMatchesRemaining: o.prov ?? 0,
    peakCr: o.peakCr ?? cr,
  };
}

function mkP(id: string, mu: number, sigma: number, o: PlayerOpts = {}): ParticipantInput {
  return {
    playerId: id,
    state: mkState(id, mu, sigma, o),
    championId: o.champ ?? 1,
    eligibleForProgression: o.elig ?? true,
    isPremade: o.premade ?? false,
    partyId: o.partyId,
    boostingPenaltyFactor: o.boost ?? 0,
  };
}

/** Realistic 8×2 Arena Duos fixture (placements 1..8, settled ratings). */
function arena8x2(): TeamInput[] {
  const teams: TeamInput[] = [];
  for (let t = 0; t < 8; t += 1) {
    teams.push({
      teamId: t,
      placement: t + 1,
      participants: [mkP(`t${t}-a`, 1000 + t * 30, 140 - t * 5), mkP(`t${t}-b`, 980 + t * 25, 150 - t * 4)],
    });
  }
  return teams;
}

function match(teams: TeamInput[], id = 'M', mode: 'DUOS' | 'TRIOS' = 'DUOS'): MatchInput {
  return { matchId: id, mode, teams, params: P };
}

// --------------------------------------------------------------------------
// Snapshot: the full RatingResult of a realistic 8×2 Arena fixture.
// --------------------------------------------------------------------------

describe('rate — realistic 8×2 Arena snapshot', () => {
  it('produces a locked RatingResult', () => {
    const res = rate(match(arena8x2(), 'M-8x2'));
    expect(res).toMatchSnapshot();
  });

  it('top-half teams win, bottom-half lose (isWin = placement ≤ floor(T/2))', () => {
    const res = rate(match(arena8x2(), 'M-8x2'));
    for (const p of res.players) {
      const teamIdx = Number(p.playerId.slice(1, p.playerId.indexOf('-')));
      const placement = teamIdx + 1;
      expect(p.isWin).toBe(placement <= 4);
    }
  });

  it('better placement ⇒ larger base Δμ (monotone base layer, I5)', () => {
    const res = rate(match(arena8x2(), 'M-8x2'));
    // First player of each team, ordered by placement.
    const firsts = res.players.filter((p) => p.playerId.endsWith('-a'));
    const byPlacement = [...firsts].sort(
      (x, y) => Number(x.playerId.slice(1, x.playerId.indexOf('-'))) - Number(y.playerId.slice(1, y.playerId.indexOf('-'))),
    );
    for (let i = 1; i < byPlacement.length; i += 1) {
      expect(byPlacement[i - 1].modifiers.plBaseDeltaMu).toBeGreaterThanOrEqual(
        byPlacement[i].modifiers.plBaseDeltaMu,
      );
    }
  });

  it('not voided, every player present once', () => {
    const res = rate(match(arena8x2(), 'M-8x2'));
    expect(res.voided).toBe(false);
    expect(res.players).toHaveLength(16);
    expect(new Set(res.players.map((p) => p.playerId)).size).toBe(16);
  });
});

// --------------------------------------------------------------------------
// Targeted case: eligibility freeze (D3/I3).
// --------------------------------------------------------------------------

describe('rate — eligibility freeze (D3/I3)', () => {
  it('freezes an ineligible player but still moves eligible opponents', () => {
    const teams: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [mkP('win', 1000, 120)] },
      { teamId: 1, placement: 2, participants: [mkP('afk', 1000, 120, { elig: false })] },
    ];
    const res = rate(match(teams));
    expect(res.voided).toBe(false);

    const afk = res.players.find((p) => p.playerId === 'afk')!;
    expect(afk.eligible).toBe(false);
    expect(afk.muAfter).toBe(afk.muBefore);
    expect(afk.sigmaAfter).toBe(afk.sigmaBefore);
    expect(afk.crDelta).toBe(0);
    expect(afk.newStreak).toBe(0); // streak frozen (ineligible never progresses)
    expect(afk.modifiers).toEqual({
      plBaseDeltaMu: 0,
      placementWeight: 1,
      placementAmp: 1,
      streakMult: 1,
      softCapFactor: 1,
      boostingFactor: 1,
      dispersionClamped: false,
      finalDeltaMu: 0,
    });

    const win = res.players.find((p) => p.playerId === 'win')!;
    expect(win.eligible).toBe(true);
    expect(win.muAfter).toBeGreaterThan(win.muBefore); // winner climbs
    expect(win.crDelta).toBeGreaterThan(0);
    // The frozen team still fed the PL aggregate: winner moved a non-trivial amount.
    expect(Math.abs(win.modifiers.plBaseDeltaMu)).toBeGreaterThan(0);
  });

  it('ineligible player on a team still contributes its aggregate to opponents', () => {
    // Two teams: eligible winner vs a duo with one AFK. The AFK still counts in
    // the loser team's μ/σ aggregate, so removing it would change the winner's Δμ.
    const withAfk: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [mkP('w', 1100, 90)] },
      {
        teamId: 1,
        placement: 2,
        participants: [mkP('l1', 1000, 100), mkP('l2-afk', 1400, 80, { elig: false })],
      },
    ];
    const resWith = rate(match(withAfk));
    const wWith = resWith.players.find((p) => p.playerId === 'w')!;

    const withoutAfk: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [mkP('w', 1100, 90)] },
      { teamId: 1, placement: 2, participants: [mkP('l1', 1000, 100)] },
    ];
    const resWithout = rate(match(withoutAfk));
    const wWithout = resWithout.players.find((p) => p.playerId === 'w')!;

    // Different aggregates ⇒ different winner movement (the AFK still informs PL).
    expect(wWith.modifiers.plBaseDeltaMu).not.toBe(wWithout.modifiers.plBaseDeltaMu);
  });
});

// --------------------------------------------------------------------------
// Targeted case: empty team rejection (spec §9 — "Validate & test: empty team").
// A team with zero participants still occupies a rank slot and adds β² to the
// match normalizer c, so a lone real opponent "loses" to a phantom empty team
// (finite but semantically corrupt output). rate() must reject it up front.
// --------------------------------------------------------------------------

describe('rate — empty team rejection (spec §9)', () => {
  it('throws on a team with zero participants (phantom-team corruption)', () => {
    const teams: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [] }, // empty (phantom) team
      { teamId: 1, placement: 2, participants: [mkP('x', 1000, 200)] },
    ];
    expect(() => rate(match(teams))).toThrow(/empty team/i);
  });

  it('throws even when the empty team is not the first sorted team', () => {
    const teams: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [mkP('x', 1000, 200)] },
      { teamId: 1, placement: 2, participants: [] }, // empty (phantom) team
    ];
    expect(() => rate(match(teams))).toThrow(/empty team/i);
  });

  it('a fully-populated match is still accepted (no false positive)', () => {
    const teams: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [mkP('x', 1000, 200)] },
      { teamId: 1, placement: 2, participants: [mkP('y', 1000, 200)] },
    ];
    expect(() => rate(match(teams))).not.toThrow();
  });
});

// --------------------------------------------------------------------------
// Targeted case: void match (all ineligible) (D3/I4).
// --------------------------------------------------------------------------

describe('rate — void match (all ineligible, D3/I4)', () => {
  it('voids and freezes everyone when ALL participants are ineligible', () => {
    const teams: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [mkP('a', 1000, 120, { elig: false, streak: 3 })] },
      { teamId: 1, placement: 2, participants: [mkP('b', 1000, 120, { elig: false, streak: -2 })] },
    ];
    const res = rate(match(teams));
    expect(res.voided).toBe(true);
    for (const p of res.players) {
      expect(p.muAfter).toBe(p.muBefore);
      expect(p.sigmaAfter).toBe(p.sigmaBefore);
      expect(p.crDelta).toBe(0);
      expect(p.modifiers.finalDeltaMu).toBe(0);
      expect(p.modifiers.plBaseDeltaMu).toBe(0);
    }
    // Streaks frozen (void = nobody moves).
    expect(res.players.find((p) => p.playerId === 'a')!.newStreak).toBe(3);
    expect(res.players.find((p) => p.playerId === 'b')!.newStreak).toBe(-2);
  });

  it('a single eligible player among ineligibles is NOT a void', () => {
    const teams: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [mkP('elig', 1000, 120)] },
      { teamId: 1, placement: 2, participants: [mkP('afk', 1000, 120, { elig: false })] },
    ];
    const res = rate(match(teams));
    expect(res.voided).toBe(false);
    expect(res.players.find((p) => p.playerId === 'elig')!.muAfter).not.toBe(1000);
  });
});

// --------------------------------------------------------------------------
// Targeted case: <2 teams is rejected, never silently rated (spec §9).
// --------------------------------------------------------------------------

describe('rate — <2 teams rejected (spec §9)', () => {
  it('throws on a single-team match (no opponent to rank against)', () => {
    // An unopposed "match" has no ranking signal: the PL update would still
    // mutate σ (via the τ-dynamics step) and crDelta, so it must be rejected
    // rather than silently accepted (spec §9 mandates validating <2 teams).
    const teams: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [mkP('solo', 1000, 200)] },
    ];
    expect(() => rate(match(teams))).toThrow(/2 teams/);
  });

  it('throws on an empty match (zero teams)', () => {
    expect(() => rate(match([]))).toThrow(/2 teams/);
  });

  it('accepts the 2-team minimum', () => {
    const teams: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [mkP('a', 1000, 200)] },
      { teamId: 1, placement: 2, participants: [mkP('b', 1000, 200)] },
    ];
    expect(() => rate(match(teams))).not.toThrow();
  });
});

// --------------------------------------------------------------------------
// Targeted case: duplicate playerId guard (§8 per-player back-association).
//
// rate() back-associates each PL base result to its participant by playerId
// (`baseById.get(participant.playerId)`). That mapping is sound ONLY if
// playerIds are unique within the match — a precondition the deterministic-
// ordering comments and the PL model both rely on. A duplicate playerId on two
// DIFFERENT teams silently collides in the id→base map: the second Map entry
// clobbers the first, so BOTH participants read the same base delta. A real
// placement-1 winner (isWin=true) then inherits the placement-2 loser's loss
// — a silent, fully constructible corruption with no guard anywhere. rate()
// MUST reject such input instead of emitting an invariant-breaking result.
// --------------------------------------------------------------------------

describe('rate — duplicate playerId guard (§8 back-association)', () => {
  it('rejects the same playerId on two different teams (no silent clobber)', () => {
    // The confirmed failing case: placement-1 winner vs placement-2 loser, same
    // id. Without the guard the winner silently receives the loser's negative
    // delta. We require a hard, deterministic failure instead.
    const teams: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [mkP('dup', 1000, 200)] },
      { teamId: 1, placement: 2, participants: [mkP('dup', 1000, 200)] },
    ];
    expect(() => rate(match(teams))).toThrow(/duplicate playerId/i);
  });

  it('rejects a duplicate playerId within the same team', () => {
    const teams: TeamInput[] = [
      {
        teamId: 0,
        placement: 1,
        participants: [mkP('twin', 1000, 200), mkP('twin', 1050, 180)],
      },
      { teamId: 1, placement: 2, participants: [mkP('foe', 1000, 200)] },
    ];
    expect(() => rate(match(teams))).toThrow(/duplicate playerId/i);
  });

  it('names the offending playerId in the error', () => {
    const teams: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [mkP('collide', 1000, 200)] },
      { teamId: 1, placement: 2, participants: [mkP('collide', 1000, 200)] },
    ];
    expect(() => rate(match(teams))).toThrow(/collide/);
  });

  it('still accepts a match where every playerId is unique', () => {
    const teams: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [mkP('a', 1000, 200)] },
      { teamId: 1, placement: 2, participants: [mkP('b', 1000, 200)] },
    ];
    expect(() => rate(match(teams))).not.toThrow();
  });
});

// --------------------------------------------------------------------------
// Targeted case: non-finite (NaN / Infinity) structural input is REJECTED
// (spec §9 "NaN/Infinity inputs (reject)" / I9 "no NaN/Infinity output").
//
// I9 promises finite output only for STRUCTURALLY VALID input, so a non-finite
// numeric anywhere in the match must be caught at the door — NEVER flowed through
// the shared PL normalizer `c` / `exp(muTeam/c)`, where a SINGLE bad participant
// poisons the WHOLE match (every eligible player's finalDeltaMu / muAfter → NaN).
// Confirmed failing case: one participant with mu=NaN ⇒ every eligible output NaN,
// and rate() returned silently. rate() must reject it instead.
// --------------------------------------------------------------------------

describe('rate — rejects non-finite (NaN/Infinity) structural input (§9 / I9)', () => {
  /** A clean 2-team duel; the mutator corrupts exactly one numeric field. */
  function duel(mutate: (teams: TeamInput[]) => void): MatchInput {
    const teams: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [mkP('a', 1000, 120)] },
      { teamId: 1, placement: 2, participants: [mkP('b', 1000, 120)] },
    ];
    mutate(teams);
    return match(teams);
  }

  it('REGRESSION: one participant with mu=NaN no longer poisons the match', () => {
    // Pre-fix this returned silently with a.finalDeltaMu=NaN and a.muAfter=NaN
    // (NaN flowed through the shared normalizer to EVERY eligible player). It must
    // now throw at the door, before any numeric work poisons a valid opponent.
    const bad = duel((t) => {
      t[1].participants[0].state.mu = NaN;
    });
    expect(() => rate(bad)).toThrow(/finite/i);
  });

  it('rejects NaN, +Infinity, and -Infinity in every numeric state field', () => {
    const stateFields = ['mu', 'sigma', 'cr', 'currentStreak', 'matchesPlayed', 'placementMatchesRemaining', 'peakCr'] as const;
    for (const bad of [NaN, Infinity, -Infinity]) {
      for (const field of stateFields) {
        expect(() =>
          rate(duel((t) => {
            (t[0].participants[0].state as unknown as Record<string, number>)[field] = bad;
          })),
        ).toThrow(/finite/i);
      }
    }
  });

  it('rejects a non-finite placement, teamId, championId, or boostingPenaltyFactor', () => {
    expect(() => rate(duel((t) => { t[0].placement = Infinity; }))).toThrow(/finite/i);
    expect(() => rate(duel((t) => { t[0].teamId = NaN; }))).toThrow(/finite/i);
    expect(() => rate(duel((t) => { t[0].participants[0].championId = NaN; }))).toThrow(/finite/i);
    expect(() => rate(duel((t) => { t[0].participants[0].boostingPenaltyFactor = -Infinity; }))).toThrow(/finite/i);
  });

  it('rejects a non-finite input on an INELIGIBLE (frozen) participant too', () => {
    // Frozen players still feed the PL aggregate (D3/I3), so a non-finite μ there
    // poisons opponents all the same. Validation must not skip ineligible inputs.
    const bad = duel((t) => {
      t[1].participants[0].eligibleForProgression = false;
      t[1].participants[0].state.mu = Infinity;
    });
    expect(() => rate(bad)).toThrow(/finite/i);
  });

  it('names the offending playerId and field in the error', () => {
    const bad = duel((t) => {
      t[0].participants[0].state.sigma = NaN;
    });
    expect(() => rate(bad)).toThrow(/\ba\b/);
    expect(() => rate(bad)).toThrow(/sigma/);
  });

  it('still accepts a fully finite, structurally valid match (no false positives)', () => {
    expect(() => rate(match(arena8x2(), 'M-8x2'))).not.toThrow();
  });
});

// --------------------------------------------------------------------------
// Targeted case: provisional amplification (§5.2).
// --------------------------------------------------------------------------

describe('rate — provisional amplification (§5.2)', () => {
  it('applies placementAmp (2.0×) to a provisional player vs an established one', () => {
    // Two identical winners but one is provisional. The provisional one should
    // get placementAmp = params.placementAmp, the established one 1.0.
    const teams: TeamInput[] = [
      {
        teamId: 0,
        placement: 1,
        participants: [mkP('prov', 1000, 200, { prov: 5 }), mkP('estab', 1000, 200, { prov: 0 })],
      },
      { teamId: 1, placement: 2, participants: [mkP('foe', 1000, 200)] },
    ];
    const res = rate(match(teams));
    const prov = res.players.find((p) => p.playerId === 'prov')!;
    const estab = res.players.find((p) => p.playerId === 'estab')!;

    expect(prov.modifiers.placementAmp).toBe(P.placementAmp);
    expect(estab.modifiers.placementAmp).toBe(1);
    // Identical base (same μ/σ/placement) but the provisional gets 2× the swing.
    expect(prov.modifiers.plBaseDeltaMu).toBeCloseTo(estab.modifiers.plBaseDeltaMu, 9);
    expect(Math.abs(prov.modifiers.finalDeltaMu)).toBeGreaterThan(
      Math.abs(estab.modifiers.finalDeltaMu),
    );
  });
});

// --------------------------------------------------------------------------
// Targeted case: streak multiplier (§5.3).
// --------------------------------------------------------------------------

describe('rate — streak multiplier (§5.3)', () => {
  it('amplifies a gain for a player riding a win streak', () => {
    const teams: TeamInput[] = [
      {
        teamId: 0,
        placement: 1,
        participants: [mkP('hot', 1000, 120, { streak: 3 }), mkP('cold', 1000, 120, { streak: 0 })],
      },
      { teamId: 1, placement: 2, participants: [mkP('foe', 1000, 120)] },
    ];
    const res = rate(match(teams));
    const hot = res.players.find((p) => p.playerId === 'hot')!;
    const cold = res.players.find((p) => p.playerId === 'cold')!;

    expect(hot.modifiers.streakMult).toBeGreaterThan(1); // win streak boosts the gain
    expect(hot.modifiers.streakMult).toBeLessThanOrEqual(P.streakWinCeil);
    expect(cold.modifiers.streakMult).toBe(1);
    expect(hot.modifiers.finalDeltaMu).toBeGreaterThan(cold.modifiers.finalDeltaMu);
    expect(hot.newStreak).toBe(4); // win extends the streak
  });

  it('dampens a loss for a player on a losing streak (loss protection)', () => {
    const teams: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [mkP('foe', 1000, 120)] },
      {
        teamId: 1,
        placement: 2,
        participants: [mkP('sinking', 1000, 120, { streak: -3 }), mkP('flat', 1000, 120, { streak: 0 })],
      },
    ];
    const res = rate(match(teams));
    const sinking = res.players.find((p) => p.playerId === 'sinking')!;
    const flat = res.players.find((p) => p.playerId === 'flat')!;

    expect(sinking.modifiers.streakMult).toBeLessThan(1); // loss streak softens the loss
    expect(sinking.modifiers.streakMult).toBeGreaterThanOrEqual(P.streakLossFloor);
    expect(flat.modifiers.streakMult).toBe(1);
    // Both lose μ, but the sinking player loses LESS (closer to zero).
    expect(sinking.modifiers.finalDeltaMu).toBeGreaterThan(flat.modifiers.finalDeltaMu);
    expect(sinking.modifiers.finalDeltaMu).toBeLessThan(0);
    expect(sinking.newStreak).toBe(-4); // loss extends the losing streak
  });
});

// --------------------------------------------------------------------------
// Targeted case: soft cap (§5.4) — positive side only.
// --------------------------------------------------------------------------

describe('rate — soft cap (§5.4)', () => {
  it('attenuates a high-CR winner gain but never a loss', () => {
    const params: RatingParams = { ...P, softCapThreshold: 800, softCapScale: 200 };
    // High-CR winner (CR well above the lowered threshold) vs a low-CR foe.
    const teams: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [mkP('whale', 1800, 60, { params })] },
      { teamId: 1, placement: 2, participants: [mkP('minnow', 900, 200, { params })] },
    ];
    const res = rate({ matchId: 'M', mode: 'DUOS', teams, params });

    const whale = res.players.find((p) => p.playerId === 'whale')!;
    const minnow = res.players.find((p) => p.playerId === 'minnow')!;

    // Whale won (placement 1) → positive base → soft cap attenuates (< 1).
    expect(whale.modifiers.plBaseDeltaMu).toBeGreaterThan(0);
    expect(whale.modifiers.softCapFactor).toBeGreaterThan(0);
    expect(whale.modifiers.softCapFactor).toBeLessThan(1);
    // Minnow lost (placement 2) → loss → soft cap leaves it alone (= 1).
    expect(minnow.modifiers.softCapFactor).toBe(1);
  });

  it('leaves a winner below the threshold untouched (factor = 1)', () => {
    const teams: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [mkP('w', 1000, 120)] },
      { teamId: 1, placement: 2, participants: [mkP('l', 1000, 120)] },
    ];
    const res = rate(match(teams)); // default softCapThreshold = 5000, CR ~ 600
    expect(res.players.find((p) => p.playerId === 'w')!.modifiers.softCapFactor).toBe(1);
  });
});

// --------------------------------------------------------------------------
// Targeted case: dispersion clamp (§5.6 / I7).
// --------------------------------------------------------------------------

describe('rate — dispersion clamp (§5.6 / I7, σ-scaled)', () => {
  it('clamps a runaway swing to ±effectiveCap and flags it', () => {
    // Force a huge swing: tiny maxDeltaMu, provisional amp, big skill gap. The
    // cap is now σ-SCALED (Trinity C1): effectiveCap = maxDeltaMu·max(1, σ/ref).
    const params: RatingParams = { ...P, maxDeltaMu: 5 };
    const teams: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [mkP('hi', 500, 300, { prov: 5, params })] },
      { teamId: 1, placement: 2, participants: [mkP('lo', 1500, 60, { params })] },
    ];
    const res = rate({ matchId: 'M', mode: 'DUOS', teams, params });

    for (const p of res.players) {
      // Each player's bound is its OWN sigma-scaled cap, not the flat maxDeltaMu.
      const effCap = params.maxDeltaMu * Math.max(1, p.sigmaBefore / params.dispersionSigmaRef);
      expect(Math.abs(p.modifiers.finalDeltaMu)).toBeLessThanOrEqual(effCap + 1e-12);
      expect(p.modifiers.dispersionClamped).toBe(true);
      // μ moved by exactly the clamped amount.
      expect(p.muAfter - p.muBefore).toBeCloseTo(p.modifiers.finalDeltaMu, 12);
    }
  });

  it('does not flag a swing within the cap', () => {
    const res = rate(match(arena8x2(), 'M-8x2')); // default maxDeltaMu = 150
    for (const p of res.players) {
      expect(p.modifiers.dispersionClamped).toBe(false);
    }
  });
});

// --------------------------------------------------------------------------
// σ is sacrosanct (D1/I1): modifiers never touch σ; PL only shrinks it.
// --------------------------------------------------------------------------

describe('rate — σ sacrosanct (D1/I1)', () => {
  it('σ_after ≤ σ_before for every eligible player and never via modifiers', () => {
    const res = rate(match(arena8x2(), 'M-8x2'));
    for (const p of res.players) {
      expect(p.sigmaAfter).toBeLessThanOrEqual(p.sigmaBefore);
    }
  });

  it('crDelta = crAfter − crBefore exactly', () => {
    const res = rate(match(arena8x2(), 'M-8x2'));
    for (const p of res.players) {
      expect(p.crDelta).toBeCloseTo(p.crAfter - p.crBefore, 12);
    }
  });
});

// --------------------------------------------------------------------------
// Boosting penalty (§5.5) routed through rate.
// --------------------------------------------------------------------------

describe('rate — boosting penalty (§5.5)', () => {
  it('a fully-flagged booster (factor=1) gets zero gain on a win', () => {
    const teams: TeamInput[] = [
      {
        teamId: 0,
        placement: 1,
        participants: [mkP('booster', 1000, 150, { boost: 1 }), mkP('clean', 1000, 150, { boost: 0 })],
      },
      { teamId: 1, placement: 2, participants: [mkP('foe', 1000, 150)] },
    ];
    const res = rate(match(teams));
    const booster = res.players.find((p) => p.playerId === 'booster')!;
    const clean = res.players.find((p) => p.playerId === 'clean')!;

    expect(booster.modifiers.boostingFactor).toBe(0);
    expect(booster.modifiers.finalDeltaMu).toBe(0); // gain fully neutralised
    expect(clean.modifiers.boostingFactor).toBe(1);
    expect(clean.modifiers.finalDeltaMu).toBeGreaterThan(0);
  });

  it('DEC-A: a fully-flagged (f=1) winner has σ FULLY FROZEN (σ_after == σ_before)', () => {
    // §5.5 / DEC-A σ-freeze: for a flagged account (f>0) the σ-shrink is blended
    // back toward σ_before by (1−f); at f=1 σ is fully frozen. This denies a
    // max-flagged booster the CR uplift that σ-shrink would otherwise grant
    // (M4 σ-laundering countermeasure), even on a WIN that shrinks σ in raw PL.
    const teams: TeamInput[] = [
      {
        teamId: 0,
        placement: 1,
        participants: [mkP('flagged', 1000, 200, { boost: 1 }), mkP('clean', 1000, 200, { boost: 0 })],
      },
      { teamId: 1, placement: 2, participants: [mkP('foe', 1000, 200)] },
    ];
    const res = rate(match(teams));
    const flagged = res.players.find((p) => p.playerId === 'flagged')!;
    const clean = res.players.find((p) => p.playerId === 'clean')!;

    // f=1 ⇒ σ untouched, to the bit.
    expect(flagged.sigmaAfter).toBe(flagged.sigmaBefore);
    // The clean control on the SAME team/placement DID shrink σ via raw PL.
    expect(clean.sigmaAfter).toBeLessThan(clean.sigmaBefore);
    // σ-freeze never inflates σ, so the amended I1 bound trivially holds here.
    const i1Bound = Math.sqrt(flagged.sigmaBefore ** 2 + P.tau ** 2);
    expect(flagged.sigmaAfter).toBeLessThanOrEqual(i1Bound);
  });

  it('DEC-A: an out-of-range boost factor is clamped (f>1 ⇒ frozen, f<0 ⇒ clean PL)', () => {
    // boostingPenaltyFactor arrives from integrity bounded to [0,1], but rate()
    // only finite-checks it at the door (not range). The σ-freeze clamps
    // defensively: factor > 1 behaves as f=1 (σ frozen) and factor < 0 as f=0
    // (clean PL shrink), so a malformed upstream value can never inflate σ or
    // flip the freeze direction.
    const teams: TeamInput[] = [
      {
        teamId: 0,
        placement: 1,
        participants: [
          mkP('over', 1000, 200, { boost: 1.5 }), // > 1 → clamped to f=1
          mkP('under', 1000, 200, { boost: -0.5 }), // < 0 → clamped to f=0
        ],
      },
      { teamId: 1, placement: 2, participants: [mkP('foe', 1000, 200)] },
    ];
    const res = rate(match(teams));
    const over = res.players.find((p) => p.playerId === 'over')!;
    const under = res.players.find((p) => p.playerId === 'under')!;

    // factor > 1 clamps to f=1: σ fully frozen.
    expect(over.sigmaAfter).toBe(over.sigmaBefore);
    // factor < 0 clamps to f=0: clean PL shrink (σ drops).
    expect(under.sigmaAfter).toBeLessThan(under.sigmaBefore);
  });

  it('DEC-A: a partially-flagged (0<f<1) winner shrinks σ LESS than a clean twin', () => {
    // Monotone σ-freeze: σ_after = σ_before − (1−f)·(σ_before − σ_afterPL). At
    // intermediate f the flagged account keeps σ wider (shrinks less) than clean.
    const teams: TeamInput[] = [
      {
        teamId: 0,
        placement: 1,
        participants: [mkP('half', 1000, 200, { boost: 0.5 }), mkP('clean', 1000, 200, { boost: 0 })],
      },
      { teamId: 1, placement: 2, participants: [mkP('foe', 1000, 200)] },
    ];
    const res = rate(match(teams));
    const half = res.players.find((p) => p.playerId === 'half')!;
    const clean = res.players.find((p) => p.playerId === 'clean')!;

    // Both shrink (won the comparison), but the flagged one shrinks less.
    expect(half.sigmaAfter).toBeLessThan(half.sigmaBefore);
    expect(half.sigmaAfter).toBeGreaterThan(clean.sigmaAfter);
    // Exact blend: half's shrink is exactly half of clean's shrink (same PL share).
    const cleanShrink = clean.sigmaBefore - clean.sigmaAfter;
    const halfShrink = half.sigmaBefore - half.sigmaAfter;
    expect(halfShrink).toBeCloseTo(0.5 * cleanShrink, 9);
  });
});

// --------------------------------------------------------------------------
// Targeted case: provisional diver at HIGH σ — the σ-scaled cap (C1) no longer
// bites. A provisional newcomer (σ=350, placementAmp 2×) who hard-DIVES (last
// place vs a strong field) takes a real loss with |Δμ| > the flat maxDeltaMu
// (150): the σ-scaled cap widens to ~617, so the PL signal — not the cap —
// sets the placement-period climb/fall rate (Trinity C1, §5.6).
// --------------------------------------------------------------------------

describe('rate — provisional diver at high σ: σ-scaled cap no longer bites (C1)', () => {
  it('a provisional σ=350 hard-dive takes a loss with |Δμ| > 150 (flat cap)', () => {
    // Provisional newcomer at fresh σ=350 finishes dead last (placement 8) in an
    // 8-team lobby of settled, much stronger opponents — a big negative PL signal,
    // doubled by placementAmp. Pre-C1 the flat maxDeltaMu=150 would have clamped
    // it to exactly −150; now effectiveCap = 150·(350/85) ≈ 617, so the full
    // (capped-wider) loss lands.
    const teams: TeamInput[] = [];
    for (let t = 0; t < 7; t += 1) {
      // Seven strong, settled winners ahead of the diver.
      teams.push({
        teamId: t,
        placement: t + 1,
        participants: [mkP(`strong${t}`, 1800, 70)],
      });
    }
    // The provisional diver, dead last.
    teams.push({
      teamId: 7,
      placement: 8,
      participants: [mkP('diver', 1000, 350, { prov: 5 })],
    });

    const res = rate(match(teams));
    const diver = res.players.find((p) => p.playerId === 'diver')!;

    // It is a loss (μ falls), it is provisional-amplified, and the magnitude
    // exceeds the OLD flat cap (150) — the σ-scaled cap let the real loss through.
    expect(diver.modifiers.finalDeltaMu).toBeLessThan(0);
    expect(diver.modifiers.placementAmp).toBe(P.placementAmp);
    expect(Math.abs(diver.modifiers.finalDeltaMu)).toBeGreaterThan(150);

    // But it is still bounded by the σ-scaled effectiveCap (I7).
    const effCap = P.maxDeltaMu * Math.max(1, diver.sigmaBefore / P.dispersionSigmaRef);
    expect(Math.abs(diver.modifiers.finalDeltaMu)).toBeLessThanOrEqual(effCap + 1e-9);
  });
});

// --------------------------------------------------------------------------
// Targeted case: party-of-size > team-size rejection (spec §9).
//
// A party is the set of premade participants that share one `partyId`. By
// construction a party must fit inside a SINGLE team — its members queued and
// were placed together on that team. The spec (§9) mandates validating &
// testing "party of size > team size": a party whose member count exceeds the
// roster size of the team it sits on is a structurally corrupt input (it could
// only arise from a malformed lobby / ingestion bug), and it manifests as a
// party whose members necessarily SPAN more than one team. Either way the
// invariant is one comparison: every party must live on exactly one team and
// be no larger than that team. rate() reads `partyId`/`isPremade` (declared in
// ParticipantInput but otherwise unused) and rejects the violation up front,
// before any rating math runs. These tests pin both the failure and the
// absence of false positives on legitimate premades.
// --------------------------------------------------------------------------

describe('rate — party of size > team size rejected (spec §9)', () => {
  it('throws when a party is larger than the team it sits on (duos, party of 3)', () => {
    // Teams hold 2 (duos) but three players share one partyId — a party of 3
    // cannot fit any single team of 2. Structurally impossible; must be rejected.
    const teams: TeamInput[] = [
      {
        teamId: 0,
        placement: 1,
        participants: [
          mkP('sq-a', 1000, 150, { premade: true, partyId: 'sq' }),
          mkP('sq-b', 1010, 150, { premade: true, partyId: 'sq' }),
        ],
      },
      {
        teamId: 1,
        placement: 2,
        participants: [
          // Third member of party 'sq' leaks onto the opposing team.
          mkP('sq-c', 990, 150, { premade: true, partyId: 'sq' }),
          mkP('rando', 1000, 150),
        ],
      },
    ];
    expect(() => rate(match(teams))).toThrow(/party/i);
  });

  it('throws when a party spans two teams even if each team could hold it', () => {
    // Party 'duo' has exactly 2 members (≤ team size 2) but they sit on DIFFERENT
    // teams. A party must be contained in one team; a cross-team party means the
    // party-vs-its-single-team size relation is violated.
    const teams: TeamInput[] = [
      {
        teamId: 0,
        placement: 1,
        participants: [
          mkP('duo-a', 1000, 150, { premade: true, partyId: 'duo' }),
          mkP('solo-1', 1000, 150),
        ],
      },
      {
        teamId: 1,
        placement: 2,
        participants: [
          mkP('duo-b', 1000, 150, { premade: true, partyId: 'duo' }),
          mkP('solo-2', 1000, 150),
        ],
      },
    ];
    expect(() => rate(match(teams))).toThrow(/party/i);
  });

  it('names the offending partyId in the error', () => {
    const teams: TeamInput[] = [
      {
        teamId: 0,
        placement: 1,
        participants: [
          mkP('g-a', 1000, 150, { premade: true, partyId: 'ghost' }),
          mkP('g-b', 1000, 150, { premade: true, partyId: 'ghost' }),
        ],
      },
      {
        teamId: 1,
        placement: 2,
        participants: [
          mkP('g-c', 1000, 150, { premade: true, partyId: 'ghost' }),
          mkP('lone', 1000, 150),
        ],
      },
    ];
    expect(() => rate(match(teams))).toThrow(/ghost/);
  });

  it('accepts a legitimate full-team premade party (party size = team size)', () => {
    // A real duo: both premade members share a partyId AND sit on the same team.
    // Party size (2) = team size (2) → valid, no throw.
    const teams: TeamInput[] = [
      {
        teamId: 0,
        placement: 1,
        participants: [
          mkP('pal-a', 1000, 150, { premade: true, partyId: 'pals' }),
          mkP('pal-b', 1000, 150, { premade: true, partyId: 'pals' }),
        ],
      },
      {
        teamId: 1,
        placement: 2,
        participants: [
          mkP('foe-a', 1000, 150, { premade: true, partyId: 'foes' }),
          mkP('foe-b', 1000, 150, { premade: true, partyId: 'foes' }),
        ],
      },
    ];
    expect(() => rate(match(teams))).not.toThrow();
  });

  it('accepts solo players (no partyId) — undefined partyId is never a party', () => {
    // Two solo players with no partyId on different teams must NOT be grouped
    // into a phantom cross-team "undefined" party.
    const teams: TeamInput[] = [
      { teamId: 0, placement: 1, participants: [mkP('s1', 1000, 150)] },
      { teamId: 1, placement: 2, participants: [mkP('s2', 1000, 150)] },
    ];
    expect(() => rate(match(teams))).not.toThrow();
  });
});

// --------------------------------------------------------------------------
// Targeted case: caller-supplied PARAMS are validated at the door (spec §9 /
// §12 / I7 / I9).
//
// params arrives untrusted through MatchInput — per §12 it is season-tunable
// and loaded from JSONB, so a structurally-valid match can still carry a
// corrupt params object. rate() rigorously asserts finiteness of every
// participant/team scalar but, pre-fix, NEVER validated params: it neither
// called validateParams nor checked params for finiteness. The same door-check
// that guards every participant input must guard the params at that boundary.
//
// Two confirmed reproducers, both from a STRUCTURALLY-VALID match:
//   1. params.placementWeights[8] containing NaN ⇒ placementWeight() returns
//      NaN ⇒ every eligible player's placementWeight / finalDeltaMu / muAfter /
//      crAfter = NaN, breaking I9 ("no NaN/Infinity output").
//   2. params.maxDeltaMu = NaN ⇒ dispersionCap's clamp (Math.abs(d) > NaN is
//      false) silently DISABLES the I7 cap, so |Δμ_final| can exceed any bound
//      and dispersionClamped is wrongly false.
// --------------------------------------------------------------------------

describe('rate — validates caller-supplied params at the door (§9/§12/I7/I9)', () => {
  /** A clean, structurally-valid 8×2 match with an overridable params object. */
  function matchWithParams(params: RatingParams): MatchInput {
    return { matchId: 'M-params', mode: 'DUOS', teams: arena8x2(), params };
  }

  it('REGRESSION: NaN in placementWeights no longer poisons every eligible output (I9)', () => {
    // Pre-fix: a single NaN in the 8-team curve flowed through placementWeight()
    // and made EVERY eligible player's finalDeltaMu / muAfter / crAfter = NaN,
    // and rate() returned silently. It must now throw at the door.
    const params: RatingParams = {
      ...P,
      placementWeights: {
        ...P.placementWeights,
        8: [NaN, 1.12, 1.06, 1.01, 1.01, 1.06, 1.12, 1.2],
      },
    };
    expect(() => rate(matchWithParams(params))).toThrow(/finite/i);
  });

  it('REGRESSION: maxDeltaMu = NaN no longer silently disables the I7 cap', () => {
    // Pre-fix: dispersionCap's `Math.abs(d) > NaN` is always false, so the cap
    // was silently disabled — |Δμ_final| unbounded and dispersionClamped wrongly
    // false. rate() must reject a non-finite maxDeltaMu before any rating math.
    const params: RatingParams = { ...P, maxDeltaMu: NaN };
    expect(() => rate(matchWithParams(params))).toThrow(/finite/i);
  });

  it('rejects NaN, +Infinity, and -Infinity in every numeric params scalar', () => {
    const scalarFields = [
      'mu0', 'sigma0', 'beta', 'tau', 'kappa', 'scaleFactor', 'baseOffset',
      'placementAmp', 'placementMatchCount', 'streakLossFloor', 'streakWinCeil',
      'streakThreshold', 'softCapThreshold', 'softCapScale', 'maxDeltaMu',
      'resetAnchor', 'resetFactor', 'sigmaResetMult', 'sigmaResetCap',
    ] as const;
    for (const bad of [NaN, Infinity, -Infinity]) {
      for (const field of scalarFields) {
        const params = { ...P } as unknown as Record<string, number>;
        params[field] = bad;
        expect(() =>
          rate(matchWithParams(params as unknown as RatingParams)),
        ).toThrow(/finite/i);
      }
    }
  });

  it('rejects a non-finite entry anywhere in a placementWeights curve', () => {
    for (const bad of [NaN, Infinity, -Infinity]) {
      // Corrupt the LAST slot of the 6-team curve to prove the whole array is swept.
      const sixCurve = [...P.placementWeights[6]];
      sixCurve[sixCurve.length - 1] = bad;
      const params: RatingParams = {
        ...P,
        placementWeights: { ...P.placementWeights, 6: sixCurve },
      };
      expect(() => rate(matchWithParams(params))).toThrow(/finite/i);
    }
  });

  it('names the offending params field in the error', () => {
    const params: RatingParams = { ...P, maxDeltaMu: NaN };
    expect(() => rate(matchWithParams(params))).toThrow(/maxDeltaMu/);
  });

  it('still delegates the structural guards to validateParams (e.g. kappa)', () => {
    // params can be finite yet structurally invalid (spec §7). rate() must
    // surface those too — here a finite but out-of-range kappa.
    const params: RatingParams = { ...P, kappa: 1 };
    expect(() => rate(matchWithParams(params))).toThrow(/kappa/);
  });

  it('still accepts DEFAULT_PARAMS on a structurally-valid match (no false positive)', () => {
    expect(() => rate(matchWithParams(P))).not.toThrow();
  });
});
