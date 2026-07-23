/**
 * Shared contracts for the CRS rating engine.
 *
 * Field names are load-bearing: downstream slices (ingestion, processor, API,
 * frontend, integrity, etc.) consume these exact shapes. They mirror spec §6
 * verbatim. Do not rename fields without coordinating the dependent agents.
 */

export interface PlayerState {
  playerId: string;
  mu: number;
  sigma: number;
  cr: number; // cr = materialized toCR(mu, sigma)
  currentStreak: number; // + wins / − losses
  matchesPlayed: number;
  placementMatchesRemaining: number;
  peakCr: number;
}

export interface ParticipantInput {
  playerId: string;
  state: PlayerState;
  championId: number; // pass-through for snapshot
  eligibleForProgression: boolean;
  isPremade: boolean;
  partyId?: string;
  boostingPenaltyFactor: number; // 0..1, from `integrity` (upstream)
}

export interface TeamInput {
  teamId: number;
  placement: number; // 1..T (1 = best); ties allowed
  participants: ParticipantInput[];
}

export type RatingMode = 'DUOS' | 'TRIOS';

export interface MatchInput {
  matchId: string;
  mode: RatingMode;
  teams: TeamInput[]; // generic over N teams × M players
  params: RatingParams;
}

export interface AppliedModifiers {
  plBaseDeltaMu: number;
  placementWeight: number;
  placementAmp: number;
  streakMult: number;
  softCapFactor: number;
  boostingFactor: number;
  dispersionClamped: boolean;
  finalDeltaMu: number;
}

export interface PlayerRatingResult {
  playerId: string;
  muBefore: number;
  muAfter: number;
  sigmaBefore: number;
  sigmaAfter: number;
  crBefore: number;
  crAfter: number;
  crDelta: number;
  eligible: boolean;
  isWin: boolean;
  newStreak: number;
  modifiers: AppliedModifiers; // full transparency breakdown (§3.5 of proposal)
}

export interface RatingResult {
  matchId: string;
  voided: boolean; // true when all ineligible (D3/I4)
  players: PlayerRatingResult[];
}

export interface RatingParams {
  mu0: number;
  sigma0: number;
  beta: number;
  tau: number;
  kappa: number;
  scaleFactor: number;
  baseOffset: number;
  placementWeights: Record<number, number[]>;
  placementAmp: number;
  placementMatchCount: number;
  streakLossFloor: number;
  streakWinCeil: number;
  streakThreshold: number;
  softCapThreshold: number;
  softCapScale: number;
  maxDeltaMu: number;
  dispersionSigmaRef: number;
  resetAnchor: number;
  resetFactor: number;
  sigmaResetMult: number;
  sigmaResetCap: number;
}
