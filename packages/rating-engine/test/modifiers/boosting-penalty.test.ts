import { describe, expect, it } from 'vitest';
import { rating, rate } from 'openskill';
import { boostingPenalty } from '../../src/modifiers/boosting-penalty.js';
import { DEFAULT_PARAMS } from '../../src/params.js';

/**
 * Unit tests for boostingPenalty — spec §5.5.
 *
 *   boostingPenalty(deltaMu, factor) =
 *     deltaMu > 0 ? (1 − clamp(factor, 0, 1)) : 1.0
 *
 * It returns a MULTIPLIER applied (positive side only) to Δμ so a flagged
 * booster's gains are attenuated. Losses are never touched (never turn a loss
 * into a gain — spec D2).
 */
describe('boostingPenalty (§5.5)', () => {
  describe('factor boundaries on gains (deltaMu > 0)', () => {
    it('factor = 0 leaves gains untouched (multiplier 1.0)', () => {
      expect(boostingPenalty(10, 0)).toBe(1.0);
    });

    it('factor = 1 fully neutralises gains (multiplier 0)', () => {
      expect(boostingPenalty(10, 1)).toBe(0);
    });

    it('factor = 0.5 halves gains (multiplier 0.5)', () => {
      expect(boostingPenalty(10, 0.5)).toBe(0.5);
    });

    it('factor = 0.25 yields multiplier 0.75', () => {
      expect(boostingPenalty(42, 0.25)).toBeCloseTo(0.75, 12);
    });

    it('returns 1 - factor for any factor in [0,1] on a gain', () => {
      for (const f of [0, 0.1, 0.2, 0.33, 0.5, 0.66, 0.8, 0.9, 1]) {
        expect(boostingPenalty(7, f)).toBeCloseTo(1 - f, 12);
      }
    });
  });

  describe('input clamping (factor outside [0,1])', () => {
    it('clamps factor > 1 down to 1 → multiplier 0', () => {
      expect(boostingPenalty(10, 1.5)).toBe(0);
      expect(boostingPenalty(10, 2)).toBe(0);
      expect(boostingPenalty(10, 1000)).toBe(0);
    });

    it('clamps factor < 0 up to 0 → multiplier 1.0', () => {
      expect(boostingPenalty(10, -0.5)).toBe(1.0);
      expect(boostingPenalty(10, -1)).toBe(1.0);
      expect(boostingPenalty(10, -1000)).toBe(1.0);
    });

    it('clamps positive Infinity factor to 1 → multiplier 0', () => {
      expect(boostingPenalty(10, Number.POSITIVE_INFINITY)).toBe(0);
    });

    it('clamps negative Infinity factor to 0 → multiplier 1.0', () => {
      expect(boostingPenalty(10, Number.NEGATIVE_INFINITY)).toBe(1.0);
    });
  });

  describe('losses and zero are never penalised (positive side only — D2)', () => {
    it('deltaMu < 0 returns 1.0 regardless of factor', () => {
      for (const f of [0, 0.5, 1, 1.5, -3]) {
        expect(boostingPenalty(-10, f)).toBe(1.0);
      }
    });

    it('deltaMu === 0 returns 1.0 (not strictly > 0)', () => {
      expect(boostingPenalty(0, 0.5)).toBe(1.0);
      expect(boostingPenalty(0, 1)).toBe(1.0);
    });

    it('a large penalty factor cannot flip a loss into a gain', () => {
      const deltaMu = -25;
      const penalised = deltaMu * boostingPenalty(deltaMu, 1);
      expect(penalised).toBe(-25);
      expect(penalised).toBeLessThan(0);
    });
  });

  describe('determinism & numeric safety (I2/I9)', () => {
    it('is a pure function — same inputs give same output', () => {
      expect(boostingPenalty(13, 0.37)).toBe(boostingPenalty(13, 0.37));
    });

    it('never returns NaN or Infinity for finite-multiplier inputs', () => {
      for (const d of [-100, -1, 0, 1, 100]) {
        for (const f of [-2, -1, 0, 0.5, 1, 2, 100]) {
          const m = boostingPenalty(d, f);
          expect(Number.isFinite(m)).toBe(true);
        }
      }
    });

    it('multiplier always lies in [0, 1]', () => {
      for (const d of [-50, 0, 50]) {
        for (const f of [-5, 0, 0.5, 1, 5]) {
          const m = boostingPenalty(d, f);
          expect(m).toBeGreaterThanOrEqual(0);
          expect(m).toBeLessThanOrEqual(1);
        }
      }
    });
  });

  describe('integration sanity (applied as a Δμ multiplier)', () => {
    it('reduces a positive Δμ exactly by the clamped factor', () => {
      const deltaMu = 80;
      const factor = 0.4; // factor sourced from integrity (0..1)
      const final = deltaMu * boostingPenalty(deltaMu, factor);
      expect(final).toBeCloseTo(80 * 0.6, 12);
    });

    it('keeps DEFAULT_PARAMS-derived flows finite (factor pass-through unaffected by params)', () => {
      // boostingPenalty does not read params, but assert the constant exists so
      // downstream wiring (rate.ts) stays anchored to the same module graph.
      expect(DEFAULT_PARAMS.maxDeltaMu).toBeGreaterThan(0);
      expect(boostingPenalty(DEFAULT_PARAMS.maxDeltaMu, 0.5)).toBe(0.5);
    });
  });

  describe('openskill oracle anchor (test-only dependency, D6)', () => {
    it('a clean (factor=0) positive Δμ matches the un-penalised openskill base gain', () => {
      // Build a trivial 1v1 where team A wins. openskill gives the raw μ gain.
      const a = rating({ mu: DEFAULT_PARAMS.mu0, sigma: DEFAULT_PARAMS.sigma0 });
      const b = rating({ mu: DEFAULT_PARAMS.mu0, sigma: DEFAULT_PARAMS.sigma0 });
      const [[na], [nb]] = rate([[a], [b]], { rank: [1, 2] });
      const baseDeltaMu = na.mu - a.mu;
      expect(baseDeltaMu).toBeGreaterThan(0);

      // factor 0 → no penalty → identical gain.
      const clean = baseDeltaMu * boostingPenalty(baseDeltaMu, 0);
      expect(clean).toBeCloseTo(baseDeltaMu, 12);

      // factor 1 → fully neutralised gain for the booster.
      const fullyPenalised = baseDeltaMu * boostingPenalty(baseDeltaMu, 1);
      expect(fullyPenalised).toBe(0);

      // the loser's negative Δμ is untouched by any factor.
      const loserDeltaMu = nb.mu - b.mu;
      expect(loserDeltaMu).toBeLessThan(0);
      const loserPenalised = loserDeltaMu * boostingPenalty(loserDeltaMu, 1);
      expect(loserPenalised).toBe(loserDeltaMu);
    });
  });
});
