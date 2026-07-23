/**
 * boostingPenalty — spec §5.5. Positive side only; booster gains less.
 *
 *   deltaMu > 0 ? (1 − clamp(factor, 0, 1)) : 1.0
 *
 * Returns the multiplier applied to Δμ in the modifier pipeline (§5). The
 * `factor` is `boostingPenaltyFactor ∈ [0, 1]` supplied by the upstream
 * integrity slice; we clamp defensively so a malformed value can never amplify
 * a gain or flip the sign of Δμ. Losses (and zero movement) are never touched,
 * preserving D2 (modifiers never turn a loss into a gain). Pure & deterministic.
 *
 * @param deltaMu the base Δμ at this pipeline stage (sign matters; >0 = gain).
 * @param factor  boosting penalty factor in [0, 1] (clamped); 0 = no penalty,
 *                1 = full neutralisation of the gain.
 * @returns the multiplier, always in [0, 1].
 */
export function boostingPenalty(deltaMu: number, factor: number): number {
  if (deltaMu > 0) {
    const clamped = factor < 0 ? 0 : factor > 1 ? 1 : factor;
    return 1 - clamped;
  }
  return 1.0;
}
