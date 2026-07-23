import type { RatingParams } from '../types.js';

/**
 * placementWeight — spec §5.1.
 *
 * Mild, symmetric emphasis on extreme placements with ~zero net drift (D5).
 * Looks up the per-mode curve by `teamCount`, then the 0-based slot for the
 * 1-based `placement`. Any miss (unknown `teamCount`, out-of-range placement,
 * or a placement < 1) falls back to a neutral `1.0` — pure & deterministic.
 *
 *   params.placementWeights[teamCount]?.[placement - 1] ?? 1.0
 *
 * @param placement 1-based finishing position (1 = best).
 * @param teamCount number of teams in the match (e.g. 8 = Duos, 6 = Trios).
 * @param params    rating params carrying the per-mode weight curves.
 * @returns the multiplicative weight applied to `Δμ_base`.
 */
export function placementWeight(
  placement: number,
  teamCount: number,
  params: RatingParams,
): number {
  return params.placementWeights[teamCount]?.[placement - 1] ?? 1.0;
}
