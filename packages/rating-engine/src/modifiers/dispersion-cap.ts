import type { RatingParams } from '../types.js';

/**
 * Result of the dispersion cap (spec §5.6, Trinity C1: SIGMA-SCALED).
 */
export interface DispersionCapResult {
  value: number;
  clamped: boolean;
  effectiveCap: number;
}

/**
 * dispersionCap — spec §5.6 (Trinity correction C1: SIGMA-SCALED). Applied last
 * in the modifier pipeline; the structural guarantor of invariant I7
 * (`|Δμ_final| ≤ effectiveCap`).
 *
 * The cap is no longer a flat `maxDeltaMu`. High-uncertainty players (large
 * `sigmaBefore`) are allowed to move faster so legitimate climbers are not
 * frozen while σ resolves; the cap scales linearly with σ above the reference
 * `dispersionSigmaRef` and floors at `maxDeltaMu` for settled players:
 *
 *   effectiveCap = maxDeltaMu · max(1, sigmaBefore / dispersionSigmaRef)
 *   { value:        clamp(deltaMu, −effectiveCap, +effectiveCap),
 *     clamped:      |deltaMu| > effectiveCap,
 *     effectiveCap: effectiveCap }
 *
 * The exact boundary (`|deltaMu| === effectiveCap`) passes through unchanged and
 * is reported as NOT clamped, per the strict `>` in the spec. Pure and
 * deterministic — no clock, no RNG, no I/O.
 */
export function dispersionCap(
  deltaMu: number,
  params: RatingParams,
  sigmaBefore: number,
): DispersionCapResult {
  const effectiveCap =
    params.maxDeltaMu * Math.max(1, sigmaBefore / params.dispersionSigmaRef);
  const clamped = Math.abs(deltaMu) > effectiveCap;
  const value =
    deltaMu > effectiveCap
      ? effectiveCap
      : deltaMu < -effectiveCap
        ? -effectiveCap
        : deltaMu;
  return { value, clamped, effectiveCap };
}
