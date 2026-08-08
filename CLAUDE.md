# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

ArenaRank / **CRS** (Casual Ranked System) — a third-party competitive rating ladder for **League of Legends Arena**. Ingests Riot match data, computes a gamified **Casual Rating (CR)** via a Plackett-Luce (OpenSkill/Weng-Lin) engine plus an integrity/anti-abuse layer, and serves leaderboards, profiles, champion stats and tournaments through a read API + React UI. The product is called variously "ArenaRank", "CRS", `@crs/*`, and the `arena` Python package — same system.

**Read `README.md` first** — it has an honest "what actually runs" status table. The product spec of record is `casual_ranked_proposal.md`; code comments reference it as "proposal §N.N". For a directory-by-directory deep dive into `backend/arena/` (including modules this file only summarizes — `ingest/`, `ddragon/`, `tournaments/`, payments — and the full `scripts/` inventory), see **`backend/CLAUDE.md`**. Frontend-specific conventions live in `frontend/AGENTS.md`.

## Common commands

Run from the repo root unless noted. Backend uses **uv** (not pip/poetry); frontend + admin-console use **npm**.

```bash
# ── Backend (Python 3.11+/3.12, FastAPI) ──  (cd backend)
uv sync --extra dev                             # install locked deps (+ --extra otel for tracing)
uv run uvicorn arena.api.app:app --reload --port 8000
uv run alembic upgrade head                     # migrate (targets DIRECT postgres, not PgBouncer)
uv run python -m arena.db.seed                  # seed champions + a dev season
uv run pytest                                   # all tests
uv run pytest tests/rating/test_engine.py       # one file
uv run pytest tests/rating -k dispersion        # one test by name
uv run ruff check . && uv run mypy arena        # lint + typecheck (mypy strict; scope to
                                                 # `arena`, matching CI — `mypy .` also walks
                                                 # `tests/`, which hits an unrelated module-path
                                                 # collision between arena/ingest and tests/ingest)

# arq worker pools (need Redis; ingestion needs RIOT_API_KEY):
uv run arq arena.workers.main.StandardWorker    # match processor (see worker classes below)

# ── Frontend (React 18 / Vite 5 / TS) ──  (cd frontend)
npm install && npm run dev                      # http://localhost:5173 (proxies /api -> :8000)
npm run lint && npm run typecheck && npm run build
npm run test                                    # vitest

# ── Admin console (separate operator UI) ──  (cd admin-console)
npm install && npm run dev                      # http://localhost:5174

# ── Reference packages (TS oracle) ──  (repo root)
npm install                                     # workspaces: packages/*
npm test --workspaces --if-present

# ── Rating-engine parity gate (TS oracle ↔ Python runtime) ──
node parity/compare.mjs                          # exits non-zero on divergence; PARITY_TOL=1e-9 to tighten

# ── Docker (full local stack) ──
docker compose up --build
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m arena.db.seed
```

> After changing backend rating params/services, **flush the leaderboard cache**: `redis-cli FLUSHALL`. A uvicorn reload does **not** invalidate it.

## Architecture

### Monorepo layout
- `backend/arena/` — the **deployed** Python runtime (FastAPI). Package name is `arena`.
- `frontend/` — the **deployed** player React UI (port 5173).
- `admin-console/` — a **separate** operator React UI (port 5174), noindex, switches target backend at runtime.
- `packages/` — TypeScript **reference** implementation. NOT deployed, but NOT legacy (see dual-engine note).
- `parity/` — harness that fails CI if the Python engine diverges from the TS oracle.
- `infrastructure/` — Helm/K8s/Terraform, scaffolded, not yet validated against the live app.

### Two implementations of the rating math — on purpose
The rating algorithm exists **twice**: `packages/rating-engine` (TypeScript, the **enforced oracle / spec-of-record**, ADR 0001) and `backend/arena/rating` (Python, the deployed port). The schema likewise exists as both Prisma (`packages/database`) and SQLAlchemy/Alembic (`backend`). **Rating logic changes land in the TS engine first**; the `parity/` gate then enforces the Python port. Caveat: their **default params already differ** and the Python engine adds a CR-space "PDL cap" layer (`arena/rating/caps.py`) the TS engine lacks — the parity gate only compares the base Plackett-Luce + CR identity with modifiers neutralized. Full-pipeline parity is an open task.

