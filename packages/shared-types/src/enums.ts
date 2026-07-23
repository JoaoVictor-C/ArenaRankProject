/**
 * String-literal enums for CRS shared contracts.
 *
 * Each enum is declared once as a `readonly` const tuple (the runtime source of
 * truth) and once as a union type derived from that tuple. A compile-time
 * `assertSync` check guarantees the hand-written union and the const array stay
 * in sync in BOTH directions:
 *   - every union member is present in the array (array element type ⊇ union)
 *   - every array element is a member of the union (union ⊇ array element type)
 * If either side drifts, `tsc --noEmit` fails.
 */

/** Bidirectional type-equality assertion used by the per-enum sync guards. */
type Equals<A, B> = (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B
  ? 1
  : 2
  ? true
  : false;

/** Resolves to `never` (compile error) unless `T` is exactly `true`. */
type AssertTrue<T extends true> = T;

// ---------------------------------------------------------------------------
// SeasonStatus
// ---------------------------------------------------------------------------
export const SEASON_STATUSES = [
  'ACTIVE',
  'SOFT_LOCK',
  'ENDED',
  'OFF_SEASON',
] as const;
export type SeasonStatus = (typeof SEASON_STATUSES)[number];
type _SeasonStatusSync = AssertTrue<
  Equals<SeasonStatus, 'ACTIVE' | 'SOFT_LOCK' | 'ENDED' | 'OFF_SEASON'>
>;

// ---------------------------------------------------------------------------
// RatingMode
// ---------------------------------------------------------------------------
export const RATING_MODES = ['DUOS', 'TRIOS'] as const;
export type RatingMode = (typeof RATING_MODES)[number];
type _RatingModeSync = AssertTrue<Equals<RatingMode, 'DUOS' | 'TRIOS'>>;

// ---------------------------------------------------------------------------
// Severity
// ---------------------------------------------------------------------------
export const SEVERITIES = ['INFO', 'WARN', 'CRITICAL'] as const;
export type Severity = (typeof SEVERITIES)[number];
type _SeveritySync = AssertTrue<Equals<Severity, 'INFO' | 'WARN' | 'CRITICAL'>>;

// ---------------------------------------------------------------------------
// RegistrationSource
// ---------------------------------------------------------------------------
export const REGISTRATION_SOURCES = ['auto', 'manual'] as const;
export type RegistrationSource = (typeof REGISTRATION_SOURCES)[number];
type _RegistrationSourceSync = AssertTrue<
  Equals<RegistrationSource, 'auto' | 'manual'>
>;

// ---------------------------------------------------------------------------
// IntegrityFlagType
// ---------------------------------------------------------------------------
export const INTEGRITY_FLAG_TYPES = [
  'RDS_BOOSTING',
  'AFK_INELIGIBLE',
  'REPEATED_LOBBY',
  'UNUSUAL_DURATION',
  'DISPERSION_CAP',
] as const;
export type IntegrityFlagType = (typeof INTEGRITY_FLAG_TYPES)[number];
type _IntegrityFlagTypeSync = AssertTrue<
  Equals<
    IntegrityFlagType,
    | 'RDS_BOOSTING'
    | 'AFK_INELIGIBLE'
    | 'REPEATED_LOBBY'
    | 'UNUSUAL_DURATION'
    | 'DISPERSION_CAP'
  >
>;

// ---------------------------------------------------------------------------
// AchievementTier
// ---------------------------------------------------------------------------
export const ACHIEVEMENT_TIERS = [
  'TOP_1',
  'TOP_10',
  'TOP_50',
  'TOP_100',
  'TOP_500',
] as const;
export type AchievementTier = (typeof ACHIEVEMENT_TIERS)[number];
type _AchievementTierSync = AssertTrue<
  Equals<
    AchievementTier,
    'TOP_1' | 'TOP_10' | 'TOP_50' | 'TOP_100' | 'TOP_500'
  >
>;

// Silence "declared but never used" for the compile-time guard aliases without
// emitting any runtime code. Referencing them in a never-typed tuple keeps them
// in the type-check graph.
export type _EnumSyncGuards = [
  _SeasonStatusSync,
  _RatingModeSync,
  _SeveritySync,
  _RegistrationSourceSync,
  _IntegrityFlagTypeSync,
  _AchievementTierSync,
];
