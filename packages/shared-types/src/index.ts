/**
 * @crs/shared-types — enums, Zod schemas and DTOs shared across CRS services.
 *
 * Slice 2 shared-contract layer. Runtime dependency: `zod`. Per decision D2.4
 * this package does NOT import `@crs/rating-engine`; `SeasonConfigSchema` is a
 * parallel Zod mirror of the engine's `RatingParams`.
 */
export * from './enums.js';
export * from './schemas.js';
export * from './dtos.js';