### The write path (match → rating), a layered seam
This is the most important cross-file flow. It was rebuilt in "waves" and the seams matter:

1. **Workers** (`arena/workers/`) discover/enqueue match ids and call `process_match(riot_match_id, payload, *, redis)`.
2. `arena/services/match_pipeline.py` — `WorkerRatingService` is the **adapter** bridging the worker's `(riot_match_id, payload)` contract to the real service. It parses the Arena payload (`arena/riot/arena.py`), registers players (one `INSERT ... ON CONFLICT` for the whole lobby), resolves the active season, and builds a normalized `RawMatch`.
3. `arena/services/rating_service.py` — `RatingService.process_match` orchestrates one match end to end: idempotency guard → integrity eval → load player state → pure `arena.rating.rate()` → **persist everything in ONE transaction under per-player Redis locks**.
4. `arena/rating/engine.py` — `rate(MatchInput) -> RatingResult` is **pure and deterministic** (no DB, no I/O). Never add side effects here.

Key invariants in that path:
- **Idempotency** is anchored on `matches.processed` (durable) + a Redis `processed` flag (fast path). The internal `matches.id` is a **deterministic UUIDv5** of the Riot match id (`deterministic_match_id`) so re-ingesting maps to the same row.
- **CR identity** holds exactly: `cr = (mu - 3*sigma)*scale + offset`. The PDL cap layer clamps displayed `cr_delta` then **back-solves `mu_after`** to preserve the identity. If you touch caps/floors, re-derive `mu_after`.
- `register_players` emits rows **sorted by puuid** to give every transaction the same lock-acquisition order (deadlock avoidance) — don't reorder.

### Worker pools (arq, one `WorkerSettings` class each in `arena/workers/main.py`)
Each is a separate `docker compose` service and scales independently. **Each cron pool has its own arq `queue_name`** — a shared queue makes a worker pick up jobs whose function it lacks (this was a real bug; see the top commit).
- `StandardWorker` / `PriorityWorker` — continuous consumers (no cron, no idle window between batches) of the `arena:standard` / `arena:priority` arq queues (`process_match`). Priority = a Top-1000 player is involved (sub-5-min SLA).
- `IngestionWorker` — Riot poller (cron), enqueues new match ids (k8s/Helm topology only — not run in any docker-compose stack today).
- `SweepWorker` / `PrioritySweepWorker` — rotating sweeps over tracked / Top-N players → enqueue `process_match` jobs straight onto `arena:standard` / `arena:priority` via `enqueue_job` (same pattern as `IngestionWorker`). No separate pending-list/drain stage. `SweepWorker`'s full-pool rotation (`sweep_batch_size` tracked players per tick) scales with the tracked-player count — at 270k+ tracked players this is a multi-day rotation per non-priority player, way past `rearm_tick`'s ~26min re-poll leash, which used to silently lose mid-session matches for anyone not in the Top-N. `PrioritySweepWorker` also hosts `recent_activity_sweep_tick` (2026-08): a CR-independent "finished a match in the last `recent_activity_window_seconds`" re-check (`player_seasons.updated_at`) that closes that gap without diluting the Top-N rotation itself.
- `SchedulerWorker` — maintenance cron (season transitions, leaderboard refresh maintaining `TOP_PLAYERS_SET`, cache warm, cr-snapshots).

`arena/workers/queues.py` is the **single source of truth** for all queue names, Redis keys, and the match-eligibility filter (queue id / participant count 16–18 / duration 120s–1h). Producers and consumers both import from it — never hardcode a queue name or Redis key elsewhere. Sweep workers are pausable at runtime via the `arena:worker:enabled:<name>` Redis flag (admin API); `StandardWorker`/`PriorityWorker` are not (arq has no native consumer-level pause — see the git history around the bulk-processor→continuous-consumer migration for why a job-level `Retry`-based pause was rejected).

