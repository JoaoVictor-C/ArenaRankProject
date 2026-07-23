import { describe, expect, it } from 'vitest';
import { placementWeight } from '../../src/modifiers/placement-weight.js';
import { DEFAULT_PARAMS } from '../../src/params.js';
import type { RatingParams } from '../../src/types.js';

/**
 * Unit tests for placementWeight — spec §5.1.
 *   placementWeight(placement, teamCount, params)
 *     = params.placementWeights[teamCount]?.[placement - 1] ?? 1.0
 *
 * Default curves (spec §5.1, mild/symmetric, RENORMALIZED to per-curve mean 1.0
 * per Trinity M3 — shape preserved, level divided by the old mean so net
 * per-match weight drift is zero by construction):
 *   8 teams (Duos):  [1.0934, 1.0205, 0.9658, 0.9203, 0.9203, 0.9658, 1.0205, 1.0934]
 *   6 teams (Trios): [1.0793, 0.9878, 0.9329, 0.9329, 0.9878, 1.0793]
 */
describe('placementWeight', () => {
  describe('exact default-curve values — 8 teams (Duos)', () => {
    const curve8 = [1.0934, 1.0205, 0.9658, 0.9203, 0.9203, 0.9658, 1.0205, 1.0934];

    it.each(
      curve8.map((expected, idx) => ({ placement: idx + 1, expected })),
    )(
      'placement $placement of 8 → $expected',
      ({ placement, expected }) => {
        expect(placementWeight(placement, 8, DEFAULT_PARAMS)).toBe(expected);
      },
    );

    it('is symmetric (best == worst, 2nd == 2nd-worst, ...)', () => {
      for (let p = 1; p <= 4; p++) {
        expect(placementWeight(p, 8, DEFAULT_PARAMS)).toBe(
          placementWeight(9 - p, 8, DEFAULT_PARAMS),
        );
      }
    });

    it('returns the full curve in order', () => {
      const got = Array.from({ length: 8 }, (_, i) =>
        placementWeight(i + 1, 8, DEFAULT_PARAMS),
      );
      expect(got).toEqual(curve8);
    });
  });

  describe('exact default-curve values — 6 teams (Trios)', () => {
    const curve6 = [1.0793, 0.9878, 0.9329, 0.9329, 0.9878, 1.0793];

    it.each(
      curve6.map((expected, idx) => ({ placement: idx + 1, expected })),
    )(
      'placement $placement of 6 → $expected',
      ({ placement, expected }) => {
        expect(placementWeight(placement, 6, DEFAULT_PARAMS)).toBe(expected);
      },
    );

    it('returns the full curve in order', () => {
      const got = Array.from({ length: 6 }, (_, i) =>
        placementWeight(i + 1, 6, DEFAULT_PARAMS),
      );
      expect(got).toEqual(curve6);
    });
  });

  describe('unknown teamCount → 1.0', () => {
    it.each([1, 2, 3, 4, 5, 7, 9, 10, 16, 100])(
      'teamCount %i (no curve defined) → 1.0',
      (teamCount) => {
        expect(placementWeight(1, teamCount, DEFAULT_PARAMS)).toBe(1.0);
      },
    );

    it('returns 1.0 for negative / zero teamCount', () => {
      expect(placementWeight(1, 0, DEFAULT_PARAMS)).toBe(1.0);
      expect(placementWeight(1, -1, DEFAULT_PARAMS)).toBe(1.0);
    });

    it('returns 1.0 when placementWeights is empty', () => {
      const empty: RatingParams = { ...DEFAULT_PARAMS, placementWeights: {} };
      expect(placementWeight(1, 8, empty)).toBe(1.0);
      expect(placementWeight(3, 6, empty)).toBe(1.0);
    });
  });

  describe('placement bounds — out-of-range index → 1.0', () => {
    it('placement below 1 (0) → 1.0 for a defined curve', () => {
      // index = placement - 1 = -1 → undefined → 1.0
      expect(placementWeight(0, 8, DEFAULT_PARAMS)).toBe(1.0);
      expect(placementWeight(0, 6, DEFAULT_PARAMS)).toBe(1.0);
    });

    it('negative placement → 1.0', () => {
      expect(placementWeight(-2, 8, DEFAULT_PARAMS)).toBe(1.0);
    });

    it('placement above teamCount → 1.0 for a defined curve', () => {
      // 8-team curve has indices 0..7; placement 9 → index 8 → undefined → 1.0
      expect(placementWeight(9, 8, DEFAULT_PARAMS)).toBe(1.0);
      expect(placementWeight(100, 8, DEFAULT_PARAMS)).toBe(1.0);
      // 6-team curve has indices 0..5; placement 7 → index 6 → undefined → 1.0
      expect(placementWeight(7, 6, DEFAULT_PARAMS)).toBe(1.0);
    });

    it('exact last valid placement still returns its curve value', () => {
      expect(placementWeight(8, 8, DEFAULT_PARAMS)).toBe(1.0934);
      expect(placementWeight(6, 6, DEFAULT_PARAMS)).toBe(1.0793);
    });
  });

  describe('respects custom params (not hard-coded to defaults)', () => {
    it('reads an arbitrary custom curve', () => {
      const custom: RatingParams = {
        ...DEFAULT_PARAMS,
        placementWeights: { 4: [3, 2, 1, 0.5] },
      };
      expect(placementWeight(1, 4, custom)).toBe(3);
      expect(placementWeight(2, 4, custom)).toBe(2);
      expect(placementWeight(4, 4, custom)).toBe(0.5);
      // default 8/6 curves are absent in this custom set → 1.0
      expect(placementWeight(1, 8, custom)).toBe(1.0);
    });

    it('is pure — repeated calls yield identical values', () => {
      const a = placementWeight(1, 8, DEFAULT_PARAMS);
      const b = placementWeight(1, 8, DEFAULT_PARAMS);
      expect(a).toBe(b);
      expect(a).toBe(1.0934);
    });
  });
});
