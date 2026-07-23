# ArenaRank — Casual Ranked System (CRS)

A third-party competitive rating ladder for **League of Legends Arena** (and
future casual modes). It ingests match data from the Riot API, computes a
gamified **Casual Rating (CR)** with a Plackett-Luce / TrueSkill-derived engine
plus an integrity (anti-abuse) layer, and serves leaderboards, player profiles,
champion stats and tournaments through a read API and a React UI.

> **Product spec of record:** [`casual_ranked_proposal.md`](./casual_ranked_proposal.md).
> Design specs live in [`docs/superpowers/specs/`](./docs/superpowers/specs/).

---

## Status (read this first)

This repo was built in **slices/waves**, and not every slice is wired end to
end. Be honest with yourself about what runs:

| Area | State |
|---|---|
| Read API (leaderboard / player / match / champions / search / tournaments) | ✅ Works; serves real backfilled data (some widgets are deliberate samples) |
| Rating + integrity engines (`backend/arena/rating`, `.../integrity`) | ✅ Pure, deterministic, used by the read path |
| **Match ingestion → processing → rating (arq workers)** | ⚠️ **Wiring repaired** (see `arena/services/match_pipeline.py`); needs Redis + a Riot key + an integration run to confirm in your env |
| Offline backfill/rerate (`backend/scripts/*`) | ✅ How the current dev data was produced |
| `packages/*` — `@crs/*` (TS rating engine + Prisma + Zod types) | ✅ **Enforced oracle / spec-of-record** ([ADR 0001](docs/decisions/0001-rating-engine-oracle.md)) — not deployed, but the parity gate makes the Python port conform |
| `infrastructure/*` (Helm / K8s / Terraform / observability) | ⚠️ Scaffolded; **not yet validated against the live FastAPI app** |
| Auth on `/admin/*` and tournament-admin endpoints | ❌ **None yet** — do not expose publicly |

See [`prompt.md`](./prompt.md) (session save-point) and
[`workaround.md`](./workaround.md) for environment gotchas.

---

## Repository layout (monorepo)

```
.
├─ backend/          Python 3.12 · FastAPI · the DEPLOYED runtime (package: arena)
│   ├─ arena/        api · services · db · rating · integrity · riot · ddragon · workers · core
│   ├─ alembic/      DB migrations (SQLAlchemy)
│   ├─ scripts/      backfill / rerate / sims / e2e fixtures (offline tools)
│   └─ tests/        pytest
├─ frontend/         React 18 · Vite 5 · TypeScript · the DEPLOYED UI
├─ packages/         TypeScript REFERENCE implementation (not deployed)
│   ├─ rating-engine/   @crs/rating-engine  — pure rating math, 100% test coverage (the "oracle")
│   ├─ database/        @crs/database       — Prisma schema + migrations
│   └─ shared-types/    @crs/shared-types   — Zod schemas + DTOs
├─ infrastructure/   Helm · K8s (Kustomize) · Terraform · observability + runbooks
├─ docs/             design specs + integration notes
├─ parity/           rating-engine parity harness (TS oracle ↔ Python runtime)
├─ docker-compose.yml   local stack (Postgres/Timescale · Redis · PgBouncer ×2 · api · worker · frontend)
└─ package.json      npm workspaces root
```

### Two implementations of the rating math — on purpose, but mind the gap

