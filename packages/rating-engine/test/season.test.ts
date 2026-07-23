import { describe, it, expect } from 'vitest';
import { softReset } from '../src/season.js';
import { DEFAULT_PARAMS } from '../src/params.js';
import type { PlayerState, RatingParams } from '../src/types.js';

/**
 * Unit tests for season soft-reset (spec §5 / D4 / proposal §13.3).
 *
 * softReset is the ONLY operation permitted to INCREASE σ (D1/I1).
 *
 * Formulae under test:
 *   muNew   = resetAnchor + (mu − resetAnchor) · resetFactor
 *   sigmaNew = min(sigma · sigmaResetMult, sigmaResetCap)
 *   crNew    = (muNew − 3·sigmaNew) · scaleFactor + baseOffset
 *   placementMatchesRemaining = placementMatchCount
 *   matchesPlayed = 0
 *   currentStreak = 0
 *   peakCr = crNew
 *   playerId preserved
 */

// Local reference of the conservative CR derivation (spec §6 toCR), used only
// as a test oracle so this unit's tests do not depend on cr.ts being filled in.
function refCR(mu: number, sigma: number, p: RatingParams): number {
  return (mu - 3 * sigma) * p.scaleFactor + p.baseOffset;
}

function makeState(overrides: Partial<PlayerState> = {}): PlayerState {
  return {
    playerId: 'player-1',
    mu: 1500,
    sigma: 120,
    cr: refCR(1500, 120, DEFAULT_PARAMS),
    currentStreak: 4,
    matchesPlayed: 87,
    placementMatchesRemaining: 0,
    peakCr: 1600,
    ...overrides,
  };
}

describe('softReset — formula exactness', () => {
  it('shrinks mu toward resetAnchor by resetFactor (above anchor)', () => {
    const state = makeState({ mu: 1500 });
    const out = softReset(state, DEFAULT_PARAMS);
    // 1000 + (1500 − 1000)·0.5 = 1250
    expect(out.mu).toBe(1250);
  });

  it('pulls mu up toward resetAnchor when below anchor', () => {
    const state = makeState({ mu: 600 });
    const out = softReset(state, DEFAULT_PARAMS);
    // 1000 + (600 − 1000)·0.5 = 800
    expect(out.mu).toBe(800);
  });

  it('leaves mu unchanged when exactly at the anchor', () => {
    const state = makeState({ mu: DEFAULT_PARAMS.resetAnchor });
    const out = softReset(state, DEFAULT_PARAMS);
    expect(out.mu).toBe(DEFAULT_PARAMS.resetAnchor);
  });

  it('applies the general mu formula for arbitrary inputs', () => {
    const params: RatingParams = { ...DEFAULT_PARAMS, resetAnchor: 900, resetFactor: 0.3 };
    const state = makeState({ mu: 1400 });
    const out = softReset(state, params);
    // 900 + (1400 − 900)·0.3 = 1050
    expect(out.mu).toBeCloseTo(1050, 12);
  });

  it('inflates sigma by sigmaResetMult when under the cap', () => {
    const state = makeState({ sigma: 100 });
    const out = softReset(state, DEFAULT_PARAMS);
    // min(100·1.5, 350) = 150
    expect(out.sigma).toBe(150);
  });

  it('increases sigma (I1: only softReset may raise σ)', () => {
    const state = makeState({ sigma: 80 });
    const out = softReset(state, DEFAULT_PARAMS);
    expect(out.sigma).toBeGreaterThan(state.sigma);
  });

  it('derives crNew = (muNew − 3·sigmaNew)·scaleFactor + baseOffset', () => {
    const state = makeState({ mu: 1500, sigma: 100 });
    const out = softReset(state, DEFAULT_PARAMS);
    const expectedMu = 1250;
    const expectedSigma = 150;
    expect(out.cr).toBeCloseTo(refCR(expectedMu, expectedSigma, DEFAULT_PARAMS), 12);
    // (1250 − 450)·1 + 250 = 1050
    expect(out.cr).toBeCloseTo(1050, 12);
  });

  it('honors non-default scaleFactor / baseOffset in crNew', () => {
    const params: RatingParams = { ...DEFAULT_PARAMS, scaleFactor: 2, baseOffset: 100 };
    const state = makeState({ mu: 1200, sigma: 90 });
    const out = softReset(state, params);
    const muNew = 1000 + (1200 - 1000) * 0.5; // 1100
    const sigmaNew = Math.min(90 * 1.5, 350); // 135
    expect(out.cr).toBeCloseTo(refCR(muNew, sigmaNew, params), 12);
  });
});

