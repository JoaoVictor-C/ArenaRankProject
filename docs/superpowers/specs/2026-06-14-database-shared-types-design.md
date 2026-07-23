# CRS Database + Shared-Types — Design Spec

> Slice 2 of CRS. Source of truth: `casual_ranked_proposal.md` §8, §11, §12.4, §13.3. Builds on slice 1 (`rating-engine`).
> Packages: `@crs/database` (Prisma + migrations + client + seed), `@crs/shared-types` (enums + Zod + DTOs).
> Status: decisions D2.1–D2.8 are engineering fill-ins (proposal omits); flagged for review, not product forks.

---

## 1. Scope & non-goals

**In scope:** persistence foundation + shared contract layer.
- Prisma schema for ALL proposal §8 tables + `player_achievements` (§13.3 gap) + `cr_snapshots` (TimescaleDB hypertable).
- Migrations: Prisma Migrate + raw-SQL for extensions, hypertable, materialized leaderboard view.
- Indexes per §8.2 + additions for §11 query patterns.
- Typed Prisma client singleton + seed (champions static set, dev season).
- `shared-types`: enums, Zod schemas (season config, core API DTOs), pagination.
- `docker-compose.yml` (Postgres 16 + TimescaleDB) for local/CI.

**Non-goals (later slices):** the API/processor that USE these; live query optimization beyond indexes; PgBouncer deployment (noted only); webhooks tables (Phase 2).

## 2. Decisions (D2.x — engineering fill-ins, defaults)

| # | Decision | Default |
|---|---|---|
| D2.1 | Timescale hypertable for `cr_snapshots` | Prisma model + raw-SQL `create_hypertable(..., '7 days')`. Degrades to plain table if extension absent (hypertable = additive migration). |
| D2.2 | `player_achievements` (referenced §13.3, undefined §8) | Define it (Top 1/10/50/100/500 per season). |
| D2.3 | Materialized leaderboard view (§11.1 "never live ORDER BY") | `leaderboard_mv` + unique index + `REFRESH ... CONCURRENTLY` + refresh fn. |
| D2.4 | shared-types ↔ rating-engine coupling | Parallel, no import (engine stays zero-dep). shared-types defines Zod/DTO mirrors; engine keeps pure TS interfaces. |
| D2.5 | UUID + JSON + Float | `@default(dbgenerated("gen_random_uuid()"))`; `Json` for flags/config/modifiers; `Float` (double) for cr/mu/sigma per §8. |
| D2.6 | Migration testing without live Postgres | Static: `prisma validate` + `prisma migrate diff --from-empty --script` + `prisma generate`. Live (migrate deploy + CRUD smoke) gated on `DATABASE_URL`/docker — test **skips** with clear message if absent. |
| D2.7 | Partitioning of `matches`/`match_participants` (millions of rows) | **Defer** (YAGNI). Note as future; Trinity to weigh in on whether to partition by `season_id` now. |
| D2.8 | GDPR delete (§12.4 — anonymize, not delete) | Player gets `anonymized_at` + nullable PII; aggregate rows retained. No hard cascade-delete of match data. |

---

## 3. Prisma schema (`packages/database/prisma/schema.prisma`)

