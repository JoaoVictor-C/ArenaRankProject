import { describe, expect, it } from 'vitest';
import { placementAmp } from '../../src/modifiers/placement-amp.js';
import { DEFAULT_PARAMS } from '../../src/params.js';
import type { PlayerState, RatingParams } from '../../src/types.js';

/**
 * Unit tests — placementAmp (spec §5.2).
 *
 *   placementAmp(state, params) =
 *     state.placementMatchesRemaining > 0 ? params.placementAmp : 1.0
 *
 * Provisional (remaining > 0) ⇒ params.placementAmp (DEFAULT 2.0).
 * Established (remaining === 0) ⇒ 1.0. Boundary is exactly 0.
 */

function makeState(placementMatchesRemaining: number): PlayerState {
  return {
    playerId: 'p1',
    mu: 1000,
    sigma: 350,
    cr: 200,
    currentStreak: 0,
    matchesPlayed: 0,
    placementMatchesRemaining,
    peakCr: 200,
  };
}

describe('placementAmp (spec §5.2)', () => {
  it('returns params.placementAmp (2.0) while provisional (remaining > 0)', () => {
    expect(placementAmp(makeState(10), DEFAULT_PARAMS)).toBe(2.0);
  });

  it('returns params.placementAmp on the last provisional match (remaining === 1)', () => {
    expect(placementAmp(makeState(1), DEFAULT_PARAMS)).toBe(2.0);
  });

  it('returns 1.0 once established at the boundary (remaining === 0)', () => {
    expect(placementAmp(makeState(0), DEFAULT_PARAMS)).toBe(1.0);
  });

  it('treats the boundary at exactly 0 (0 → 1.0, 1 → amp): strict > 0', () => {
    expect(placementAmp(makeState(0), DEFAULT_PARAMS)).toBe(1.0);
    expect(placementAmp(makeState(1), DEFAULT_PARAMS)).toBe(DEFAULT_PARAMS.placementAmp);
  });

  it('returns 1.0 for negative remaining (already established / over-counted)', () => {
    expect(placementAmp(makeState(-1), DEFAULT_PARAMS)).toBe(1.0);
    expect(placementAmp(makeState(-100), DEFAULT_PARAMS)).toBe(1.0);
  });

  it('honors a custom params.placementAmp value when provisional', () => {
    const customParams: RatingParams = { ...DEFAULT_PARAMS, placementAmp: 3.5 };
    expect(placementAmp(makeState(5), customParams)).toBe(3.5);
  });

  it('ignores params.placementAmp when established (always 1.0)', () => {
    const customParams: RatingParams = { ...DEFAULT_PARAMS, placementAmp: 3.5 };
    expect(placementAmp(makeState(0), customParams)).toBe(1.0);
  });

  it('returns a finite multiplier (no NaN / Infinity) on both sides of the boundary', () => {
    expect(Number.isFinite(placementAmp(makeState(7), DEFAULT_PARAMS))).toBe(true);
    expect(Number.isFinite(placementAmp(makeState(0), DEFAULT_PARAMS))).toBe(true);
  });

  it('is pure & deterministic — same input yields same output across calls', () => {
    const provisional = makeState(4);
    const established = makeState(0);
    expect(placementAmp(provisional, DEFAULT_PARAMS)).toBe(
      placementAmp(provisional, DEFAULT_PARAMS),
    );
    expect(placementAmp(established, DEFAULT_PARAMS)).toBe(
      placementAmp(established, DEFAULT_PARAMS),
    );
  });
});
