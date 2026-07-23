# arenarank-realoficial — FastAPI Backend Master Plan

> **Direction (locked, Clesio 2026-06-14):** implement the **proposal's gamified design** (`casual_ranked_proposal.md`) as a **new FastAPI/Python backend** in `arenarank-realoficial`, serving the **existing `frontend/`** (React+Vite). Slices 1-2 (TS rating-engine + Prisma) are **spec reference to port**, not final code.
> Supersedes the NestJS/TS stack. Not the target: `F:\arenarank`'s austere `formula_ranking_v1` (μ-pure). See memory `backend-direction-fastapi-pivot`.

## 1. What carries over vs is set aside

| From | Status |
|---|---|
| Rating math (Weng-Lin Plackett-Luce, oracle-validated) + modifier pipeline + CR=(μ−3σ)·scale+offset + soft-reset + Trinity hardening (C1/C2/M3/I1, DEC-A/DEC-B) | **PORT TS→Python** (logic + the slice-1 spec `2026-06-14-rating-engine-design.md` are the source) |
| Prisma schema (§8 + achievements + Timescale + leaderboard MV) | **PORT → SQLAlchemy 2.0 + Alembic**, applying Trinity schema findings |
| shared-types (Zod/DTOs) | Re-expressed as **Pydantic models** matching `api_contract_v1` |
| Trinity schema-at-scale findings (5 irreversibles + MV/pooler/GIN) | **APPLY** to the SQLAlchemy schema/migrations |
| TS packages (slices 1-2 code) | **reference only** (kept in repo, not deployed) |

## 2. API surface = the existing frontend contract

Serve `frontend/src/lib/types.ts` ↔ `F:\arenarank\spec\api_contract_v1.md` 1:1. FastAPI, base `http://localhost:8000`, prefix `/api/v1`, camelCase JSON, CORS allow Vite (`5173`). Endpoints: `GET /leaderboard`, `GET /player/{riotId}`, `GET /match/{matchId}`, `GET /champions`, `GET /tournaments`, `GET /tournament/{id}`, `POST /admin/tournaments` (+5 onboarding/admin tournament endpoints), `GET /admin/overview`, `GET /meta/last-update`. RFC-style `404 {detail}` / `422`.

- **CR field** = our gamified `toCR(μ,σ)` from the proposal design (μ0=1000, (μ−3σ)·scale+offset → ~200–1840 range). Overrides the contract's `round(mu*200)` suggestion (`cr` is display-only). Rank by CR within format.
- **`modifiers` breakdown** (contract has colocação/sequência/proteção/penalidade) = our `AppliedModifiers` mapped to `{kind,label,value,icon}`.
- Subsystems the contract marks "DTO sample" (champion tierlist, admin overview) → representative DTOs now, backed by real tables later.
- **Tournaments** = first-class persisted (read `F:\arenarank\spec\tournament_onboarding_scoring_v1.md` when building; `compute_standings` is scoring source of truth).
- **Riot ToS:** never expose augment/item winrate (pick rate OK); no μ/σ or raw formulas in API-for-UI (use CR/Pontos/PDL); champion art = placeholder gradients only.

## 3. Python project structure

```
backend/
  pyproject.toml (uv/poetry) · fastapi · uvicorn · sqlalchemy[asyncio] · alembic · asyncpg
                · pydantic v2 · httpx · redis · arq (workers) · openskill (rating oracle)
  arena/
    rating/        # PORT of slice-1: plackett_luce.py, modifiers/, cr.py, season.py, rate.py, params.py
    integrity/     # RDS, flag evaluators (proposal §3.2)
    riot/          # httpx client + redis token-bucket (Lua) + retry + circuit breaker + coalesce + cache
    db/            # SQLAlchemy models (Trinity-partitioned) + Alembic migrations + session
    schemas/       # Pydantic models == api_contract_v1 DTOs
    services/      # rating_service, stats_service, season_service, leaderboard_service, tournament_service, integrity_service
    api/           # FastAPI app: routers per contract section + deps + CORS + error handlers
    admin/         # admin router (overview, tournament provisioning, DLQ, integrity queue)
    workers/       # ingestion (poll Riot), processor (match pipeline §13), scheduler (cron: season, MV refresh, cache warm)
    core/          # config (pydantic-settings), logging (structured JSON), telemetry (OTel)
  tests/           # pytest — MINIMAL per cadence; full suite deferred to final phase
  Dockerfile · alembic.ini
```

