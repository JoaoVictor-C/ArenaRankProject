import type { PlayerState, RatingParams } from './types.js';

/**
 * softReset — season soft-reset of a player's latent state (spec §5 / D4 / proposal §13.3).
 *
 * The ONLY operation that may INCREASE σ (D1/I1). Pure & deterministic: no
 * `Date.now`/`Math.random`/I/O. Returns a brand-new {@link PlayerState}; the
 * input is never mutated.
 *
 * Transformation:
 *   muNew    = resetAnchor + (mu − resetAnchor) · resetFactor   (regress μ toward the anchor)
 *   sigmaNew = min(sigma · sigmaResetMult, sigmaResetCap)       (re-inflate uncertainty, capped)
 *   crNew    = (muNew − 3·sigmaNew) · scaleFactor + baseOffset  (toCR derivation, spec §6)
 *   placementMatchesRemaining = placementMatchCount             (player re-enters provisional)
 *   matchesPlayed = 0
 *   currentStreak = 0
 *   peakCr = crNew                                              (peak rebased to the new season)
 *   playerId preserved
 *
 * CR is derived inline from the conservative formula (D1) rather than calling
 * `toCR`, so this unit stays self-contained and depends on no other module's
 * implementation.
 */
export function softReset(state: PlayerState, params: RatingParams): PlayerState {
  const muNew = params.resetAnchor + (state.mu - params.resetAnchor) * params.resetFactor;
  const sigmaNew = Math.min(state.sigma * params.sigmaResetMult, params.sigmaResetCap);
  const crNew = (muNew - 3 * sigmaNew) * params.scaleFactor + params.baseOffset;

  return {
    playerId: state.playerId,
    mu: muNew,
    sigma: sigmaNew,
    cr: crNew,
    currentStreak: 0,
    matchesPlayed: 0,
    placementMatchesRemaining: params.placementMatchCount,
    peakCr: crNew,
  };
}
