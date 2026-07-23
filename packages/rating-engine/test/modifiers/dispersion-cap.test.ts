import { describe, expect, it } from 'vitest';
import { DEFAULT_PARAMS } from '../../src/params.js';
import { dispersionCap } from '../../src/modifiers/dispersion-cap.js';
import type { RatingParams } from '../../src/types.js';

/**
 * Unit tests for dispersionCap — spec §5.6 (Trinity correction C1: SIGMA-SCALED;
 * applied last; enforces I7 against the σ-scaled effectiveCap).
 *
 *   effectiveCap = maxDeltaMu · max(1, sigmaBefore / dispersionSigmaRef)
 *   { value:        clamp(deltaMu, −effectiveCap, +effectiveCap),
 *     clamped:      |deltaMu| > effectiveCap,
 *     effectiveCap: effectiveCap }
 *
 * Defaults: maxDeltaMu = 150, dispersionSigmaRef = 85.
 */
describe('dispersionCap (§5.6, SIGMA-SCALED / Trinity C1)', () => {
  const floor = DEFAULT_PARAMS.maxDeltaMu; // 150 (cap at/below the σ reference)
  const sigmaRef = DEFAULT_PARAMS.dispersionSigmaRef; // 85

  describe('effectiveCap scales linearly with σ above the reference', () => {
    it('high σ (350) widens the cap to ~617 (150·350/85)', () => {
      const expected = floor * (350 / sigmaRef); // ≈ 617.647
      const r = dispersionCap(0, DEFAULT_PARAMS, 350);
      expect(r.effectiveCap).toBeCloseTo(expected, 9);
      expect(r.effectiveCap).toBeGreaterThan(600);
      expect(r.effectiveCap).toBeLessThan(620);
    });

    it('σ exactly at the reference (85) gives effectiveCap == maxDeltaMu', () => {
      const r = dispersionCap(0, DEFAULT_PARAMS, sigmaRef);
      expect(r.effectiveCap).toBe(floor);
    });

    it('σ below the reference floors effectiveCap at maxDeltaMu (no shrink)', () => {
      const r = dispersionCap(0, DEFAULT_PARAMS, 50);
      expect(r.effectiveCap).toBe(floor);
    });

    it('σ == 0 still floors effectiveCap at maxDeltaMu', () => {
      const r = dispersionCap(0, DEFAULT_PARAMS, 0);
      expect(r.effectiveCap).toBe(floor);
    });
  });

  describe('high σ (350): wide cap lets a large delta pass UNCLAMPED', () => {
    it('a +500 delta passes through unchanged (effectiveCap ≈ 617)', () => {
      const r = dispersionCap(500, DEFAULT_PARAMS, 350);
      expect(r.value).toBe(500);
      expect(r.clamped).toBe(false);
    });

    it('a −500 delta passes through unchanged (both signs)', () => {
      const r = dispersionCap(-500, DEFAULT_PARAMS, 350);
      expect(r.value).toBe(-500);
      expect(r.clamped).toBe(false);
    });

    it('a delta beyond the widened cap still clamps to ±effectiveCap', () => {
      const r = dispersionCap(1000, DEFAULT_PARAMS, 350);
      expect(r.value).toBeCloseTo(floor * (350 / sigmaRef), 9);
      expect(r.clamped).toBe(true);
    });

    it('clamps a too-large negative delta past the widened cap', () => {
      const r = dispersionCap(-1000, DEFAULT_PARAMS, 350);
      expect(r.value).toBeCloseTo(-floor * (350 / sigmaRef), 9);
      expect(r.clamped).toBe(true);
    });
  });

  describe('low σ (≤ 85): cap floors at 150, behaves like the flat cap', () => {
    it('within-range positive delta passes through (clamped=false)', () => {
      const r = dispersionCap(42.5, DEFAULT_PARAMS, sigmaRef);
      expect(r.value).toBe(42.5);
      expect(r.clamped).toBe(false);
      expect(r.effectiveCap).toBe(floor);
    });

    it('within-range negative delta passes through (clamped=false)', () => {
      const r = dispersionCap(-99.25, DEFAULT_PARAMS, 60);
      expect(r.value).toBe(-99.25);
      expect(r.clamped).toBe(false);
      expect(r.effectiveCap).toBe(floor);
    });

    it('passes through zero (clamped=false)', () => {
      const r = dispersionCap(0, DEFAULT_PARAMS, sigmaRef);
      expect(r.value).toBe(0);
      expect(r.clamped).toBe(false);
    });

    it('clamps a too-large positive delta to +150 (clamped=true)', () => {
      const r = dispersionCap(500, DEFAULT_PARAMS, sigmaRef);
      expect(r.value).toBe(floor);
      expect(r.clamped).toBe(true);
    });

    it('clamps a too-large negative delta to −150 (clamped=true)', () => {
      const r = dispersionCap(-500, DEFAULT_PARAMS, 50);
      expect(r.value).toBe(-floor);
      expect(r.clamped).toBe(true);
    });
  });

  describe('exact boundary (|deltaMu| == effectiveCap) ⇒ not clamped', () => {
    it('exact +effectiveCap at the σ floor passes through', () => {
      const r = dispersionCap(floor, DEFAULT_PARAMS, sigmaRef);
      expect(r.value).toBe(floor);
      expect(r.clamped).toBe(false);
    });

    it('exact −effectiveCap at the σ floor passes through', () => {
      const r = dispersionCap(-floor, DEFAULT_PARAMS, sigmaRef);
      expect(r.value).toBe(-floor);
      expect(r.clamped).toBe(false);
    });

    it('exact +effectiveCap at high σ passes through (clamped=false)', () => {
      const high = floor * (350 / sigmaRef);
      const r = dispersionCap(high, DEFAULT_PARAMS, 350);
      expect(r.value).toBe(high);
      expect(r.clamped).toBe(false);
    });

    it('just past the high-σ boundary clamps', () => {
      const high = floor * (350 / sigmaRef);
      const r = dispersionCap(high + 0.0001, DEFAULT_PARAMS, 350);
      expect(r.value).toBe(high);
      expect(r.clamped).toBe(true);
    });

    it('just inside the floor boundary is not clamped', () => {
      const r = dispersionCap(floor - 0.0001, DEFAULT_PARAMS, sigmaRef);
      expect(r.value).toBe(floor - 0.0001);
      expect(r.clamped).toBe(false);
    });
  });

  describe('honours a custom maxDeltaMu / dispersionSigmaRef from params', () => {
    const tight: RatingParams = {
      ...DEFAULT_PARAMS,
      maxDeltaMu: 10,
      dispersionSigmaRef: 100,
    };

    it('uses the supplied floor cap at/below the custom reference', () => {
      const r = dispersionCap(25, tight, 100);
      expect(r.value).toBe(10);
      expect(r.clamped).toBe(true);
      expect(r.effectiveCap).toBe(10);
    });

    it('scales the custom cap with σ above the custom reference', () => {
      const r = dispersionCap(15, tight, 200); // cap = 10 · 200/100 = 20
      expect(r.effectiveCap).toBe(20);
      expect(r.value).toBe(15);
      expect(r.clamped).toBe(false);
    });

    it('respects the custom exact boundary as not clamped', () => {
      const r = dispersionCap(-10, tight, 100);
      expect(r.value).toBe(-10);
      expect(r.clamped).toBe(false);
    });
  });

  describe('I7: |value| ≤ effectiveCap and output is finite for any input', () => {
    const cases: Array<{ d: number; sigma: number }> = [
      { d: -1e6, sigma: 350 },
      { d: -617.7, sigma: 350 },
      { d: -0.5, sigma: 85 },
      { d: 0, sigma: 85 },
      { d: 0.5, sigma: 40 },
      { d: 150.0001, sigma: 85 },
      { d: 1e6, sigma: 200 },
    ];
    for (const { d, sigma } of cases) {
      it(`enforces the cap for deltaMu=${d}, σ=${sigma}`, () => {
        const r = dispersionCap(d, DEFAULT_PARAMS, sigma);
        expect(Number.isFinite(r.value)).toBe(true);
        expect(Math.abs(r.value)).toBeLessThanOrEqual(r.effectiveCap);
      });
    }
  });
});
