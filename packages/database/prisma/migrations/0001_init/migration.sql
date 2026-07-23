-- CreateEnum
CREATE TYPE "SeasonStatus" AS ENUM ('ACTIVE', 'SOFT_LOCK', 'ENDED', 'OFF_SEASON');

-- CreateEnum
CREATE TYPE "RatingMode" AS ENUM ('DUOS', 'TRIOS');

-- CreateEnum
CREATE TYPE "Severity" AS ENUM ('INFO', 'WARN', 'CRITICAL');

-- CreateEnum
CREATE TYPE "RegistrationSource" AS ENUM ('auto', 'manual');

-- CreateTable
CREATE TABLE "players" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "puuid" VARCHAR(78) NOT NULL,
    "summonerName" VARCHAR(64),
    "tagLine" VARCHAR(8),
    "region" VARCHAR(8),
    "registeredAt" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "registrationSource" "RegistrationSource" NOT NULL DEFAULT 'auto',
    "moderationFlags" JSONB NOT NULL DEFAULT '[]',
    "anonymizedAt" TIMESTAMPTZ(6),

    CONSTRAINT "players_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "seasons" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "name" VARCHAR(64) NOT NULL,
    "queueId" INTEGER NOT NULL,
    "startsAt" TIMESTAMPTZ(6) NOT NULL,
    "endsAt" TIMESTAMPTZ(6) NOT NULL,
    "status" "SeasonStatus" NOT NULL,
    "config" JSONB NOT NULL,

    CONSTRAINT "seasons_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "player_seasons" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "playerId" UUID NOT NULL,
    "seasonId" UUID NOT NULL,
    "cr" DOUBLE PRECISION NOT NULL DEFAULT 1000,
    "mu" DOUBLE PRECISION NOT NULL DEFAULT 1000,
    "sigma" DOUBLE PRECISION NOT NULL DEFAULT 350,
    "matchesPlayed" INTEGER NOT NULL DEFAULT 0,
    "placementMatchesRemaining" INTEGER NOT NULL DEFAULT 10,
    "isProvisional" BOOLEAN NOT NULL DEFAULT true,
    "peakCr" DOUBLE PRECISION NOT NULL DEFAULT 1000,
    "currentStreak" INTEGER NOT NULL DEFAULT 0,
    "updatedAt" TIMESTAMPTZ(6) NOT NULL,

    CONSTRAINT "player_seasons_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "matches" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "riotMatchId" VARCHAR(32) NOT NULL,
    "queueId" INTEGER NOT NULL,
    "mode" "RatingMode" NOT NULL,
    "seasonId" UUID NOT NULL,
    "playedAt" TIMESTAMPTZ(6) NOT NULL,
    "processedAt" TIMESTAMPTZ(6),
    "processed" BOOLEAN NOT NULL DEFAULT false,
    "integrityFlags" JSONB NOT NULL DEFAULT '[]',
    "durationSeconds" INTEGER,

    CONSTRAINT "matches_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "match_participants" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "matchId" UUID NOT NULL,
    "playerId" UUID NOT NULL,
    "championId" INTEGER NOT NULL,
    "teamId" INTEGER NOT NULL,
    "placement" INTEGER NOT NULL,
    "eligible" BOOLEAN NOT NULL,
    "crBefore" DOUBLE PRECISION NOT NULL,
    "crAfter" DOUBLE PRECISION NOT NULL,
    "crDelta" DOUBLE PRECISION NOT NULL,
    "isPremade" BOOLEAN NOT NULL DEFAULT false,
    "partyId" VARCHAR(36),
    "modifiers" JSONB NOT NULL,

    CONSTRAINT "match_participants_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "champion_stats" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "playerId" UUID NOT NULL,
    "seasonId" UUID NOT NULL,
    "championId" INTEGER NOT NULL,
    "matchesPlayed" INTEGER NOT NULL DEFAULT 0,
    "wins" INTEGER NOT NULL DEFAULT 0,
    "topHalf" INTEGER NOT NULL DEFAULT 0,
    "totalPlacementSum" INTEGER NOT NULL DEFAULT 0,
    "crDeltaSum" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "last10Placements" INTEGER[] DEFAULT ARRAY[]::INTEGER[],

    CONSTRAINT "champion_stats_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "integrity_events" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "matchId" UUID NOT NULL,
    "playerId" UUID,
    "flagType" VARCHAR(32) NOT NULL,
    "severity" "Severity" NOT NULL,
    "metadata" JSONB,
    "createdAt" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "reviewed" BOOLEAN NOT NULL DEFAULT false,
    "reviewerId" UUID,

    CONSTRAINT "integrity_events_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "player_achievements" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "playerId" UUID NOT NULL,
    "seasonId" UUID NOT NULL,
    "achievementType" VARCHAR(32) NOT NULL,
    "tier" VARCHAR(16) NOT NULL,
    "rankValue" INTEGER NOT NULL,
    "awardedAt" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "player_achievements_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "cr_snapshots" (
    "playerId" UUID NOT NULL,
    "seasonId" UUID NOT NULL,
    "snapshotAt" TIMESTAMPTZ(6) NOT NULL,
    "cr" DOUBLE PRECISION NOT NULL,
    "mu" DOUBLE PRECISION NOT NULL,
    "sigma" DOUBLE PRECISION NOT NULL,
    "matchesPlayed" INTEGER NOT NULL,

    CONSTRAINT "cr_snapshots_pkey" PRIMARY KEY ("playerId","seasonId","snapshotAt")
);