```prisma
generator client { provider = "prisma-client-js" }
datasource db { provider = "postgresql"; url = env("DATABASE_URL") }

enum SeasonStatus { ACTIVE SOFT_LOCK ENDED OFF_SEASON }
enum RatingMode   { DUOS TRIOS }
enum Severity     { INFO WARN CRITICAL }
enum RegistrationSource { auto manual }

model Player {
  id                 String   @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  puuid              String   @unique @db.VarChar(78)
  summonerName       String?  @db.VarChar(64)
  tagLine            String?  @db.VarChar(8)
  region             String?  @db.VarChar(8)
  registeredAt       DateTime @default(now()) @db.Timestamptz(6)
  registrationSource RegistrationSource @default(auto)
  moderationFlags    Json     @default("[]")
  anonymizedAt       DateTime? @db.Timestamptz(6)         // D2.8 GDPR
  playerSeasons      PlayerSeason[]
  participants       MatchParticipant[]
  championStats      ChampionStat[]
  achievements       PlayerAchievement[]
  @@map("players")
}

model Season {
  id        String   @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  name      String   @db.VarChar(64)
  queueId   Int
  startsAt  DateTime @db.Timestamptz(6)
  endsAt    DateTime @db.Timestamptz(6)
  status    SeasonStatus
  config    Json                                            // placementCount, resetFactor, cap params (mirrors RatingParams)
  playerSeasons PlayerSeason[]
  matches       Match[]
  championStats ChampionStat[]
  achievements  PlayerAchievement[]
  @@index([status])
  @@map("seasons")
}

model PlayerSeason {
  id        String @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  playerId  String @db.Uuid
  seasonId  String @db.Uuid
  cr        Float  @default(1000)
  mu        Float  @default(1000)
  sigma     Float  @default(350)
  matchesPlayed Int @default(0)
  placementMatchesRemaining Int @default(10)
  isProvisional Boolean @default(true)
  peakCr    Float  @default(1000)
  currentStreak Int @default(0)
  updatedAt DateTime @updatedAt @db.Timestamptz(6)
  player Player @relation(fields: [playerId], references: [id])
  season Season @relation(fields: [seasonId], references: [id])
  @@unique([playerId, seasonId])
  @@index([seasonId, cr(sort: Desc)])                       // leaderboard §8.2
  @@map("player_seasons")
}

model Match {
  id            String @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  riotMatchId   String @unique @db.VarChar(32)
  queueId       Int
  mode          RatingMode
  seasonId      String @db.Uuid
  playedAt      DateTime @db.Timestamptz(6)
  processedAt   DateTime? @db.Timestamptz(6)
  processed     Boolean @default(false)
  integrityFlags Json @default("[]")
  durationSeconds Int?
  season        Season @relation(fields: [seasonId], references: [id])
  participants  MatchParticipant[]
  integrityEvents IntegrityEvent[]
  @@index([playedAt(sort: Desc)])
  @@index([processed], map: "idx_matches_unprocessed")      // partial (WHERE processed=false) added in raw SQL — ingestion scan
  @@map("matches")
}

model MatchParticipant {
  id         String @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  matchId    String @db.Uuid
  playerId   String @db.Uuid
  championId Int
  teamId     Int
  placement  Int
  eligible   Boolean
  crBefore   Float
  crAfter    Float
  crDelta    Float
  isPremade  Boolean @default(false)
  partyId    String? @db.VarChar(36)
  modifiers  Json                                           // AppliedModifiers snapshot from rating-engine
  match  Match  @relation(fields: [matchId], references: [id])
  player Player @relation(fields: [playerId], references: [id])
  @@unique([matchId, playerId])
  @@index([playerId, matchId])                              // profile history §8.2
  @@map("match_participants")
}

model ChampionStat {
  id            String @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  playerId      String @db.Uuid
  seasonId      String @db.Uuid
  championId    Int
  matchesPlayed Int @default(0)
  wins          Int @default(0)
  topHalf       Int @default(0)
  totalPlacementSum Int @default(0)
  crDeltaSum    Float @default(0)
  last10Placements Int[] @default([])
  player Player @relation(fields: [playerId], references: [id])
  season Season @relation(fields: [seasonId], references: [id])
  @@unique([playerId, seasonId, championId])
  @@index([playerId, seasonId])
  @@map("champion_stats")
}

model IntegrityEvent {
  id         String @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  matchId    String @db.Uuid
  playerId   String? @db.Uuid
  flagType   String @db.VarChar(32)
  severity   Severity
  metadata   Json?
  createdAt  DateTime @default(now()) @db.Timestamptz(6)
  reviewed   Boolean @default(false)
  reviewerId String? @db.Uuid
  match Match @relation(fields: [matchId], references: [id])
  @@index([playerId, createdAt(sort: Desc)])
  @@index([reviewed])                                        // admin review queue
  @@map("integrity_events")
}

model PlayerAchievement {                                    // D2.2 / §13.3
  id              String @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  playerId        String @db.Uuid
  seasonId        String @db.Uuid
  achievementType String @db.VarChar(32)                     // 'PLACEMENT_TIER' | 'SEASON_BADGE' ...
  tier            String @db.VarChar(16)                     // 'TOP_1'|'TOP_10'|'TOP_50'|'TOP_100'|'TOP_500'
  rankValue       Int
  awardedAt       DateTime @default(now()) @db.Timestamptz(6)
  player Player @relation(fields: [playerId], references: [id])
  season Season @relation(fields: [seasonId], references: [id])
  @@unique([playerId, seasonId, achievementType])
  @@index([playerId])
  @@map("player_achievements")
}

model CrSnapshot {                                           // D2.1 Timescale hypertable
  playerId      String @db.Uuid
  seasonId      String @db.Uuid
  snapshotAt    DateTime @db.Timestamptz(6)
  cr            Float
  mu            Float
  sigma         Float
  matchesPlayed Int
  @@id([playerId, seasonId, snapshotAt])
  @@map("cr_snapshots")
}
```

