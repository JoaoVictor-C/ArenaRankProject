import type { PlayerState, RatingParams } from '../types.js';

/**
 * placementAmp — spec §5.2.
 *
 * Provisional-match amplification multiplier applied to `Δμ_base` so that
 * a player's rating resolves faster during their placement matches.
 *
 *   placementAmp(state, params) =
 *     state.placementMatchesRemaining > 0 ? params.placementAmp : 1.0
 *
 * Boundary is exactly 0: `remaining > 0` ⇒ amplify (DEFAULT 2.0×);
 * `remaining === 0` (or below) ⇒ neutral 1.0× (player is established).
 *
 * Pure & deterministic: no I/O, no Date.now / Math.random.
 */
export function placementAmp(state: PlayerState, params: RatingParams): number {
  return state.placementMatchesRemaining > 0 ? params.placementAmp : 1.0;
}