### Read API (`arena/api/`)
`create_app()` in `arena/api/app.py` is the factory; all routes mount under `/api/v1`. Routers are included **defensively** (each in its own try/except) so the app still boots if an optional router's deps are absent. `arena/services/*_service.py` back the routers (leaderboard, stats, season). Leaderboard results are Redis-cached.

### Datastores & connection pooling (Trinity finding #9)
Postgres is **TimescaleDB** (pg16) — `cr_snapshots` is a hypertable. Two PgBouncer pools front it: **transaction** mode (6432) for the web/API tier, **session** mode (6433) for workers (they hold advisory locks / prepared state). `arena/db/session.py` sets `statement_cache_size=0` for tx-pool compatibility. **Alembic migrations target the DIRECT postgres port (5432)** — DDL + Timescale policy statements are not tx-pool safe. Redis backs cache, per-player locks, arq queues, and the Riot token bucket.

### Admin auth (note: README's "no auth" line is stale)
`arena/api/security.py` — `require_admin` gates the entire `/admin/*` + tournament-admin surface with a shared key (`ADMIN_API_KEY` env → `X-Admin-Key` header or `Bearer` token, constant-time compare). **Fail-closed**: if no key is configured every admin request gets 503. There is still no per-user identity/RBAC — that's a later slice; the `Depends(require_admin)` seam stays when it lands.

## Conventions
- **Language split**: all **user-facing strings** (error messages, UI copy) are **PT-BR**; code identifiers, internal docstrings, and log event names are English. JSON envelope keys are **camelCase** (`detail`, `requestId`, `traceId`).
- **Structured logging**: use `arena.core.logging.get_logger("arena.x")` and emit event-name + kwargs (`_log.info("http.request", method=..., status=...)`), not f-strings.
- **Config**: everything runtime-configurable lives in `arena/core/config.py` (`Settings`, pydantic-settings, env-driven). Add new knobs there; don't read `os.environ` directly.
- **Rating engine purity**: `arena/rating/` and `arena/integrity/` are pure/deterministic and used by the read path too. Keep DB/IO out of them.
- **Frontend API client**: all read-API calls go through `frontend/src/lib/api.ts` (typed against `lib/types.ts`); it prefixes `/api/v1` and attaches `X-Admin-Key` for `/admin` paths. Routes are lazy-loaded in `App.tsx`.
- **Offline tooling**: `backend/scripts/` (backfill, rerate, sims, e2e fixtures) is how the current dev data was produced and is the reference for the online write path.

## Design Context (frontend)

The player app (`frontend/`) has captured design context for the Impeccable design workflow:
- `frontend/PRODUCT.md` — register **product**, platform **web**. Users: jogadores competitivos de Arena (BR). Positioning: "o hub social do Arena" (ranking + campeonatos + perfis como rede da comunidade competitiva), com o CR legítimo como espinha dorsal.
- Strategic principles: legitimidade primeiro · hub não só ladder · densidade com autoridade · premium do universo do jogo (usado nos momentos, não pulverizado) · rápido e confiável.
- Anti-references: SaaS genérico/dashboard corporate, stats poluído/ad-heavy, cartoon/infantil, cripto/neon. Brand feel: competitivo, premium, legítimo (mira FACEIT/esports + acabamento Mobalytics/Blitz).
- `frontend/DESIGN.md` captures the visual system (dark theme, azul `#2f9bd6` interativo + ouro `#d9b25f` rating, Plus Jakarta Sans + Anton). Live mode configured at `frontend/.impeccable/live/config.json`.

## CI gates (must pass)
- `.github/workflows/ci.yml`: ruff, mypy (strict), import smoke, `alembic check`, Docker build.
- `.github/workflows/quality.yml`: pytest (fast), frontend build/lint/typecheck, `packages/*` tests, and the **rating-engine parity gate**.
