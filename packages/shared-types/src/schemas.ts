import { z } from 'zod';

/**
 * Zod schemas for runtime-validated CRS contracts.
 *
 * `SeasonConfigSchema` mirrors the rating-engine `RatingParams` interface
 * (slice 1) so a `seasons.config` JSONB blob can be validated before it is fed
 * back into the engine as per-season overrides. Per decision D2.4 this is a
 * parallel mirror — shared-types does NOT import the engine (which stays
 * zero-dep); the two are kept in lockstep by review.
 */

/** A non-empty array of placement weight multipliers for a given team count. */
const placementWeightCurve = z.array(z.number().finite()).min(1);

/**
 * `placementWeights`: keyed by team count (e.g. 6, 8) -> per-placement weights.
 * JSON object keys are always strings, so we coerce/validate the key as a
 * positive integer string and the value as a weight curve.
 */
const placementWeightsSchema = z.record(
  z.string().regex(/^\d+$/, 'team-count key must be a positive integer'),
  placementWeightCurve,
);

export const SeasonConfigSchema = z
  .object({
    // placement / provisional
    placementMatchCount: z.number().int().positive(),
    // soft reset (season rollover, §13.3)
    resetFactor: z.number().min(0).max(1),
    sigmaResetMult: z.number().positive(),
    sigmaResetCap: z.number().positive(),
    // CR mapping (§5)
    scaleFactor: z.number().positive(),
    baseOffset: z.number(),
    // soft cap (§3.1 / §5)
    softCapThreshold: z.number().positive(),
    softCapScale: z.number().positive(),
    // dispersion cap (Trinity C1, §5.6)
    maxDeltaMu: z.number().positive(),
    dispersionSigmaRef: z.number().positive(),
    // openskill / TrueSkill params
    beta: z.number().positive(),
    tau: z.number().min(0),
    kappa: z.number().gt(0).lt(1),
    // streak dampener (§3.2)
    streakLossFloor: z.number().min(0).max(1),
    streakWinCeil: z.number().gte(1),
    streakThreshold: z.number().int().positive(),
    // placement weight curves (keyed by team count)
    placementWeights: placementWeightsSchema,
  })
  .strict();

export type SeasonConfig = z.infer<typeof SeasonConfigSchema>;

/** Standard list pagination: 1-indexed page, bounded limit. */
export const PaginationSchema = z
  .object({
    page: z.coerce.number().int().min(1).default(1),
    limit: z.coerce.number().int().min(1).max(100).default(20),
  })
  .strict();

export type Pagination = z.infer<typeof PaginationSchema>;

/** Riot ID: `gameName#tagLine`. */
export const RiotIdSchema = z
  .object({
    gameName: z.string().min(3).max(16),
    tagLine: z.string().min(3).max(5),
  })
  .strict();

export type RiotId = z.infer<typeof RiotIdSchema>;
