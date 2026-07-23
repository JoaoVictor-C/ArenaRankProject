import type { RatingParams } from '../types.js';

/**
 * softCapFactor — spec §5.4. Always in (0, 1]; positive side only.
 *   deltaMu > 0 && cr > softCapThreshold
 *     ? 1 / (1 + (cr − softCapThreshold) / softCapScale)
 *     : 1.0
 *
 * Attenuates only positive μ movement once a player's CR climbs past
 * `softCapThreshold`, with diminishing returns governed by `softCapScale`.
 * Losses (deltaMu ≤ 0) and players at/below the threshold are untouched.
 * No hard ceiling: the factor approaches 0 as cr → ∞ but never reaches it.
 *
 * Pure & deterministic — no Date.now / Math.random.
 */
export function softCapFactor(
  cr: number,
  deltaMu: number,
  params: RatingParams,
): number {
  if (deltaMu > 0 && cr > params.softCapThreshold) {
    return 1 / (1 + (cr - params.softCapThreshold) / params.softCapScale);
  }
  return 1.0;
}
