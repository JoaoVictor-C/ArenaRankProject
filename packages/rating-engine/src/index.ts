/**
 * @crs/rating-engine — public barrel.
 *
 * Re-exports the public API (spec §6): rate, toCR, softReset, DEFAULT_PARAMS,
 * validateParams, every individual modifier fn (for isolated testing/tooling),
 * and all shared types.
 */

// Core entry points
export { rate } from './rate.js';
export { toCR } from './cr.js';
export { softReset } from './season.js';

// Params
export { DEFAULT_PARAMS, validateParams } from './params.js';

// Base model
export { ratePlackettLuce } from './model/plackett-luce.js';
export type { PlBaseResult } from './model/plackett-luce.js';

// Modifiers
export { placementWeight } from './modifiers/placement-weight.js';
export { placementAmp } from './modifiers/placement-amp.js';
export { streakMultiplier, nextStreak } from './modifiers/streak.js';
export { softCapFactor } from './modifiers/soft-cap.js';
export { dispersionCap } from './modifiers/dispersion-cap.js';
export type { DispersionCapResult } from './modifiers/dispersion-cap.js';
export { boostingPenalty } from './modifiers/boosting-penalty.js';

// Types
export type {
  PlayerState,
  ParticipantInput,
  TeamInput,
  RatingMode,
  MatchInput,
  AppliedModifiers,
  PlayerRatingResult,
  RatingResult,
  RatingParams,
} from './types.js';