describe('softReset — sigma cap boundary', () => {
  it('caps sigma at sigmaResetCap when sigma·mult would exceed it', () => {
    // 300·1.5 = 450 → capped at 350
    const state = makeState({ sigma: 300 });
    const out = softReset(state, DEFAULT_PARAMS);
    expect(out.sigma).toBe(DEFAULT_PARAMS.sigmaResetCap);
    expect(out.sigma).toBe(350);
  });

  it('sigma exactly at the cap boundary (sigma·1.5 === 350)', () => {
    // 350 / 1.5 = 233.333… → ·1.5 = 350 exactly equals the cap
    const sigma = DEFAULT_PARAMS.sigmaResetCap / DEFAULT_PARAMS.sigmaResetMult;
    const state = makeState({ sigma });
    const out = softReset(state, DEFAULT_PARAMS);
    expect(out.sigma).toBeCloseTo(350, 9);
    expect(out.sigma).toBeLessThanOrEqual(DEFAULT_PARAMS.sigmaResetCap);
  });

  it('does not cap when just under the boundary', () => {
    const sigma = 200; // 200·1.5 = 300 < 350
    const out = softReset(makeState({ sigma }), DEFAULT_PARAMS);
    expect(out.sigma).toBe(300);
  });

  it('never returns sigma above sigmaResetCap for large inputs', () => {
    const out = softReset(makeState({ sigma: 10_000 }), DEFAULT_PARAMS);
    expect(out.sigma).toBe(DEFAULT_PARAMS.sigmaResetCap);
  });
});

describe('softReset — provisional / placement reset', () => {
  it('reopens placement matches to placementMatchCount', () => {
    const out = softReset(makeState({ placementMatchesRemaining: 0 }), DEFAULT_PARAMS);
    expect(out.placementMatchesRemaining).toBe(DEFAULT_PARAMS.placementMatchCount);
    expect(out.placementMatchesRemaining).toBe(10);
  });

  it('uses a custom placementMatchCount', () => {
    const params: RatingParams = { ...DEFAULT_PARAMS, placementMatchCount: 5 };
    const out = softReset(makeState(), params);
    expect(out.placementMatchesRemaining).toBe(5);
  });

  it('zeroes matchesPlayed', () => {
    const out = softReset(makeState({ matchesPlayed: 87 }), DEFAULT_PARAMS);
    expect(out.matchesPlayed).toBe(0);
  });

  it('zeroes currentStreak (both winning and losing streaks)', () => {
    expect(softReset(makeState({ currentStreak: 9 }), DEFAULT_PARAMS).currentStreak).toBe(0);
    expect(softReset(makeState({ currentStreak: -6 }), DEFAULT_PARAMS).currentStreak).toBe(0);
  });

  it('resets peakCr to the freshly derived crNew', () => {
    const state = makeState({ mu: 1500, sigma: 100, peakCr: 9999 });
    const out = softReset(state, DEFAULT_PARAMS);
    expect(out.peakCr).toBe(out.cr);
    expect(out.peakCr).not.toBe(9999);
  });

  it('preserves playerId', () => {
    const out = softReset(makeState({ playerId: 'abc-123' }), DEFAULT_PARAMS);
    expect(out.playerId).toBe('abc-123');
  });
});

describe('softReset — purity & determinism', () => {
  it('does not mutate the input state', () => {
    const state = makeState();
    const snapshot = structuredClone(state);
    softReset(state, DEFAULT_PARAMS);
    expect(state).toEqual(snapshot);
  });

  it('returns a new object reference', () => {
    const state = makeState();
    const out = softReset(state, DEFAULT_PARAMS);
    expect(out).not.toBe(state);
  });

  it('is deterministic: identical inputs deep-equal across calls', () => {
    const a = softReset(makeState(), DEFAULT_PARAMS);
    const b = softReset(makeState(), DEFAULT_PARAMS);
    expect(a).toEqual(b);
  });

  it('produces no NaN / Infinity for structurally valid input (I9)', () => {
    const out = softReset(makeState({ mu: 1800, sigma: 70 }), DEFAULT_PARAMS);
    for (const v of [out.mu, out.sigma, out.cr, out.peakCr]) {
      expect(Number.isFinite(v)).toBe(true);
    }
  });

  it('returns exactly the PlayerState shape (no extra / missing keys)', () => {
    const out = softReset(makeState(), DEFAULT_PARAMS);
    expect(Object.keys(out).sort()).toEqual(
      [
        'cr',
        'currentStreak',
        'matchesPlayed',
        'mu',
        'peakCr',
        'placementMatchesRemaining',
        'playerId',
        'sigma',
      ].sort(),
    );
  });
});
