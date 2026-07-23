import { describe, it, expect } from 'vitest';
import {
  // enums
  SEASON_STATUSES,
  RATING_MODES,
  SEVERITIES,
  REGISTRATION_SOURCES,
  INTEGRITY_FLAG_TYPES,
  ACHIEVEMENT_TIERS,
  type SeasonStatus,
  type RatingMode,
  type Severity,
  type RegistrationSource,
  type IntegrityFlagType,
  type AchievementTier,
  // schemas
  SeasonConfigSchema,
  PaginationSchema,
  RiotIdSchema,
  // dtos
  PlayerProfileDTOSchema,
  LeaderboardEntryDTOSchema,
  MatchRecordDTOSchema,
  ChampionStatDTOSchema,
  HeadToHeadDTOSchema,
} from '../src/index.js';

// ---------------------------------------------------------------------------
// Enum union <-> const-array sync
// ---------------------------------------------------------------------------
describe('enum union <-> const-array sync', () => {
  // The compile-time AssertTrue<Equals<...>> guards in enums.ts already fail
  // `tsc` on drift. These runtime checks assert each const value is assignable
  // to its union (a value-level mirror of that guarantee) and that arrays have
  // no accidental duplicates.
  const cases: Array<[string, readonly string[]]> = [
    ['SeasonStatus', SEASON_STATUSES],
    ['RatingMode', RATING_MODES],
    ['Severity', SEVERITIES],
    ['RegistrationSource', REGISTRATION_SOURCES],
    ['IntegrityFlagType', INTEGRITY_FLAG_TYPES],
    ['AchievementTier', ACHIEVEMENT_TIERS],
  ];

  it.each(cases)('%s has unique, non-empty members', (_name, arr) => {
    expect(arr.length).toBeGreaterThan(0);
    expect(new Set(arr).size).toBe(arr.length);
  });

  it('union members are exactly the const-array members', () => {
    const seasonStatus: SeasonStatus = 'ACTIVE';
    const ratingMode: RatingMode = 'DUOS';
    const severity: Severity = 'CRITICAL';
    const registrationSource: RegistrationSource = 'auto';
    const integrityFlag: IntegrityFlagType = 'RDS_BOOSTING';
    const achievementTier: AchievementTier = 'TOP_1';

    expect(SEASON_STATUSES).toContain(seasonStatus);
    expect(RATING_MODES).toContain(ratingMode);
    expect(SEVERITIES).toContain(severity);
    expect(REGISTRATION_SOURCES).toContain(registrationSource);
    expect(INTEGRITY_FLAG_TYPES).toContain(integrityFlag);
    expect(ACHIEVEMENT_TIERS).toContain(achievementTier);

    expect(SEASON_STATUSES).toEqual([
      'ACTIVE',
      'SOFT_LOCK',
      'ENDED',
      'OFF_SEASON',
    ]);
    expect(INTEGRITY_FLAG_TYPES).toEqual([
      'RDS_BOOSTING',
      'AFK_INELIGIBLE',
      'REPEATED_LOBBY',
      'UNUSUAL_DURATION',
      'DISPERSION_CAP',
    ]);
    expect(ACHIEVEMENT_TIERS).toEqual([
      'TOP_1',
      'TOP_10',
      'TOP_50',
      'TOP_100',
      'TOP_500',
    ]);
  });
});

// ---------------------------------------------------------------------------
// SeasonConfigSchema (mirrors RatingParams)
// ---------------------------------------------------------------------------
const validSeasonConfig = {
  placementMatchCount: 10,
  resetFactor: 0.5,
  sigmaResetMult: 1.5,
  sigmaResetCap: 350,
  scaleFactor: 1.0,
  baseOffset: 250,
  softCapThreshold: 5000,
  softCapScale: 1000,
  maxDeltaMu: 150,
  dispersionSigmaRef: 85,
  beta: 175,
  tau: 3.5,
  kappa: 1e-4,
  streakLossFloor: 0.25,
  streakWinCeil: 1.35,
  streakThreshold: 3,
  placementWeights: {
    '6': [1.1, 1.05, 1.0, 1.0, 0.95, 0.9],
    '8': [1.2, 1.1, 1.05, 1.0, 1.0, 0.95, 0.9, 0.8],
  },
};

