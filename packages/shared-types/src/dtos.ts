import { z } from 'zod';
import {
  ACHIEVEMENT_TIERS,
  INTEGRITY_FLAG_TYPES,
  RATING_MODES,
} from './enums.js';

/**
 * Core API response DTOs (proposal §9 + §3.3). Zod schemas + inferred types so
 * the same definition validates at the API boundary and types the client.
 * Core set only (YAGNI on the rest, per spec §5).
 */

const uuid = z.string().uuid();
const isoDateTime = z.string().datetime();

// ---------------------------------------------------------------------------
// PlayerProfileDTO — GET /players/{puuid} (active-season summary, §9.1 / §3.3)
// ---------------------------------------------------------------------------
export const PlayerProfileDTOSchema = z
  .object({
    playerId: uuid,
    puuid: z.string(),
    summonerName: z.string().nullable(),
    tagLine: z.string().nullable(),
    region: z.string().nullable(),
    seasonId: uuid,
    cr: z.number(),
    mu: z.number(),
    sigma: z.number(),
    rank: z.number().int().positive().nullable(),
    matchesPlayed: z.number().int().min(0),
    placementMatchesRemaining: z.number().int().min(0),
    isProvisional: z.boolean(),
    peakCr: z.number(),
    currentStreak: z.number().int(),
    achievementTiers: z.array(z.enum(ACHIEVEMENT_TIERS)),
  })
  .strict();

export type PlayerProfileDTO = z.infer<typeof PlayerProfileDTOSchema>;

// ---------------------------------------------------------------------------
// LeaderboardEntryDTO — GET /leaderboard (§9.1 / §11.1 materialized view)
// ---------------------------------------------------------------------------
export const LeaderboardEntryDTOSchema = z
  .object({
    rank: z.number().int().positive(),
    playerId: uuid,
    summonerName: z.string().nullable(),
    tagLine: z.string().nullable(),
    cr: z.number(),
    mu: z.number(),
    sigma: z.number(),
    matchesPlayed: z.number().int().min(0),
    isProvisional: z.boolean(),
  })
  .strict();

export type LeaderboardEntryDTO = z.infer<typeof LeaderboardEntryDTOSchema>;

// ---------------------------------------------------------------------------
// MatchRecordDTO — GET /matches/{matchId} (full record + participants, §9.1)
// ---------------------------------------------------------------------------
export const MatchParticipantDTOSchema = z
  .object({
    playerId: uuid,
    summonerName: z.string().nullable(),
    championId: z.number().int(),
    teamId: z.number().int(),
    placement: z.number().int().positive(),
    eligible: z.boolean(),
    crBefore: z.number(),
    crAfter: z.number(),
    crDelta: z.number(),
    isPremade: z.boolean(),
  })
  .strict();

export type MatchParticipantDTO = z.infer<typeof MatchParticipantDTOSchema>;

export const MatchRecordDTOSchema = z
  .object({
    matchId: uuid,
    riotMatchId: z.string(),
    mode: z.enum(RATING_MODES),
    seasonId: uuid,
    playedAt: isoDateTime,
    durationSeconds: z.number().int().positive().nullable(),
    processed: z.boolean(),
    integrityFlags: z.array(z.enum(INTEGRITY_FLAG_TYPES)),
    participants: z.array(MatchParticipantDTOSchema),
  })
  .strict();

export type MatchRecordDTO = z.infer<typeof MatchRecordDTOSchema>;

// ---------------------------------------------------------------------------
// ChampionStatDTO — GET /players/{puuid}/champions (§9.1 / §3.3)
// ---------------------------------------------------------------------------
export const ChampionStatDTOSchema = z
  .object({
    championId: z.number().int(),
    matchesPlayed: z.number().int().min(0),
    wins: z.number().int().min(0),
    topHalf: z.number().int().min(0),
    winRate: z.number().min(0).max(1),
    topHalfRate: z.number().min(0).max(1),
    avgPlacement: z.number(),
    crDeltaSum: z.number(),
  })
  .strict();

export type ChampionStatDTO = z.infer<typeof ChampionStatDTOSchema>;

// ---------------------------------------------------------------------------
// HeadToHeadDTO — GET /players/{puuid}/head-to-head/{puuid2} (§9.1 / §3.3)
// ---------------------------------------------------------------------------
export const HeadToHeadDTOSchema = z
  .object({
    playerId: uuid,
    opponentId: uuid,
    // matches where the two were on the same team
    gamesTogether: z.number().int().min(0),
    winsTogether: z.number().int().min(0),
    winRateTogether: z.number().min(0).max(1),
    // matches where the two were on opposing teams
    gamesAgainst: z.number().int().min(0),
    winsAgainst: z.number().int().min(0),
    winRateAgainst: z.number().min(0).max(1),
  })
  .strict();

export type HeadToHeadDTO = z.infer<typeof HeadToHeadDTOSchema>;