The rating algorithm exists **twice**: `packages/rating-engine` (TypeScript, the
**enforced oracle / spec-of-record** — see [ADR 0001](docs/decisions/0001-rating-engine-oracle.md))
and `backend/arena/rating` (Python, the deployed port). Likewise the schema exists
as both Prisma (`packages/database`) and SQLAlchemy/Alembic (`backend`). Production
doesn't *run* `packages/`, but it is **not** legacy: rating changes land in the TS
engine first, and the [`parity/`](./parity) gate fails CI if the Python port
diverges from it. See [Testing](#testing).

> ⚠️ Their **default params already differ** (the Python engine was recalibrated
> 2026-06-15 and adds a CR-space "PDL cap" layer the TS engine lacks). The parity
> gate compares the **base Plackett-Luce + CR identity** with modifiers
> neutralized; full-pipeline parity is an open reconciliation task.

---

## Prerequisites

- **Docker** + Docker Compose (easiest path), **or** for manual dev:
- **[uv](https://docs.astral.sh/uv/)** (manages Python + the backend venv from `uv.lock`) and **Node 20+**
- A **Riot API key** (only needed to ingest new matches; not needed to serve
  already-backfilled data) — set it in `backend/.env`.

---

## Quickstart (Docker, recommended)

```bash
# from the repo root
docker compose up --build
# in another shell, once Postgres is healthy:
docker compose run --rm api alembic upgrade head        # create the schema
docker compose run --rm api python -m arena.db.seed     # seed champions + a dev season
```

- API → http://localhost:8000  (`/docs` for OpenAPI)
- Frontend → http://localhost:5173
- Postgres `5432` · PgBouncer tx `6432` / session `6433` · Redis `6379`

> The frontend dev server proxies `/api` → `http://localhost:8000`, so no CORS
> config is needed locally.

---

## Manual local dev

All commands are **relative to the repo root** — no absolute paths (older notes
in `prompt.md`/`workaround.md` reference a different machine's `F:\` drive; ignore
those paths and use these).

### Backend

```bash
cd backend
# uv creates the venv + installs the locked, reproducible deps (uv.lock).
uv sync --extra dev                # add --extra otel to export traces

# point at your Postgres + Redis (see backend/.env.example):
export DATABASE_URL="postgresql+asyncpg://arena:arena@localhost:5432/arena"
export REDIS_URL="redis://localhost:6379/0"

uv run alembic upgrade head
uv run python -m arena.db.seed
uv run uvicorn arena.api.app:app --reload --port 8000
```

Workers (ingestion + processing) — requires Redis and a `RIOT_API_KEY`:

```bash
cd backend
uv run arq arena.workers.main.StandardWorker      # match processor
uv run arq arena.workers.main.IngestionWorker     # Riot poller (enqueues matches)
```

> After changing backend rating params/services, flush the leaderboard cache:
> `redis-cli FLUSHALL` (a uvicorn reload does **not** invalidate it).

### Frontend

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173 (set VITE_API_URL for a non-proxied API)
```

---

## Environment variables

| Var | Used by | Notes |
|---|---|---|
| `DATABASE_URL` | backend, alembic | asyncpg DSN. Migrations target the **direct** Postgres port, not PgBouncer. |
| `REDIS_URL` | backend, workers | cache · per-player locks · arq queues · Riot token bucket |
| `RIOT_API_KEY` | workers/ingestion | required only to ingest new matches |
| `CORS_ORIGINS` | api | comma-separated; defaults to the Vite origin |
| `VITE_API_URL` | frontend | empty in dev (uses the proxy); the real API URL in prod |

Backend templates: [`backend/.env.example`](./backend/.env.example) ·
Frontend: [`frontend/.env.example`](./frontend/.env.example). **Never commit real
secrets** (`.gitignore` keeps only `*.example`).

---

## Testing

```bash
# Backend (pytest)
cd backend && uv sync --extra dev && uv run pytest
#   ↳ the worker write-path has fast contract tests (tests/workers) + pure
#     normalization tests (tests/services); the DB-gated integration test runs
#     only when DATABASE_URL points at a migrated Postgres.

# Reference packages (Vitest)
npm install            # at repo root (workspaces)
npm test --workspaces --if-present

# Frontend
cd frontend && npm run lint && npm run typecheck && npm run build

# Rating-engine parity (TS oracle ↔ Python runtime)
node parity/compare.mjs    # see parity/README.md
```

---

## CI/CD

- [`.github/workflows/ci.yml`](./.github/workflows/ci.yml) — backend lint
  (ruff), type-check (mypy), import smoke, `alembic check`, Docker build.
- [`.github/workflows/quality.yml`](./.github/workflows/quality.yml) — backend
  fast tests (pytest), frontend build/lint/typecheck, `packages/*` tests, and the
  **rating-engine parity gate**.
- [`.github/workflows/release.yml`](./.github/workflows/release.yml) — build +
  push the backend image to ECR; deploy to staging (on `main`) / production (on
  `v*` tags) via Kustomize. *(Frontend deploy is not yet wired.)*

---

## Known gaps & conventions

- **No auth** on admin/tournament-admin mutations yet — gate before any public
  deploy.
- **Dual rating/schema implementations** (`packages/` vs `backend/`) can drift;
  the parity harness covers the engine core only.
- **Mixed language:** user-facing strings and many docs are **PT-BR**; code
  identifiers and internal docs are English.
- **Naming:** the product is variously "ArenaRank" / "CRS" / `@crs/*` / the
  `arena` Python package — same system.

## License

_TODO: add a `LICENSE`._