## 4. Raw-SQL migrations (applied after `prisma migrate`)

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;
-- hypertable (D2.1) — degrades gracefully: wrap in DO block, skip if extension missing
SELECT create_hypertable('cr_snapshots','snapshot_at', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
-- partial index for ingestion scan (D2 §3)
CREATE INDEX IF NOT EXISTS idx_matches_unprocessed ON matches(played_at) WHERE processed = false;
-- materialized leaderboard view (D2.3 / §11.1)
CREATE MATERIALIZED VIEW IF NOT EXISTS leaderboard_mv AS
  SELECT season_id, player_id, cr, mu, sigma,
         RANK() OVER (PARTITION BY season_id ORDER BY cr DESC) AS rank
  FROM player_seasons;
CREATE UNIQUE INDEX IF NOT EXISTS leaderboard_mv_pk ON leaderboard_mv(season_id, player_id);
CREATE INDEX IF NOT EXISTS leaderboard_mv_rank ON leaderboard_mv(season_id, rank);
-- refresh fn (called by scheduler every 30s per §11.1)
CREATE OR REPLACE FUNCTION refresh_leaderboard() RETURNS void AS $$
  REFRESH MATERIALIZED VIEW CONCURRENTLY leaderboard_mv;
$$ LANGUAGE sql;
```

## 5. shared-types (`packages/shared-types/src`)

- `enums.ts` — SeasonStatus, RatingMode, Severity, RegistrationSource, IntegrityFlagType, AchievementTier (string-literal unions + const arrays).
- `schemas.ts` — Zod: `SeasonConfigSchema` (placementCount, resetFactor, sigmaResetMult, sigmaResetCap, scaleFactor, baseOffset, softCapThreshold, maxDeltaMu, dispersionSigmaRef, placementWeights — mirrors `RatingParams`), `PaginationSchema`, `RiotIdSchema` (gameName#tag).
- `dtos.ts` — Zod-derived: `PlayerProfileDTO`, `LeaderboardEntryDTO`, `MatchRecordDTO`, `ChampionStatDTO`, `HeadToHeadDTO`. (Core set only; YAGNI on the rest.)
- `index.ts` barrel. Runtime dep: `zod` (allowed here, unlike the engine).

## 6. Package structure

```
packages/database/
  prisma/schema.prisma · prisma/migrations/
  prisma/sql/  (raw migrations §4)
  src/client.ts (PrismaClient singleton + graceful shutdown) · src/seed.ts
  test/ schema.test.ts (static: validate/diff/generate) · integration.test.ts (docker-gated)
  docker-compose.yml (timescale/timescaledb-ha:pg16) · package.json · README.md
packages/shared-types/
  src/{enums,schemas,dtos,index}.ts · test/schemas.test.ts · package.json
```

## 7. Test strategy

- **shared-types:** vitest — every Zod schema parses valid + rejects invalid; enum const-array ↔ union consistency.
- **database static (no DB):** `prisma validate` exits 0; `prisma migrate diff --from-empty --to-schema-datamodel --script` emits non-empty valid SQL; `prisma generate` then `tsc --noEmit` on `src/client.ts` (client types compile); raw-SQL §4 parses (sqlparser or a syntax smoke).
- **database live (docker-gated):** if `DATABASE_URL` reachable → `prisma migrate deploy` + apply raw SQL + CRUD smoke (insert player/season/playerSeason, refresh `leaderboard_mv`, query rank) + assert hypertable exists; else `test.skip` with a printed reason.
- CI: spin docker-compose Postgres/Timescale, run live suite.

## 8. Open questions for Trinity (schema-at-scale audit)

Leaderboard `leaderboard_mv` refresh contention at 250k players / 30s (CONCURRENTLY lock + RANK() full-scan cost); index coverage vs §11 query patterns (profile history, head-to-head, champion sort); `cr_snapshots` write volume (hourly × 250k = 6M rows/day) vs 7-day chunk sizing; partition `matches`/`match_participants` now vs defer (D2.7); `processed`-flag race & the right constraint/index for atomic dedup; JSONB flags query cost vs normalized; PgBouncer transaction-mode vs Prisma prepared statements.