-- CreateIndex
CREATE UNIQUE INDEX "players_puuid_key" ON "players"("puuid");

-- CreateIndex
CREATE INDEX "seasons_status_idx" ON "seasons"("status");

-- CreateIndex
CREATE INDEX "player_seasons_seasonId_cr_idx" ON "player_seasons"("seasonId", "cr" DESC);

-- CreateIndex
CREATE UNIQUE INDEX "player_seasons_playerId_seasonId_key" ON "player_seasons"("playerId", "seasonId");

-- CreateIndex
CREATE UNIQUE INDEX "matches_riotMatchId_key" ON "matches"("riotMatchId");

-- CreateIndex
CREATE INDEX "matches_playedAt_idx" ON "matches"("playedAt" DESC);

-- CreateIndex
CREATE INDEX "idx_matches_unprocessed" ON "matches"("processed");

-- CreateIndex
CREATE INDEX "match_participants_playerId_matchId_idx" ON "match_participants"("playerId", "matchId");

-- CreateIndex
CREATE UNIQUE INDEX "match_participants_matchId_playerId_key" ON "match_participants"("matchId", "playerId");

-- CreateIndex
CREATE INDEX "champion_stats_playerId_seasonId_idx" ON "champion_stats"("playerId", "seasonId");

-- CreateIndex
CREATE UNIQUE INDEX "champion_stats_playerId_seasonId_championId_key" ON "champion_stats"("playerId", "seasonId", "championId");

-- CreateIndex
CREATE INDEX "integrity_events_playerId_createdAt_idx" ON "integrity_events"("playerId", "createdAt" DESC);

-- CreateIndex
CREATE INDEX "integrity_events_reviewed_idx" ON "integrity_events"("reviewed");

-- CreateIndex
CREATE INDEX "player_achievements_playerId_idx" ON "player_achievements"("playerId");

-- CreateIndex
CREATE UNIQUE INDEX "player_achievements_playerId_seasonId_achievementType_key" ON "player_achievements"("playerId", "seasonId", "achievementType");

-- AddForeignKey
ALTER TABLE "player_seasons" ADD CONSTRAINT "player_seasons_playerId_fkey" FOREIGN KEY ("playerId") REFERENCES "players"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "player_seasons" ADD CONSTRAINT "player_seasons_seasonId_fkey" FOREIGN KEY ("seasonId") REFERENCES "seasons"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "matches" ADD CONSTRAINT "matches_seasonId_fkey" FOREIGN KEY ("seasonId") REFERENCES "seasons"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "match_participants" ADD CONSTRAINT "match_participants_matchId_fkey" FOREIGN KEY ("matchId") REFERENCES "matches"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "match_participants" ADD CONSTRAINT "match_participants_playerId_fkey" FOREIGN KEY ("playerId") REFERENCES "players"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "champion_stats" ADD CONSTRAINT "champion_stats_playerId_fkey" FOREIGN KEY ("playerId") REFERENCES "players"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "champion_stats" ADD CONSTRAINT "champion_stats_seasonId_fkey" FOREIGN KEY ("seasonId") REFERENCES "seasons"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "integrity_events" ADD CONSTRAINT "integrity_events_matchId_fkey" FOREIGN KEY ("matchId") REFERENCES "matches"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "player_achievements" ADD CONSTRAINT "player_achievements_playerId_fkey" FOREIGN KEY ("playerId") REFERENCES "players"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "player_achievements" ADD CONSTRAINT "player_achievements_seasonId_fkey" FOREIGN KEY ("seasonId") REFERENCES "seasons"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