describe('SeasonConfigSchema', () => {
  it('parses a valid config', () => {
    expect(SeasonConfigSchema.parse(validSeasonConfig)).toEqual(
      validSeasonConfig,
    );
  });

  it('rejects kappa outside (0,1)', () => {
    const bad = { ...validSeasonConfig, kappa: 1.5 };
    expect(SeasonConfigSchema.safeParse(bad).success).toBe(false);
  });

  it('rejects non-positive dispersionSigmaRef (division guard)', () => {
    const bad = { ...validSeasonConfig, dispersionSigmaRef: 0 };
    expect(SeasonConfigSchema.safeParse(bad).success).toBe(false);
  });

  it('rejects streakLossFloor > 1', () => {
    const bad = { ...validSeasonConfig, streakLossFloor: 1.2 };
    expect(SeasonConfigSchema.safeParse(bad).success).toBe(false);
  });

  it('rejects a non-integer team-count key in placementWeights', () => {
    const bad = {
      ...validSeasonConfig,
      placementWeights: { duos: [1.0, 1.0] },
    };
    expect(SeasonConfigSchema.safeParse(bad).success).toBe(false);
  });

  it('rejects unknown extra keys (strict)', () => {
    const bad = { ...validSeasonConfig, mysteryParam: 42 };
    expect(SeasonConfigSchema.safeParse(bad).success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// PaginationSchema
// ---------------------------------------------------------------------------
describe('PaginationSchema', () => {
  it('parses a valid page/limit', () => {
    expect(PaginationSchema.parse({ page: 2, limit: 50 })).toEqual({
      page: 2,
      limit: 50,
    });
  });

  it('applies defaults when omitted', () => {
    expect(PaginationSchema.parse({})).toEqual({ page: 1, limit: 20 });
  });

  it('coerces numeric strings (query params)', () => {
    expect(PaginationSchema.parse({ page: '3', limit: '10' })).toEqual({
      page: 3,
      limit: 10,
    });
  });

  it('rejects page < 1', () => {
    expect(PaginationSchema.safeParse({ page: 0 }).success).toBe(false);
  });

  it('rejects limit > 100', () => {
    expect(PaginationSchema.safeParse({ limit: 101 }).success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// RiotIdSchema
// ---------------------------------------------------------------------------
describe('RiotIdSchema', () => {
  it('parses a valid Riot ID', () => {
    expect(RiotIdSchema.parse({ gameName: 'Faker', tagLine: 'KR1' })).toEqual({
      gameName: 'Faker',
      tagLine: 'KR1',
    });
  });

  it('rejects too-short gameName', () => {
    expect(
      RiotIdSchema.safeParse({ gameName: 'ab', tagLine: 'KR1' }).success,
    ).toBe(false);
  });

  it('rejects too-long tagLine', () => {
    expect(
      RiotIdSchema.safeParse({ gameName: 'Faker', tagLine: 'TOOLONG' }).success,
    ).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// DTOs
// ---------------------------------------------------------------------------
describe('PlayerProfileDTOSchema', () => {
  const valid = {
    playerId: '11111111-1111-4111-8111-111111111111',
    puuid: 'puuid-abc',
    summonerName: 'Hide on bush',
    tagLine: 'KR1',
    region: 'KR',
    seasonId: '22222222-2222-4222-8222-222222222222',
    cr: 1840.2,
    mu: 1800,
    sigma: 70,
    rank: 1,
    matchesPlayed: 120,
    placementMatchesRemaining: 0,
    isProvisional: false,
    peakCr: 1900,
    currentStreak: 4,
    achievementTiers: ['TOP_1', 'TOP_10'],
  };

  it('parses a valid profile', () => {
    expect(PlayerProfileDTOSchema.parse(valid)).toEqual(valid);
  });

  it('rejects an invalid playerId (not a uuid)', () => {
    expect(
      PlayerProfileDTOSchema.safeParse({ ...valid, playerId: 'nope' }).success,
    ).toBe(false);
  });

  it('rejects an unknown achievement tier', () => {
    expect(
      PlayerProfileDTOSchema.safeParse({
        ...valid,
        achievementTiers: ['TOP_9000'],
      }).success,
    ).toBe(false);
  });
});

describe('LeaderboardEntryDTOSchema', () => {
  const valid = {
    rank: 1,
    playerId: '33333333-3333-4333-8333-333333333333',
    summonerName: 'TopDog',
    tagLine: 'NA1',
    cr: 1840,
    mu: 1800,
    sigma: 70,
    matchesPlayed: 100,
    isProvisional: false,
  };

  it('parses a valid entry', () => {
    expect(LeaderboardEntryDTOSchema.parse(valid)).toEqual(valid);
  });

  it('rejects rank < 1', () => {
    expect(
      LeaderboardEntryDTOSchema.safeParse({ ...valid, rank: 0 }).success,
    ).toBe(false);
  });
});

describe('MatchRecordDTOSchema', () => {
  const valid = {
    matchId: '44444444-4444-4444-8444-444444444444',
    riotMatchId: 'KR_123456789',
    mode: 'DUOS',
    seasonId: '22222222-2222-4222-8222-222222222222',
    playedAt: '2026-06-14T12:00:00.000Z',
    durationSeconds: 1800,
    processed: true,
    integrityFlags: ['UNUSUAL_DURATION'],
    participants: [
      {
        playerId: '11111111-1111-4111-8111-111111111111',
        summonerName: 'Faker',
        championId: 157,
        teamId: 1,
        placement: 1,
        eligible: true,
        crBefore: 1800,
        crAfter: 1820,
        crDelta: 20,
        isPremade: true,
      },
    ],
  };

  it('parses a valid match record', () => {
    expect(MatchRecordDTOSchema.parse(valid)).toEqual(valid);
  });

  it('rejects an unknown mode', () => {
    expect(
      MatchRecordDTOSchema.safeParse({ ...valid, mode: 'QUADS' }).success,
    ).toBe(false);
  });

  it('rejects a non-datetime playedAt', () => {
    expect(
      MatchRecordDTOSchema.safeParse({ ...valid, playedAt: 'yesterday' })
        .success,
    ).toBe(false);
  });
});

describe('ChampionStatDTOSchema', () => {
  const valid = {
    championId: 157,
    matchesPlayed: 40,
    wins: 12,
    topHalf: 25,
    winRate: 0.3,
    topHalfRate: 0.625,
    avgPlacement: 3.4,
    crDeltaSum: 120.5,
  };

  it('parses a valid champion stat', () => {
    expect(ChampionStatDTOSchema.parse(valid)).toEqual(valid);
  });

  it('rejects winRate > 1', () => {
    expect(
      ChampionStatDTOSchema.safeParse({ ...valid, winRate: 1.5 }).success,
    ).toBe(false);
  });
});

describe('HeadToHeadDTOSchema', () => {
  const valid = {
    playerId: '11111111-1111-4111-8111-111111111111',
    opponentId: '55555555-5555-4555-8555-555555555555',
    gamesTogether: 10,
    winsTogether: 6,
    winRateTogether: 0.6,
    gamesAgainst: 4,
    winsAgainst: 2,
    winRateAgainst: 0.5,
  };

  it('parses a valid head-to-head', () => {
    expect(HeadToHeadDTOSchema.parse(valid)).toEqual(valid);
  });

  it('rejects a negative gamesTogether', () => {
    expect(
      HeadToHeadDTOSchema.safeParse({ ...valid, gamesTogether: -1 }).success,
    ).toBe(false);
  });
});
