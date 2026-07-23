import { describe, expect, it } from 'vitest';
import { toCR } from '../src/cr.js';
import { DEFAULT_PARAMS } from '../src/params.js';
import type { RatingParams } from '../src/types.js';

describe('toCR', () => {
  describe('spec §7 CR anchor table', () => {
    // CR = (μ − 3σ)·scaleFactor + baseOffset, with scaleFactor=1, baseOffset=250.
    it('fresh 1000/350 → 200', () => {
      expect(toCR(1000, 350, DEFAULT_PARAMS)).toBe(200);
    });

    it('post-placements 1000/150 → 800', () => {
      expect(toCR(1000, 150, DEFAULT_PARAMS)).toBe(800);
    });

    it('established 1000/85 → ~1000 (within rounding)', () => {
      // (1000 − 3*85) + 250 = (1000 − 255) + 250 = 995, i.e. ~1000 to the nearest 10.
      const cr = toCR(1000, 85, DEFAULT_PARAMS);
      expect(cr).toBe(995);
      // "~1000 within rounding": rounds to 1000 at the nearest-10 ladder bucket.
      expect(Math.round(cr / 10) * 10).toBe(1000);
      expect(Math.abs(cr - 1000)).toBeLessThanOrEqual(5);
    });

    it('strong 1300/80 → 1310', () => {
      expect(toCR(1300, 80, DEFAULT_PARAMS)).toBe(1310);
    });

    it('elite 1800/70 → 1840', () => {
      expect(toCR(1800, 70, DEFAULT_PARAMS)).toBe(1840);
    });
  });

  describe('formula (spec §5/§7)', () => {
    it('equals (μ − 3σ)·scaleFactor + baseOffset', () => {
      const mu = 1234;
      const sigma = 99;
      const expected = (mu - 3 * sigma) * DEFAULT_PARAMS.scaleFactor + DEFAULT_PARAMS.baseOffset;
      expect(toCR(mu, sigma, DEFAULT_PARAMS)).toBe(expected);
    });

    it('honors a non-default scaleFactor', () => {
      const params: RatingParams = { ...DEFAULT_PARAMS, scaleFactor: 2, baseOffset: 0 };
      // (1000 − 3*100) * 2 + 0 = 700 * 2 = 1400
      expect(toCR(1000, 100, params)).toBe(1400);
    });

    it('honors a non-default baseOffset', () => {
      const params: RatingParams = { ...DEFAULT_PARAMS, scaleFactor: 1, baseOffset: 500 };
      // (1000 − 300) + 500 = 1200
      expect(toCR(1000, 100, params)).toBe(1200);
    });

    it('can produce a negative CR for very uncertain low μ', () => {
      const params: RatingParams = { ...DEFAULT_PARAMS, scaleFactor: 1, baseOffset: 0 };
      // (100 − 3*350) = 100 − 1050 = −950
      expect(toCR(100, 350, params)).toBe(-950);
    });
  });

  describe('I8 — strictly increasing in μ', () => {
    it('larger μ ⇒ larger CR (σ fixed)', () => {
      const sigma = 120;
      const a = toCR(900, sigma, DEFAULT_PARAMS);
      const b = toCR(1000, sigma, DEFAULT_PARAMS);
      const c = toCR(1100, sigma, DEFAULT_PARAMS);
      expect(a).toBeLessThan(b);
      expect(b).toBeLessThan(c);
    });

    it('holds across a sweep', () => {
      const sigma = 200;
      let prev = -Infinity;
      for (let mu = -500; mu <= 2500; mu += 13.7) {
        const cur = toCR(mu, sigma, DEFAULT_PARAMS);
        expect(cur).toBeGreaterThan(prev);
        prev = cur;
      }
    });
  });

  describe('I8 — strictly decreasing in σ', () => {
    it('larger σ ⇒ smaller CR (μ fixed)', () => {
      const mu = 1000;
      const a = toCR(mu, 70, DEFAULT_PARAMS);
      const b = toCR(mu, 150, DEFAULT_PARAMS);
      const c = toCR(mu, 350, DEFAULT_PARAMS);
      expect(a).toBeGreaterThan(b);
      expect(b).toBeGreaterThan(c);
    });

    it('holds across a sweep', () => {
      const mu = 1500;
      let prev = Infinity;
      for (let sigma = 1; sigma <= 400; sigma += 3.3) {
        const cur = toCR(mu, sigma, DEFAULT_PARAMS);
        expect(cur).toBeLessThan(prev);
        prev = cur;
      }
    });
  });

  describe('pure & deterministic', () => {
    it('returns the same value on repeated calls', () => {
      const first = toCR(1042, 137, DEFAULT_PARAMS);
      const second = toCR(1042, 137, DEFAULT_PARAMS);
      expect(second).toBe(first);
    });

    it('does not mutate params', () => {
      const params: RatingParams = { ...DEFAULT_PARAMS };
      const snapshot = JSON.stringify(params);
      toCR(1000, 100, params);
      expect(JSON.stringify(params)).toBe(snapshot);
    });

    it('never returns NaN/Infinity for finite inputs (I9)', () => {
      expect(Number.isFinite(toCR(0, 0, DEFAULT_PARAMS))).toBe(true);
      expect(Number.isFinite(toCR(-1000, 350, DEFAULT_PARAMS))).toBe(true);
      expect(Number.isFinite(toCR(5000, 1, DEFAULT_PARAMS))).toBe(true);
    });
  });
});