Workers via **arq + Redis** (async, lightweight) for ingestion/processor; APScheduler or arq cron for scheduler. Match-processing pipeline per proposal §13.2 (PL → modifiers → sequential per-player write under Redis lock → match_participants + champion_stats + cr_snapshot + integrity_events in one tx).

## 4. Schema (SQLAlchemy + Alembic) — Trinity findings applied

Port the slice-2 Prisma models to SQLAlchemy, with the **5 irreversibles** baked into the initial migration (declarative partitioning via raw DDL in Alembic, since SQLAlchemy lacks native partition DDL):
1. `matches` `PARTITION BY LIST(season_id)` sub-partition `RANGE(played_at)` monthly.
2. `match_participants` `PARTITION BY HASH(player_id, 16)` + denormalized `played_at` + `INDEX(player_id, played_at DESC)`; Prisma-middleware-equivalent: enforce `played_at` predicate in repository queries.
3. `integrity_events` `PARTITION BY RANGE(created_at)` monthly + partial open-queue index.
4. `cr_snapshots` PK `(snapshot_at, player_id, season_id)`, hypertable interval at creation.
5. `players` `shadowbanned/banned/restricted` as real `bool` columns + partial indexes; keep `moderation_flags` jsonb for long tail.
Plus (reversible, do before traffic): replace `leaderboard_mv` 30s refresh with `pg_ivm` (or Top-1000 trigger + Redis read-through); event-driven `cr_snapshots` + continuous aggregate + compression; autovacuum tuning + fillfactor 85 on `player_seasons`; PgBouncer dual-pool (tx 6432 web / session 6433 workers); GIN(jsonb_path_ops) on integrity_flags/metadata/modifiers; generated `winrate` column on champion_stats. Add `tournaments` tables (migration per contract §5).

## 5. Build waves (no per-slice test gate; final test phase at end)

| Wave | Content | Dep |
|---|---|---|
| **W1 Foundation** | Python scaffold (pyproject, FastAPI app, config, Docker) + **port rating-engine** + **SQLAlchemy schema/Alembic** (Trinity-partitioned) + Pydantic schemas | — |
| **W2 Core libs/workers** | riot-client (httpx) · integrity · processor/ingestion/scheduler workers (pipeline §13) | W1 |
| **W3 Read+Admin API** | FastAPI routers serving all `api_contract_v1` read endpoints + admin overview/DLQ/integrity | W1 |
| **W4 Tournaments** | tournaments subsystem (persisted; onboarding + scoring `compute_standings`) per contract §5 + `tournament_onboarding_scoring_v1` | W1 |
| **W5 Wire + Infra** | point frontend `VITE_API_URL`/CORS; Docker/compose (api+workers+pg/timescale+redis+pgbouncer); CI/CD; observability (Prom/Grafana/Loki/Tempo); deploy | W2-4 |
| **Final** | E2E wiring + **single final test pass** + hardening | all |

## 6. Constraints / notes

- Cadence: minimal sanity (ruff/mypy, alembic check) per build; comprehensive tests deferred to Final.
- Session limit hit 2026-06-14 → workflow agents resume 18:50 BRT; W1 launches then.
- `F:\arenarank\backend` (existing FastAPI) is a **reference template** for structure (it already serves this contract) — consult, don't copy wholesale (fresh build per directive).
