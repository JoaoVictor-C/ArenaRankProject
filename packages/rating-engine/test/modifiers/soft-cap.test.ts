import { describe, it, expect } from 'vitest';
import { softCapFactor } from '../../src/modifiers/soft-cap.js';
import { DEFAULT_PARAMS } from '../../src/params.js';
import type { RatingParams } from '../../src/types.js';

/**
 * Unit tests for softCapFactor — spec §5.4.
 *
 *   deltaMu > 0 && cr > softCapThreshold
 *     ? 1 / (1 + (cr − softCapThreshold) / softCapScale)
 *     : 1.0
 *
 * Always in (0, 1]; positive side only; no hard ceiling.
 *
 * DEFAULT_PARAMS: softCapThreshold = 5000, softCapScale = 1000.
 */

const { softCapThreshold, softCapScale } = DEFAULT_PARAMS;

describe('softCapFactor', () => {
  describe('no effect below the threshold', () => {
    it('returns 1.0 when cr is well below softCapThreshold (gain)', () => {
      expect(softCapFactor(1000, 5, DEFAULT_PARAMS)).toBe(1.0);
    });

    it('returns 1.0 at cr just below softCapThreshold (gain)', () => {
      expect(softCapFactor(softCapThreshold - 1, 5, DEFAULT_PARAMS)).toBe(1.0);
    });

    it('returns 1.0 for a typical mid-ladder player (gain)', () => {
      expect(softCapFactor(2500, 12, DEFAULT_PARAMS)).toBe(1.0);
    });
  });

  describe('exactly at the threshold', () => {
    it('returns 1.0 when cr === softCapThreshold (strict > comparison)', () => {
      expect(softCapFactor(softCapThreshold, 5, DEFAULT_PARAMS)).toBe(1.0);
    });
  });

  describe('no effect on losses (deltaMu <= 0)', () => {
    it('returns 1.0 on a loss even far above the threshold', () => {
      expect(softCapFactor(9000, -10, DEFAULT_PARAMS)).toBe(1.0);
    });

    it('returns 1.0 when deltaMu === 0 above the threshold', () => {
      expect(softCapFactor(9000, 0, DEFAULT_PARAMS)).toBe(1.0);
    });

    it('returns 1.0 on a loss below the threshold', () => {
      expect(softCapFactor(1000, -3, DEFAULT_PARAMS)).toBe(1.0);
    });

    it('returns 1.0 on a loss exactly at the threshold', () => {
      expect(softCapFactor(softCapThreshold, -1, DEFAULT_PARAMS)).toBe(1.0);
    });
  });

  describe('diminishing returns above the threshold', () => {
    it('applies 1/(1 + (cr - threshold)/scale) one scale-unit above', () => {
      // cr = threshold + scale → 1/(1 + 1) = 0.5
      const cr = softCapThreshold + softCapScale;
      expect(softCapFactor(cr, 5, DEFAULT_PARAMS)).toBeCloseTo(0.5, 12);
    });

    it('matches the closed form at an arbitrary point above the threshold', () => {
      const cr = 6500;
      const expected = 1 / (1 + (cr - softCapThreshold) / softCapScale);
      expect(softCapFactor(cr, 1, DEFAULT_PARAMS)).toBeCloseTo(expected, 12);
    });

    it('is strictly below 1.0 just above the threshold', () => {
      const f = softCapFactor(softCapThreshold + 0.001, 5, DEFAULT_PARAMS);
      expect(f).toBeLessThan(1.0);
      expect(f).toBeGreaterThan(0);
    });

    it('is monotonically decreasing as cr rises above the threshold', () => {
      const crs = [5001, 5500, 6000, 8000, 12000, 50000];
      const factors = crs.map((cr) => softCapFactor(cr, 5, DEFAULT_PARAMS));
      for (let i = 1; i < factors.length; i++) {
        expect(factors[i]).toBeLessThan(factors[i - 1]);
      }
    });

    it('approaches but never reaches 0 for very large cr (no hard ceiling)', () => {
      const f = softCapFactor(1e9, 5, DEFAULT_PARAMS);
      expect(f).toBeGreaterThan(0);
      expect(f).toBeLessThan(1e-3);
    });
  });

  describe('factor always in (0, 1]', () => {
    const sampleCrs = [
      -1000, 0, 100, 1000, softCapThreshold - 0.0001, softCapThreshold,
      softCapThreshold + 0.0001, 5500, 7000, 9000, 25000, 1e6,
    ];

    it('returns a value in (0, 1] across a sweep of cr values (gains)', () => {
      for (const cr of sampleCrs) {
        const f = softCapFactor(cr, 7, DEFAULT_PARAMS);
        expect(f).toBeGreaterThan(0);
        expect(f).toBeLessThanOrEqual(1);
        expect(Number.isFinite(f)).toBe(true);
      }
    });

    it('returns exactly 1.0 whenever the cap is inactive', () => {
      // Inactive because below threshold:
      expect(softCapFactor(100, 7, DEFAULT_PARAMS)).toBe(1.0);
      // Inactive because it is a loss:
      expect(softCapFactor(50000, -7, DEFAULT_PARAMS)).toBe(1.0);
    });
  });

  describe('parameterization (uses params, not hard-coded constants)', () => {
    it('respects a custom softCapThreshold/softCapScale', () => {
      const custom: RatingParams = {
        ...DEFAULT_PARAMS,
        softCapThreshold: 1000,
        softCapScale: 200,
      };
      // Below custom threshold → no effect.
      expect(softCapFactor(900, 5, custom)).toBe(1.0);
      // At custom threshold → no effect.
      expect(softCapFactor(1000, 5, custom)).toBe(1.0);
      // One scale-unit above (1200) → 0.5.
      expect(softCapFactor(1200, 5, custom)).toBeCloseTo(0.5, 12);
    });
  });
});
