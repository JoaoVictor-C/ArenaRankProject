import { describe, expect, it } from 'vitest';

import { DEFAULT_PARAMS, validateParams } from '../src/params.js';
import type { RatingParams } from '../src/types.js';

/**
 * Unit coverage for the hand-rolled, zero-dependency param guards (spec §7 / D6).
 * Each invalid mutation must throw; the default config must pass.
 */

function withDefault(over: Partial<RatingParams>): RatingParams {
  return { ...DEFAULT_PARAMS, ...over };
}

describe('DEFAULT_PARAMS (spec §5.1/§7 contract values)', () => {
  it('uses the renormalized (mean 1.0) DUOS placement weights', () => {
    expect(DEFAULT_PARAMS.placementWeights[8]).toEqual([
      1.0934, 1.0205, 0.9658, 0.9203, 0.9203, 0.9658, 1.0205, 1.0934,
    ]);
  });

  it('uses the renormalized (mean 1.0) TRIOS placement weights', () => {
    expect(DEFAULT_PARAMS.placementWeights[6]).toEqual([
      1.0793, 0.9878, 0.9329, 0.9329, 0.9878, 1.0793,
    ]);
  });

  it('placement weight curves average ~1.0 (mean-1.0 renormalization)', () => {
    const mean = (xs: number[]): number => xs.reduce((a, b) => a + b, 0) / xs.length;
    expect(mean(DEFAULT_PARAMS.placementWeights[8])).toBeCloseTo(1.0, 3);
    expect(mean(DEFAULT_PARAMS.placementWeights[6])).toBeCloseTo(1.0, 3);
  });

  it('sets dispersionSigmaRef default to 85', () => {
    expect(DEFAULT_PARAMS.dispersionSigmaRef).toBe(85);
  });
});

describe('validateParams (spec §7, D6 — zero-dep guards)', () => {
  it('accepts DEFAULT_PARAMS', () => {
    expect(() => validateParams(DEFAULT_PARAMS)).not.toThrow();
  });

  it('throws on non-positive sigma0', () => {
    expect(() => validateParams(withDefault({ sigma0: 0 }))).toThrow(/sigma0/);
    expect(() => validateParams(withDefault({ sigma0: -1 }))).toThrow(/sigma0/);
  });

  it('throws on non-positive beta', () => {
    expect(() => validateParams(withDefault({ beta: 0 }))).toThrow(/beta/);
    expect(() => validateParams(withDefault({ beta: -5 }))).toThrow(/beta/);
  });

  it('throws on kappa outside (0, 1)', () => {
    expect(() => validateParams(withDefault({ kappa: 0 }))).toThrow(/kappa/);
    expect(() => validateParams(withDefault({ kappa: 1 }))).toThrow(/kappa/);
    expect(() => validateParams(withDefault({ kappa: 1.5 }))).toThrow(/kappa/);
    expect(() => validateParams(withDefault({ kappa: -0.1 }))).toThrow(/kappa/);
  });

  it('throws on resetFactor outside [0, 1]', () => {
    expect(() => validateParams(withDefault({ resetFactor: -0.01 }))).toThrow(/resetFactor/);
    expect(() => validateParams(withDefault({ resetFactor: 1.01 }))).toThrow(/resetFactor/);
    // Boundaries are valid.
    expect(() => validateParams(withDefault({ resetFactor: 0 }))).not.toThrow();
    expect(() => validateParams(withDefault({ resetFactor: 1 }))).not.toThrow();
  });

  it('throws on streakLossFloor > 1', () => {
    expect(() => validateParams(withDefault({ streakLossFloor: 1.2 }))).toThrow(/streakLossFloor/);
    expect(() => validateParams(withDefault({ streakLossFloor: 1 }))).not.toThrow();
  });

  it('throws on streakWinCeil < 1', () => {
    expect(() => validateParams(withDefault({ streakWinCeil: 0.9 }))).toThrow(/streakWinCeil/);
    expect(() => validateParams(withDefault({ streakWinCeil: 1 }))).not.toThrow();
  });

  it('throws on missing DUOS (8-team) placement weights', () => {
    const params = withDefault({});
    // Replace the weights map without the 8-team curve.
    params.placementWeights = { 6: DEFAULT_PARAMS.placementWeights[6] };
    expect(() => validateParams(params)).toThrow(/8 teams/);
  });

  it('throws on missing TRIOS (6-team) placement weights', () => {
    const params = withDefault({});
    params.placementWeights = { 8: DEFAULT_PARAMS.placementWeights[8] };
    expect(() => validateParams(params)).toThrow(/6 teams/);
  });

  it('throws on NaN maxDeltaMu (finiteness guard)', () => {
    expect(() => validateParams(withDefault({ maxDeltaMu: NaN }))).toThrow(/maxDeltaMu/);
    expect(() => validateParams(withDefault({ maxDeltaMu: Infinity }))).toThrow(/maxDeltaMu/);
  });

  it('throws on a NaN placementWeights entry (per-entry finiteness guard)', () => {
    const params = withDefault({});
    params.placementWeights = {
      8: [1.0934, 1.0205, 0.9658, NaN, 0.9203, 0.9658, 1.0205, 1.0934],
      6: DEFAULT_PARAMS.placementWeights[6],
    };
    expect(() => validateParams(params)).toThrow(/placementWeights/);
  });

  it('skips a non-array placementWeights entry in the finiteness sweep', () => {
    // The finiteness sweep guards each curve with `if (!Array.isArray(weights)) continue`
    // so a malformed (non-array) value under some teamCount key does not crash the
    // sweep; the structural 8/6-team presence checks still run afterwards. Here the
    // required 8 & 6 curves are present and valid, plus a junk non-array key — the
    // non-array branch is taken and validation passes.
    const params = withDefault({});
    params.placementWeights = {
      8: DEFAULT_PARAMS.placementWeights[8],
      6: DEFAULT_PARAMS.placementWeights[6],
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      4: 'not-an-array' as unknown as number[],
    };
    expect(() => validateParams(params)).not.toThrow();
  });

  it('throws on dispersionSigmaRef <= 0', () => {
    expect(() => validateParams(withDefault({ dispersionSigmaRef: 0 }))).toThrow(
      /dispersionSigmaRef/,
    );
    expect(() => validateParams(withDefault({ dispersionSigmaRef: -10 }))).toThrow(
      /dispersionSigmaRef/,
    );
  });
});
