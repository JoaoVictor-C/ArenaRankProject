# Casual Ranked System
## Production-Ready Product Proposal
**Version 2.0 | Confidential**
*Prepared for: Stakeholders, Engineering Leadership & Investors*

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Project Vision and Objectives](#2-project-vision-and-objectives)
3. [Core Features and Functional Requirements](#3-core-features-and-functional-requirements)
4. [User Flow and System Workflow](#4-user-flow-and-system-workflow)
5. [Technical Architecture](#5-technical-architecture)
6. [Backend Structure](#6-backend-structure)
7. [Frontend Structure](#7-frontend-structure)
8. [Database Design](#8-database-design)
9. [API Design and Integrations](#9-api-design-and-integrations)
10. [Infrastructure and Deployment Strategy](#10-infrastructure-and-deployment-strategy)
11. [Scalability and Performance Considerations](#11-scalability-and-performance-considerations)
12. [Security and Authentication](#12-security-and-authentication)
13. [Data Processing Pipelines](#13-data-processing-pipelines)
14. [Monitoring and Observability](#14-monitoring-and-observability)
15. [AI and Analytics Components](#15-ai-and-analytics-components)
16. [Monetization Strategy](#16-monetization-strategy)
17. [Development Roadmap and Milestones](#17-development-roadmap-and-milestones)
18. [Risks and Technical Challenges](#18-risks-and-technical-challenges)
19. [Future Expansion Possibilities](#19-future-expansion-possibilities)

---

## 1. Executive Summary

The **Casual Ranked System (CRS)** is a third-party competitive rating platform for League of Legends casual game modes — beginning with Arena (Queue ID 1700) and expanding to ARAM Mayhem and beyond. It addresses a significant gap in the competitive ecosystem: players who invest serious time in casual modes have no official ladder, no skill-based matchmaking context, and no meaningful progression framework.

CRS provides a fair, transparent, and abuse-resistant **Casual Rating (CR)** powered by a modified TrueSkill algorithm, extended with placement-weighted scoring, multi-layer integrity enforcement, and a full statistical profile per player. The system is designed from the ground up for high availability, horizontal scalability, and eventual multi-game expansion.

This document presents CRS as a production-grade product: an engineering blueprint, a strategic roadmap, and a monetization framework suitable for stakeholder review, investor consideration, and developer onboarding.

**Market opportunity:** The League of Legends Arena mode consistently draws millions of active players per cycle. No official or third-party ranked system exists for this mode. CRS is positioned to become the definitive competitive reference for this audience, building a loyal community with strong retention mechanics.

---

## 2. Project Vision and Objectives

### 2.1 Vision Statement

To become the **authoritative competitive platform** for League of Legends casual game modes — creating meaningful progression, fair competition, and deep statistical insight for the millions of players overlooked by official ranked systems.

### 2.2 Strategic Objectives

| Objective | Description |
|---|---|
| **Fairness** | Rating reflects skill, not play volume or exploitable patterns |
| **Transparency** | Every CR change is explainable, traceable, and auditable |
| **Integrity** | Multi-layer anti-abuse: boosting detection, AFK protection, smurf mitigation |
| **Engagement** | Season structure, streaks, badges, and leaderboards drive long-term retention |
| **Scalability** | Architecture supports millions of matches and concurrent users without rearchitecting |
| **Extensibility** | Designed as a platform, not a single-mode tool |

### 2.3 Success Metrics (12-Month Targets)

- 250,000+ registered players
- 5,000,000+ processed matches
- 99.5% API uptime SLA maintained
- < 5-minute leaderboard update latency for Top 1000 players
- < 2% abuse flag rate on processed matches

---

## 3. Core Features and Functional Requirements

### 3.1 Rating System

- **TrueSkill-based CR** (Casual Rating) with placement-weighted pairwise scoring
- Placement multipliers for Duo Mode (8 teams) and Trio Mode (6 teams)
- Placement matches (first 10 games) with 2.0× amplification and provisional display
- Soft-reset between seasons: `new_CR = 1000 + (prev_CR − 1000) × 0.5`
- Conservative CR display formula: `CR = (μ − 3σ) × scale_factor + base_offset`
- Soft cap with diminishing returns above 5,000 CR; no hard ceiling

### 3.2 Integrity and Anti-Abuse

- **Rating Disparity Score (RDS)** for duo boosting detection with tiered penalties
- **AFK / Ineligible Player Protection** via `eligibleForProgression` flag — null result, no rating movement
- **Repeated lobby detection** — same composition appearing 3+ times in 24 hours flagged as match-fixing
- **Unusual duration flagging** — statistical outlier detection on match length
- **Win/Loss streak dampener** — loss protection floor at 0.25×, win bonus ceiling at 1.35×
- **Maximum rating dispersion control** — prevents single-player leaderboard distortion

### 3.3 Player Profiles

- Full per-season and all-time statistical breakdown
- Champion-level statistics: win rate, top-half rate, average placement, CR delta per champion
- Head-to-head statistics with specific players (win rate with/against)
- Provisional badge during placement phase
- Permanent season achievement badges and placement tiers (Top 1 / 10 / 50 / 100 / 500)
- Historical season archive on every profile

### 3.4 Leaderboard

- Public global leaderboard with pagination and filtering
- Regional and friend-circle sub-leaderboards
- Top 1000 priority processing lane (< 5-minute update latency)
- Soft lock display in the final 7 days of a season
- Real-time top-player activity feed (optional, user-controlled)

### 3.5 Match History

- Self-contained match records: placement, CR change, modifiers, teammates, integrity flags
- Full modifier breakdown per match: expected placement, premade bonus, streak dampener, AFK protection, boosting penalty
- Relative and absolute timestamps
- Champion icons, color-coded placement badges, CR delta indicators
- Admin-only integrity flag details; user-facing generic warning for severe flags

### 3.6 Season Management

- Admin panel for creating and managing season lifecycle: Active → Soft Lock → Ended → Off-Season
- Season archive with final standings snapshot
- Configurable placement match count, reset intensity, and cap formulas per season

---

## 4. User Flow and System Workflow

### 4.1 Player-Facing Flow

```
User lands on platform
        │
        ▼
Search by Riot ID (GameName#Tag)
        │
        ├─ Player not found → Auto-registration triggered via PUUID lookup
        │                     Displays provisional profile, placement match badge
        │
        └─ Player found → Profile page rendered
                                │
                                ├─ Overview: CR, rank, season standing
                                ├─ Match History: paginated, filterable
                                ├─ Champion Stats: sortable table + sparklines
                                ├─ Head-to-Head: search partner/opponent
                                └─ Season Archive: all past seasons
```

### 4.2 Match Processing Workflow

```
Riot API Match Endpoints
        │
        ▼
[ Ingestion Service ]
  Poll MatchIDs → Filter (QueueID, participant count, duration, date)
  Deduplicate via processed flag (atomic check)
        │
        ▼
[ Match Queue — Redis Streams ]
  Batched in groups of 100 MatchIDs
        │
        ├──── Top 1000 Priority Lane ────► [ Priority Worker Pool ]
        │                                          │
        └──── General Queue ──────────► [ Standard Worker Pool ]
                                                   │
                    ┌──────────────────────────────┘
                    ▼
        [ Processing Worker ]
          1. Fetch full match data (cache-first, 24h TTL)
          2. Validate all integrity filters
          3. Register unknown participants (auto-registration)
          4. Compute RDS — apply boosting modifiers if applicable
          5. Apply premade adjustment to expected outcomes
          6. Run TrueSkill pairwise placement computation
          7. Apply streak modifier (loss dampener / win bonus)
          8. Apply dispersion cap if triggered
          9. Write CR updates (sequential per player — mutex lock)
         10. Write Match Record + Participant snapshots
         11. Update champion statistics
         12. Update streak counters
         13. Emit integrity flags to audit log
         14. Invalidate relevant caches
                    │
                    ▼
        [ Database Layer ]
          Postgres (relational core) + Redis (cache + queues)
                    │
                    ▼
        [ API / Frontend ]
          Leaderboard · Profile · Match History · Admin Panel
```

### 4.3 Admin Workflow

```
Admin authenticates via SSO (role: ADMIN)
        │
        ├─ Season Management: create, configure, transition lifecycle
        ├─ Integrity Review Queue: review flagged matches, apply manual overrides
        ├─ Player Flags: view account-level moderation flags, add notes
        ├─ DLQ Review: inspect failed matches, trigger manual reprocessing
        └─ System Health Dashboard: queue depth, worker status, error rates
```

---

## 5. Technical Architecture

### 5.1 System Overview

CRS follows a **microservices-inspired monorepo architecture** with clear service boundaries, deployed via containers on a managed Kubernetes platform. Services communicate via async message queues for processing and synchronous REST/gRPC for queries.

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                            │
│    Next.js Web App        Mobile PWA        Public REST API     │
└───────────────────────────────┬─────────────────────────────────┘
                                │ HTTPS
┌───────────────────────────────▼─────────────────────────────────┐
│                      API GATEWAY (Kong / AWS API GW)            │
│   Auth · Rate Limiting · Request Routing · TLS Termination      │
└───────┬───────────────────────┬──────────────────────┬──────────┘
        │                       │                      │
┌───────▼──────┐   ┌────────────▼──────────┐  ┌───────▼──────────┐
│  Player API  │   │   Leaderboard API     │  │   Admin API      │
│  (NestJS)    │   │   (NestJS + Cache)    │  │   (NestJS, Auth) │
└───────┬──────┘   └────────────┬──────────┘  └───────┬──────────┘
        │                       │                      │
┌───────▼───────────────────────▼──────────────────────▼──────────┐
│                     SERVICE LAYER (NestJS Modules)               │
│  RatingService · StatsService · IntegrityService · SeasonService │
└───────────────────────────────┬─────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────┐
│                    PROCESSING LAYER                              │
│  IngestionWorker · MatchProcessor · RDSEvaluator · CacheWarmer  │
└───────┬───────────────────────┬─────────────────────────────────┘
        │ Redis Streams         │ BullMQ
┌───────▼──────┐   ┌────────────▼──────────────────────────────── ┐
│ Redis Cluster│   │         Data Layer                           │
│ (Queues +    │   │   PostgreSQL (Primary) + Read Replicas       │
│  Cache)      │   │   TimescaleDB (time-series stats)            │
└──────────────┘   │   S3-compatible (match snapshots / archives) │
                   └──────────────────────────────────────────────┘
```

### 5.2 Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| **Frontend** | Next.js 14 (App Router), TypeScript, Tailwind CSS | SSR/ISR for SEO and performance; React Server Components |
| **Backend** | NestJS (Node.js), TypeScript | Modular, DI-based architecture; strong typing across stack |
| **Queue / Cache** | Redis 7 (Streams + BullMQ) | Low-latency job processing; atomic operations for dedup |
| **Primary Database** | PostgreSQL 16 | Relational integrity; JSONB for flexible flag storage |
| **Time-Series** | TimescaleDB (PostgreSQL extension) | Efficient querying of historical rating/stat snapshots |
| **Object Storage** | AWS S3 / Cloudflare R2 | Season archives, match data snapshots at scale |
| **API Gateway** | Kong Gateway | Auth enforcement, rate limiting, routing, observability |
| **Containerization** | Docker + Kubernetes (EKS/GKE) | Horizontal scaling, rolling deploys, service isolation |
| **CI/CD** | GitHub Actions + ArgoCD | GitOps workflows, automated testing, staged rollouts |
| **Observability** | Grafana + Prometheus + Loki | Metrics, alerting, structured log aggregation |
| **CDN** | Cloudflare | DDoS protection, edge caching, static asset delivery |

---

## 6. Backend Structure

### 6.1 Monorepo Organization

```
/apps
  /api            → NestJS REST API (public endpoints)
  /admin-api      → NestJS Admin API (protected)
  /ingestion      → Ingestion service (Riot API polling)
  /processor      → Match processing workers (BullMQ consumers)
  /scheduler      → Cron-based tasks (season transitions, cache warming)

/packages
  /rating-engine  → TrueSkill implementation, modifier logic (pure TypeScript, fully testable)
  /integrity      → RDS calculator, flag evaluators, abuse scoring
  /riot-client    → Riot API SDK wrapper (token bucket, retry, caching)
  /shared-types   → DTOs, enums, Zod schemas shared across services
  /database       → Prisma schema, migrations, typed query helpers

/infrastructure
  /k8s            → Kubernetes manifests and Helm charts
  /terraform      → Cloud infrastructure as code
  /docker         → Dockerfiles per service
```

### 6.2 Core Service Modules

**RatingService**
- Encapsulates all TrueSkill computation
- Accepts a `MatchInput` (placements, team compositions, pre-match CRs)
- Outputs a `RatingResult` (per-player CR delta, sigma update, modifiers applied)
- Fully stateless and deterministic — same input always produces same output
- 100% unit tested; used in both processing pipeline and simulation tooling

**IntegrityService**
- Evaluates each match for RDS, lobby repetition, unusual duration
- Emits structured `IntegrityFlag` objects — never mutates match data directly
- Operates as a pure scoring function; enforcement is handled downstream
- Maintains a rolling 24-hour lobby fingerprint cache in Redis

**StatsService**
- Aggregates champion stats, head-to-head data, and streak states
- Uses database transactions to update multiple counters atomically
- Exposes batch-update APIs for processing workers to minimize round trips

**SeasonService**
- Manages season lifecycle transitions via state machine (Active → Soft Lock → Ended → Off-Season)
- Runs soft-reset calculations on season start
- Generates and stores season snapshots to S3 on season end

### 6.3 Worker Architecture

**IngestionWorker**
- Runs on a configurable polling interval (e.g., every 60 seconds)
- Fetches MatchIDs from Riot `/match/v5/matches/by-puuid` and `/match/v5/matches/{matchId}`
- Pushes eligible MatchIDs to the appropriate Redis Stream (priority or general)
- Maintains token bucket state per API key in Redis

**MatchProcessor (BullMQ Consumer)**
- Instantiated as N concurrent workers (configurable per environment)
- Processes one match per job; failures requeue automatically up to 3× before DLQ
- Each job is idempotent: checks `processed` flag before beginning, sets it atomically on commit
- Emits a `match.processed` event on completion for downstream consumers (cache invalidation, webhooks)

**Priority Workers**
- Dedicated worker pool subscribed exclusively to the priority stream
- Separate resource allocation (CPU/memory) in Kubernetes; auto-scaled independently

---

## 7. Frontend Structure

### 7.1 Application Architecture

The frontend is a **Next.js 14** application using the App Router with React Server Components where applicable and client components for interactive elements. It communicates exclusively with the public CRS API.

```
/app
  /[region]/[gameName]/[tagLine]  → Player Profile Page
  /leaderboard                    → Global Leaderboard
  /leaderboard/[season]           → Historical Season Leaderboard
  /matches/[matchId]              → Match Detail Page
  /admin                          → Admin Panel (protected route)
  /api                            → Next.js API routes (BFF layer)

/components
  /profile
    PlayerHeader.tsx              → CR display, rank badge, season standing
    MatchHistoryList.tsx          → Paginated match history
    ChampionStatsTable.tsx        → Sortable champion breakdown
    HeadToHeadPanel.tsx           → Duo/opponent statistics
  /leaderboard
    LeaderboardTable.tsx          → Virtualized, paginated ranking table
    SeasonSelector.tsx            → Switch between active/historical seasons
  /shared
    CRTrendChart.tsx              → D3.js / Recharts CR over time sparkline
    PlacementBadge.tsx            → Color-coded placement indicator
    IntegrityWarningBadge.tsx     → User-facing flag indicator
    StreakIndicator.tsx           → Current streak display

/lib
  api.ts                          → Typed API client with SWR integration
  trueskill-display.ts            → CR formatting, tier calculation utilities
  auth.ts                         → NextAuth.js session helpers
```

### 7.2 Rendering Strategy

| Page | Strategy | Rationale |
|---|---|---|
| Player Profile | ISR (60s revalidation) | High traffic; content changes frequently but not in real time |
| Leaderboard | ISR (30s revalidation) | Balance freshness with server load |
| Match Detail | Static on first view, then cached | Match data is immutable once processed |
| Admin Panel | SSR + auth guard | Security-sensitive; no caching |

### 7.3 Performance Targets

- **Largest Contentful Paint (LCP):** < 2.0s on 4G connections
- **Time to Interactive (TTI):** < 3.5s
- **Cumulative Layout Shift (CLS):** < 0.1
- Leaderboard table virtualized via `react-virtual` to handle 1000+ visible rows without DOM bloat

---

## 8. Database Design

### 8.1 Schema Overview (PostgreSQL + Prisma)

**players**
```sql
id            UUID PRIMARY KEY DEFAULT gen_random_uuid()
puuid         VARCHAR(78) UNIQUE NOT NULL   -- Riot PUUID
summoner_name VARCHAR(64)                   -- Latest known name
tag_line      VARCHAR(8)
region        VARCHAR(8)
registered_at TIMESTAMPTZ DEFAULT NOW()
registration_source VARCHAR(16)            -- 'auto' | 'manual'
moderation_flags JSONB DEFAULT '[]'
```

**player_seasons**
```sql
id            UUID PRIMARY KEY
player_id     UUID REFERENCES players(id)
season_id     UUID REFERENCES seasons(id)
cr            FLOAT NOT NULL DEFAULT 1000.0
mu            FLOAT NOT NULL DEFAULT 1000.0
sigma         FLOAT NOT NULL DEFAULT 350.0
matches_played INT DEFAULT 0
placement_matches_remaining INT DEFAULT 10
is_provisional BOOLEAN DEFAULT TRUE
peak_cr       FLOAT DEFAULT 1000.0
current_streak INT DEFAULT 0              -- positive = wins, negative = losses
UNIQUE(player_id, season_id)
```

**matches**
```sql
id            UUID PRIMARY KEY
riot_match_id VARCHAR(32) UNIQUE NOT NULL
queue_id      INT NOT NULL
mode          VARCHAR(8) NOT NULL          -- 'DUOS' | 'TRIOS'
season_id     UUID REFERENCES seasons(id)
played_at     TIMESTAMPTZ NOT NULL
processed_at  TIMESTAMPTZ
processed     BOOLEAN DEFAULT FALSE
integrity_flags JSONB DEFAULT '[]'
duration_seconds INT
```

**match_participants**
```sql
id            UUID PRIMARY KEY
match_id      UUID REFERENCES matches(id)
player_id     UUID REFERENCES players(id)
champion_id   INT NOT NULL
team_id       INT NOT NULL
placement     INT NOT NULL
eligible      BOOLEAN NOT NULL
cr_before     FLOAT NOT NULL
cr_after      FLOAT NOT NULL
cr_delta      FLOAT NOT NULL
is_premade    BOOLEAN DEFAULT FALSE
party_id      VARCHAR(36)
modifiers     JSONB                        -- snapshot of all modifiers applied
```

**champion_stats** (per player × champion × season)
```sql
id             UUID PRIMARY KEY
player_id      UUID REFERENCES players(id)
season_id      UUID REFERENCES seasons(id)
champion_id    INT NOT NULL
matches_played INT DEFAULT 0
wins           INT DEFAULT 0
top_half       INT DEFAULT 0
total_placement_sum INT DEFAULT 0
cr_delta_sum   FLOAT DEFAULT 0
last_10_placements INT[] DEFAULT '{}'
UNIQUE(player_id, season_id, champion_id)
```

**seasons**
```sql
id            UUID PRIMARY KEY
name          VARCHAR(64) NOT NULL
queue_id      INT NOT NULL
starts_at     TIMESTAMPTZ NOT NULL
ends_at       TIMESTAMPTZ NOT NULL
status        VARCHAR(16) NOT NULL        -- 'ACTIVE' | 'SOFT_LOCK' | 'ENDED' | 'OFF_SEASON'
config        JSONB                       -- placement_count, reset_factor, cap params
```

**integrity_events** (audit log)
```sql
id            UUID PRIMARY KEY
match_id      UUID REFERENCES matches(id)
player_id     UUID
flag_type     VARCHAR(32) NOT NULL
severity      VARCHAR(8) NOT NULL         -- 'INFO' | 'WARN' | 'CRITICAL'
metadata      JSONB
created_at    TIMESTAMPTZ DEFAULT NOW()
reviewed      BOOLEAN DEFAULT FALSE
reviewer_id   UUID
```

### 8.2 Indexing Strategy

```sql
CREATE INDEX idx_player_seasons_cr ON player_seasons(season_id, cr DESC);  -- Leaderboard
CREATE INDEX idx_match_participants_player ON match_participants(player_id, match_id);  -- Profile history
CREATE INDEX idx_matches_played_at ON matches(played_at DESC);
CREATE INDEX idx_champion_stats_lookup ON champion_stats(player_id, season_id);
CREATE INDEX idx_integrity_events_player ON integrity_events(player_id, created_at DESC);
```

### 8.3 Time-Series Data (TimescaleDB)

A hypertable `cr_snapshots` stores hourly CR checkpoints per player per season, partitioned by time. This powers historical CR trend charts on player profiles efficiently without scanning the full `match_participants` table.

```sql
cr_snapshots (player_id, season_id, snapshot_at, cr, mu, sigma, matches_played)
-- Hypertable partitioned by snapshot_at with 1-week chunks
```

---

## 9. API Design and Integrations

### 9.1 Public REST API

**Base URL:** `https://api.casualranked.gg/v1`

All endpoints return JSON. Errors follow RFC 7807 (Problem Details).

**Players**
```
GET    /players/{puuid}                         Player summary (active season)
GET    /players/{puuid}/seasons/{seasonId}      Season-specific profile
GET    /players/{puuid}/matches                 Match history (paginated, filterable)
GET    /players/{puuid}/champions               Champion stats (active season)
GET    /players/{puuid}/head-to-head/{puuid2}   Head-to-head stats with another player
GET    /players/search?name={name}&tag={tag}    Search by Riot ID
```

**Leaderboard**
```
GET    /leaderboard?season={id}&page={n}&limit={n}   Global leaderboard (paginated)
GET    /leaderboard/top?season={id}&n={n}             Top N players (max 100)
```

**Matches**
```
GET    /matches/{matchId}                        Full match record with all participants
```

**Seasons**
```
GET    /seasons                                  All seasons (summary)
GET    /seasons/active                           Currently active season
GET    /seasons/{seasonId}                       Season details + config
```

**Champions** *(static reference)*
```
GET    /champions                                All champion IDs and names
```

### 9.2 Response Caching Strategy

| Endpoint | Cache Layer | TTL |
|---|---|---|
| Leaderboard top 100 | Redis + CDN Edge | 30 seconds |
| Player profile | Redis | 60 seconds |
| Match record | CDN Edge | Immutable (1 year) |
| Champion stats | Redis | 5 minutes |
| Head-to-head | Redis | 1 hour |

### 9.3 Riot API Integration

The `riot-client` package wraps Riot's Developer API with:

- **Token bucket rate limiting** per API key (configurable burst and refill): enforced in Redis with Lua scripts for atomic decrement
- **Exponential backoff** with jitter on HTTP 429 and 503 responses
- **Circuit breaker** pattern (5 failures in 10 seconds → open circuit for 30 seconds)
- **Request coalescing:** if two workers request the same MatchID simultaneously, the second waits on the first's result (Redis-based promise coalescing)
- **24-hour TTL cache** for match data stored in Redis; overflow archived to S3

### 9.4 Webhooks (Phase 2)

An opt-in webhook system will allow platform integrations to subscribe to:

- `match.processed` — a tracked player's match has been rated
- `season.started` / `season.ended`
- `integrity.flagged` — a critical integrity event on a tracked player

Webhooks are HMAC-SHA256 signed, have retry logic with exponential backoff, and support delivery confirmation tracking.

---

## 10. Infrastructure and Deployment Strategy

### 10.1 Cloud Architecture (AWS Primary)

```
Route 53 → Cloudflare (DNS + DDoS + CDN)
    │
    ▼
AWS Application Load Balancer
    │
    ▼
EKS Cluster (Kubernetes)
  ├── Namespace: api           → api, admin-api deployments
  ├── Namespace: processing    → ingestion, processor, scheduler deployments
  ├── Namespace: data          → Postgres (RDS), Redis (ElastiCache), TimescaleDB
  └── Namespace: observability → Prometheus, Grafana, Loki, AlertManager

AWS S3      → Season archives, match snapshots
AWS RDS     → PostgreSQL 16 Multi-AZ (primary + 1 read replica initially)
ElastiCache → Redis 7 Cluster Mode (3 shards, 1 replica each)
ECR         → Private container registry
```

### 10.2 Environment Strategy

| Environment | Purpose | Scale |
|---|---|---|
| **Development** | Local Docker Compose; mocked Riot API | Minimal |
| **Staging** | Full cloud stack; production data mirror (anonymized) | 25% prod scale |
| **Production** | Live, real data; full redundancy | Autoscaled |

### 10.3 CI/CD Pipeline (GitHub Actions + ArgoCD)

```
Push to feature branch
    → Lint + Type Check + Unit Tests
    → Build Docker image + push to ECR (dev tag)

Merge to main
    → Full test suite (unit + integration + E2E)
    → Build + tag production image
    → ArgoCD auto-sync to staging
    → Automated smoke tests on staging
    → Manual approval gate
    → ArgoCD promotes to production (rolling update)
```

### 10.4 Kubernetes Resource Configuration

**Processing workers** autoscale based on Redis queue depth via KEDA (Kubernetes Event-Driven Autoscaling):
- Scale from 2 → 20 workers when queue depth exceeds 500 matches
- Scale back to minimum after 5 minutes of idle queue

**API services** autoscale based on CPU (target 60%) with a minimum of 3 replicas for HA.

### 10.5 Database Operations

- **Automated backups:** RDS daily snapshots retained for 30 days; point-in-time recovery enabled
- **Migrations:** Managed via Prisma Migrate with zero-downtime patterns (additive-only in CI)
- **Failover:** RDS Multi-AZ with automatic failover < 60 seconds
- **Connection pooling:** PgBouncer deployed as a sidecar to each processing namespace, transaction-mode pooling

---

## 11. Scalability and Performance Considerations

### 11.1 Read Path Optimization

The read path (player profiles, leaderboards) must serve high concurrency at low latency. The strategy is layered:

1. **CDN edge cache** (Cloudflare) — static and near-static pages (match detail, historical leaderboard)
2. **Redis application cache** — profile data, active leaderboard, champion stats
3. **PostgreSQL read replicas** — long-tail queries that miss cache
4. **Materialized leaderboard view** — pre-computed and refreshed every 30 seconds; the API never runs a live ORDER BY on `player_seasons`

### 11.2 Write Path Optimization

All CR updates use **sequential writes per player** enforced by Redis distributed locks (Redlock pattern). This ensures:
- No race conditions when the same player appears in multiple matches processed concurrently
- Lock TTL is set to 10 seconds (well above expected write time); automatic expiry prevents deadlocks

**Batch stat updates:** Champion statistics and streak counters are updated in a single transaction per participant, not one update per field.

### 11.3 Expected Throughput

| Metric | Estimate | Supported Capacity |
|---|---|---|
| Matches/day (Arena peak season) | ~500,000 | 2,000,000+ (20-worker pool) |
| Leaderboard requests/sec | ~2,000 | 10,000+ (CDN + Redis) |
| Profile page requests/sec | ~5,000 | 20,000+ (ISR + Redis) |
| Match history queries/sec | ~1,000 | 5,000+ (indexed, cached) |

### 11.4 Queue Backpressure

If the match queue depth exceeds a configurable threshold (e.g., 100,000 unprocessed matches), the ingestion service enters **pressure mode**:
- Stops fetching new MatchIDs
- Prioritizes enriching and processing matches already queued
- Resumes normal ingestion when queue depth drops below the low-water mark

This prevents unbounded queue growth during API bursts and season starts.

---

## 12. Security and Authentication

### 12.1 Authentication Architecture

- **Public API:** Read-only endpoints are unauthenticated. Rate limited at the API gateway (100 req/min per IP; 1,000 req/min for registered API key holders)
- **User accounts:** Optional; linked to Riot account via OAuth 2.0 (Riot SSO). Enables features: friend leaderboards, notifications, preference persistence
- **Admin panel:** NextAuth.js with Google Workspace SSO + RBAC. Roles: `ADMIN`, `MODERATOR`, `VIEWER`
- **Service-to-service:** Internal services communicate over mTLS within the cluster; API keys for cross-service auth injected via Kubernetes Secrets

### 12.2 API Security

- All external traffic served over TLS 1.3 only
- API Gateway enforces authentication, rate limiting, and request size limits before any request reaches application code
- Riot API keys stored in AWS Secrets Manager; rotated quarterly; never present in application code or environment variables in plaintext
- Input validation on all endpoints using Zod schemas; unknown fields rejected

### 12.3 Anti-Scraping and Abuse

- Cloudflare Bot Management for the web frontend
- Aggressive rate limiting on search endpoints (20 req/min per IP)
- API key tiers for third-party developers; usage tracked and throttled
- CORS policy: web frontend origin only for browser requests; wildcard only for explicitly public endpoints

### 12.4 Data Privacy

- PUUID is used as the internal player identifier; summoner names are stored as snapshots only (logged at match time, not updated retroactively — name changes are non-breaking)
- No personal data beyond publicly available Riot API data is collected
- GDPR-compliant data deletion: `DELETE /players/{puuid}` removes all personal records within 30 days (match aggregate data is anonymized, not deleted)
- Privacy policy and terms of service required before account creation

### 12.5 Dependency Security

- `npm audit` and Snyk scans run on every CI build
- Docker base images pinned to specific SHA digests
- Dependabot configured for automated security patch PRs
- SBOM (Software Bill of Materials) generated on each release

---

## 13. Data Processing Pipelines

### 13.1 Ingestion Pipeline Detail

```
Scheduler (every 60s)
    │
    ├─ Fetch MatchIDs for tracked players (PUUID list)
    │    └─ Source: player_seasons WHERE matches_played > 0 (active players)
    │
    ├─ Fetch MatchIDs from global endpoint (new player discovery)
    │
    ├─ Deduplicate against processed_matches Redis set
    │
    ├─ Classify: Top-1000 player involved? → Priority stream
    │            Otherwise → Standard stream
    │
    └─ Enqueue MatchIDs as BullMQ jobs with priority metadata
```

### 13.2 Match Processing Pipeline Detail

```
Job dequeued by worker
    │
    ├─ Check `processed` flag (Redis atomic GET/SET)
    │    └─ Already processed → Acknowledge job, exit
    │
    ├─ Fetch match data (Redis cache → Riot API → store in Redis + S3)
    │
    ├─ Validate filters (QueueID, participant count, duration, season range)
    │    └─ Fails filter → Mark as FILTERED, emit audit log, exit
    │
    ├─ Register unknown participants (batch insert, concurrent-safe)
    │
    ├─ Run IntegrityService.evaluate(match)
    │    └─ Emits zero or more IntegrityFlag objects
    │
    ├─ For each team:
    │    ├─ Determine party composition → premade modifier
    │    ├─ Compute RDS for premade pairs → boosting modifier
    │    └─ Check AFK eligibility → null result path
    │
    ├─ Run RatingEngine.compute(matchInput)
    │    ├─ TrueSkill pairwise update for each placement pair
    │    ├─ Apply placement weight multiplier
    │    ├─ Apply placement match multiplier (if provisional)
    │    ├─ Apply streak modifier
    │    ├─ Apply dispersion cap
    │    └─ Return RatingResult[] per player
    │
    ├─ Begin database transaction:
    │    ├─ Update player_seasons (CR, mu, sigma, streak, peak)
    │    ├─ Insert match_participants (snapshot CR deltas + modifiers)
    │    ├─ Upsert champion_stats
    │    ├─ Insert cr_snapshot (TimescaleDB)
    │    ├─ Mark match as processed
    │    └─ Insert integrity_events (if any flags)
    │
    ├─ Commit transaction
    │
    ├─ Invalidate Redis cache keys for affected players
    │
    └─ Emit `match.processed` event → cache warmer + webhook dispatcher
```

### 13.3 Season Transition Pipeline

When a season status transitions to `ENDED` (scheduled or manual):
1. Scheduler triggers `SeasonService.closeseason(seasonId)`
2. Snapshot all `player_seasons` records to S3 as Parquet files
3. Generate top-tier achievement badges (Top 1/10/50/100/500) based on final CR sort
4. Write badge records to `player_achievements` table
5. Set season status to `ENDED` — ingestion service stops processing new matches for this season
6. Trigger season archive cache warm-up

When a new season starts:
1. Admin creates season record via Admin API
2. `SeasonService.softReset()` runs on scheduler at `starts_at`:
   - For all players with `matches_played > 0` in the previous season: `new_CR = 1000 + (prev_CR − 1000) × 0.5`
   - Sigma partially reset: `new_sigma = sigma × 1.5` (capped at 350)
   - New `player_seasons` row created; all players start the new season
3. Ingestion begins processing new-season matches

---

## 14. Monitoring and Observability

### 14.1 Metrics (Prometheus + Grafana)

**Processing Metrics**
- `crs_matches_processed_total` — counter by outcome (success, filtered, failed)
- `crs_queue_depth` — gauge per queue (priority, standard, DLQ)
- `crs_processing_duration_seconds` — histogram (p50, p95, p99)
- `crs_worker_active_count` — gauge
- `crs_riot_api_requests_total` — counter by status code
- `crs_riot_api_rate_limit_hits_total` — counter

**Business Metrics**
- `crs_players_registered_total`
- `crs_active_season_player_count`
- `crs_integrity_flags_total` — counter by flag type
- `crs_leaderboard_update_latency_seconds` — histogram for Top 1000 players

**Infrastructure Metrics**
- Standard Kubernetes node/pod metrics via kube-state-metrics
- PostgreSQL metrics via postgres_exporter (connection pool, query latency, replication lag)
- Redis metrics via redis_exporter (memory, hit rate, queue depth)

### 14.2 Alerting Rules

| Alert | Condition | Severity |
|---|---|---|
| Processing lag | Queue depth > 50,000 for > 10 min | WARNING |
| Processing stalled | No matches processed in > 15 min during active season | CRITICAL |
| High DLQ rate | DLQ intake > 1% of processed in 5 min | WARNING |
| API error spike | 5xx rate > 1% over 2 min | CRITICAL |
| Leaderboard staleness | Top 1000 player unupdated > 10 min | WARNING |
| DB replication lag | > 5 seconds | WARNING |
| Redis memory | > 80% used | WARNING |

### 14.3 Logging Strategy (Loki + Structured JSON)

All services emit structured JSON logs with mandatory fields: `level`, `service`, `traceId`, `timestamp`, `message`. Sensitive fields (PUUIDs in error contexts) are redacted.

Log retention: 30 days hot (Loki), 1 year cold (S3 Glacier).

### 14.4 Distributed Tracing

OpenTelemetry SDK integrated across all NestJS services. Traces exported to Grafana Tempo. End-to-end trace for a single match: ingestion → queue → processing → database write, visible in a single trace waterfall for debugging latency issues.

### 14.5 Operational Runbooks

Documented runbooks for:
- DLQ backlog remediation
- Riot API key rotation
- Season transition manual override
- Emergency leaderboard freeze
- Database failover checklist

---

## 15. AI and Analytics Components

### 15.1 Smurf / New Account Detection (Phase 2)

New accounts that exhibit unusually high placement rates in early matches are candidates for smurf acceleration:
- A logistic regression model trained on historical player progression curves detects anomalous convergence speed
- Detected accounts have their sigma artificially elevated, causing faster CR movement (converges to true rating faster)
- No punitive action taken — purely a rating accuracy improvement

### 15.2 Match Outcome Prediction (Internal)

A lightweight gradient boosting model (XGBoost) trained on historical match data provides expected placement distributions per team, factoring in:
- Pre-match CR differential between all teams
- Champion pool synergy scores (from historical data)
- Recent form (last 10 placements per player)

This model feeds the **Expected Placement** display in match history, making the CR change more interpretable to players.

### 15.3 Anomaly Detection for Match Integrity

Beyond rule-based flags, an isolation forest model monitors for statistical anomalies:
- Unusually consistent placements across a fixed lobby (possible collusion)
- CR manipulation patterns across multiple accounts
- Abnormal play time distributions (bots)

Anomaly scores are stored alongside integrity flags and surfaced in the admin review queue.

### 15.4 Player Insights (Premium Feature)

Optional AI-generated insights per player profile (powered by an LLM call against aggregated stats):
- "Your win rate increases 23% when playing in your strongest 5 champions"
- "You average 0.4 placements better in trios than duos"
- "Your CR has been most volatile on Fridays — consider your playtimes"

Cached per player per day; generated on-demand and stored.

---

## 16. Monetization Strategy

CRS is positioned as a **freemium platform** with community-first principles. Core ranking features remain free forever.

### 16.1 CRS Pro (Subscription — ~$4.99/month or $39.99/year)

| Feature | Free | Pro |
|---|---|---|
| CR tracking + leaderboard | ✓ | ✓ |
| Match history (last 50) | ✓ | ✓ |
| Full match history (unlimited) | — | ✓ |
| Champion stats (all seasons) | Current only | ✓ |
| CR trend chart (last 30 days) | ✓ | ✓ |
| CR trend chart (full season) | — | ✓ |
| AI player insights | — | ✓ |
| Head-to-head stats | Limited (last 20 matches) | ✓ |
| Priority data processing | Standard | Accelerated |
| Profile customization (banner, badge showcase) | — | ✓ |
| Export stats to CSV | — | ✓ |

### 16.2 Developer API Access

Third-party developers who want programmatic access to CRS data can apply for API keys with tiered plans:

| Tier | Requests/min | Price |
|---|---|---|
| Free | 30 | Free |
| Hobby | 300 | $9.99/month |
| Business | 3,000 | $79.99/month |

### 16.3 Sponsored Seasons

Brands relevant to the gaming ecosystem (peripherals, energy drinks, VPN services) can sponsor seasonal leaderboards — receiving logo placement on the leaderboard header and season badge design. Revenue share model with Riot ToS compliance review.

### 16.4 Community Tournaments

CRS can host structured community tournaments where registration, bracket seeding (CR-based), and results tracking are managed on-platform. A small entry fee model or free entry with premium bracket export drives conversion to Pro.

### 16.5 Revenue Projections (Year 1)

| Stream | Estimate |
|---|---|
| Pro subscriptions (2% of 250K users) | ~$300,000 ARR |
| API access fees | ~$50,000 ARR |
| Sponsored seasons (2 per year) | ~$40,000 |
| **Total Year 1 Estimate** | **~$390,000 ARR** |

---

## 17. Development Roadmap and Milestones

### Phase 0 — Foundation (Weeks 1–6)

- [ ] Monorepo setup: NestJS, Next.js, Prisma, Docker, CI pipeline
- [ ] Riot API client with rate limiting, caching, and retry logic
- [ ] Database schema implementation and migration tooling
- [ ] TrueSkill rating engine (pure TypeScript, fully unit tested)
- [ ] Core integrity module (RDS, flag evaluators)
- [ ] Ingestion service (filtering, dedup, queue publishing)
- [ ] Basic match processing worker (happy path only)

### Phase 1 — Arena MVP (Weeks 7–14)

- [ ] Full processing pipeline (all modifiers: streak, premade, AFK, dispersion)
- [ ] Player registration and auto-registration
- [ ] Placement match system with provisional display
- [ ] REST API: player profile, match history, champion stats, leaderboard
- [ ] Next.js frontend: profile page, leaderboard, match history
- [ ] Admin panel: season management, DLQ review, integrity queue
- [ ] Season 1 soft reset and lifecycle management
- [ ] Redis caching layer and materialized leaderboard
- [ ] Kubernetes deployment to staging
- [ ] Load testing and performance validation

### Phase 1.5 — Hardening and Growth (Weeks 15–20)

- [ ] Distributed tracing (OpenTelemetry)
- [ ] Full alerting and runbook documentation
- [ ] CR trend charts (TimescaleDB integration)
- [ ] Head-to-head statistics API and UI
- [ ] Top 1000 priority processing lane
- [ ] Public beta launch; community feedback collection
- [ ] CRS Pro subscription infrastructure (Stripe integration)
- [ ] API key developer tier

### Phase 2 — ARAM Mayhem (Weeks 21–28)

- [ ] ARAM Mayhem design document (separate spec)
- [ ] Binary win/loss rating variant with kill-differential margin
- [ ] 5-stack premade normalization calibration
- [ ] Early surrender detection integration
- [ ] ARAM mode toggle on frontend (unified profile, separate season)
- [ ] Cross-mode leaderboards

### Phase 3 — Intelligence and Expansion (Weeks 29–40)

- [ ] Smurf detection model training and deployment
- [ ] Match outcome prediction model
- [ ] AI player insights (LLM integration)
- [ ] Community tournament platform
- [ ] Webhook system for third-party integrations
- [ ] Mobile-optimized PWA
- [ ] Multi-region support (EUW, KR, etc.)

---

## 18. Risks and Technical Challenges

### 18.1 Riot API Dependency

**Risk:** Riot API changes endpoint structure, deprecates fields, or significantly reduces rate limits.
**Mitigation:** Abstract all Riot API calls behind `riot-client`; version-lock API versions; monitor Riot developer changelog. Cache aggressively to reduce dependency on API availability.

### 18.2 Riot Terms of Service Compliance

**Risk:** CRS is a third-party tool subject to Riot's Developer Agreement. Monetization strategies must remain compliant.
**Mitigation:** Legal review of Riot's Developer Portal ToS before monetization launch. Avoid any feature that could be perceived as pay-to-win or stat manipulation. Proactively communicate with Riot Developer Relations if the platform reaches scale requiring a partnership-tier API key.

### 18.3 Rating System Fairness Perception

**Risk:** Players perceive the CR system as unfair, leading to community backlash and low retention.
**Mitigation:** Full modifier transparency per match (shown in match detail). Public documentation of all formulas. Community feedback channel. Willingness to tune parameters per-season based on data.

### 18.4 Scale at Season Start

**Risk:** All players return at season start simultaneously, creating a spike in match ingestion and processing demand.
**Mitigation:** KEDA autoscaling tested against 10× normal load. Queue backpressure logic prevents unbounded growth. Proactive worker pool warm-up 1 hour before season start. Staged rollout of season-start announcements to spread load.

### 18.5 Data Consistency Under Failures

**Risk:** A worker crash mid-processing leaves the database in a partially updated state.
**Mitigation:** All match processing is wrapped in a database transaction. The `processed` flag is only set on transaction commit. Failed jobs requeue and are reprocessed idempotently — same input always produces same output.

### 18.6 Cheating and Coordinated Abuse Evolution

**Risk:** Sophisticated users discover and exploit gaps in the anti-abuse system.
**Mitigation:** Integrity system is pluggable and extensible — new flag types can be added without system changes. The anomaly detection layer (Phase 3) catches patterns rule-based systems miss. Moderation team reviews flagged accounts; system does not automate punishments.

---

## 19. Future Expansion Possibilities

### 19.1 Multi-Game Platform

The CRS architecture is deliberately game-agnostic at the infrastructure layer. Expanding to:
- **Teamfight Tactics (TFT)** — placement-based, same TrueSkill model applies directly
- **Legends of Runeterra** — binary win/loss variant
- **Valorant Unrated / Quickplay** — skill tracking for non-competitive modes

Each new game mode is a new `queue_id` configuration and rating engine variant on shared infrastructure.

### 19.2 Embedded Widgets

A publicly embeddable JavaScript widget (iframe-free, Web Component-based) that streamers and content creators can embed on their personal sites, displaying their live CR, rank, and recent placements. Drive brand awareness and organic acquisition.

### 19.3 Discord Integration

A Discord bot (`/rank`, `/leaderboard`, `/match`) allowing guild admins to set up server-specific CRS leaderboards, track season standings, and receive match result notifications. Powered by the Webhook API and Discord.js.

### 19.4 Coaching and VOD Marketplace

Premium feature connecting high-CR players with players seeking coaching, facilitated through the platform using CR as a trust and qualification signal. Revenue share model.

### 19.5 Esports Organization Dashboards

Private dashboards for amateur esports organizations to track their rosters' CRS performance across casual modes — useful for scouting and internal competition tracking. B2B SaaS tier.

### 19.6 Official Partnership

At meaningful scale, CRS becomes an attractive partner or acquisition target for Riot Games, third-party stat platforms (OP.GG, U.GG), or gaming analytics companies. The clean data architecture and engaged community are core assets.

---

*Document Version 2.0 — Prepared for stakeholder review. Subject to revision as implementation progresses and community feedback is incorporated.*

*All Riot Games data is used in accordance with Riot Games' Developer API Terms of Service. CRS is not endorsed or affiliated with Riot Games.*
