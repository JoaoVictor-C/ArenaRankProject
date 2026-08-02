# CLAUDE.md — backend/

This is the deep-dive companion to the root `CLAUDE.md` (read that first — it
covers the write path, worker pools, datastores, and conventions that apply
here). This file is a navigational map of `backend/arena/` plus the pieces the
root doc doesn't cover: `arena/ingest`, `arena/ddragon`, `arena/tournaments`,
payments, and the `scripts/` inventory.

## Directory map (`arena/`)

| Dir | What it is |
|---|---|
| `api/` | FastAPI app factory (`app.py`) + routers, each mounted defensively (own try/except so one optional router's missing deps never break the boot). `api/routers/_common.py` holds shared response helpers. |
| `services/` | The orchestration layer between routers/workers and the pure engines — `rating_service.py` (the write-path transaction, see root doc), `season_service.py`, `leaderboard_service.py`, `stats_service.py`, `match_pipeline.py` (`WorkerRatingService` adapter), `locks.py` (per-player Redis locks), `protocols.py` (the `RawMatch`/typed-dict contracts pure code depends on without importing the DB layer), `build_ref_service.py` (provisional champion build-reference reads), `replication_status.py` (EC2 replica-lag probe for `/healthz`), `infinitepay.py` (payments client, see below). |
| `workers/` | arq worker pools — see root doc's "Worker pools" section for the full picture. `queues.py` is the single source of truth for queue names/Redis keys/eligibility filters. `deps.py` wires the Riot client + rating service singletons workers pull from. |
| `rating/` | Pure, deterministic engine (`engine.py::rate()`), modifiers (`modifiers.py`), the CR-space PDL cap layer (`caps.py` — Python-only, not in the TS oracle), params (`params.py::DEFAULT_PARAMS`), and shared types (`types.py`). No DB/IO — see root doc's "Rating engine purity" rule. |
| `integrity/` | Pure anti-abuse evaluation. `service.py::evaluate()` is the sync entry point (RDS, eligibility, duration, dispersion checks); `evaluate_async` adds the one I/O-bound signal (repeated-lobby via a Redis fingerprint store, `fingerprint.py`). `evaluators.py` holds the individual flag checks, `params.py` their thresholds. |
| `riot/` | The resilient Riot API client stack: `client.py` (`RiotClient`, the public entry point) → `rate_limit.py` (Redis Lua token buckets) → `circuit_breaker.py` (trips after 5 failures/10s, 30s cooldown — see the retry/DLQ interaction note below) → `retry.py` (backoff + jitter, honors `Retry-After`) → httpx. Plus `coalesce.py` (dedup identical in-flight match fetches), `cache.py` (24h Redis cache + optional S3 overflow), `arena.py` (match-v5 payload parsing), `routing.py` (region/platform hosts), `errors.py` (typed exception hierarchy), `limit_headers.py` (parses Riot's `X-*-Rate-Limit*` response headers as ground truth vs. our modeled buckets), `factory.py` (`get_client()` singleton). |
| `ingest/` | A lower-level match-discovery toolkit (`crawler.py`, `engine.py`, `registry.py`, `replay.py`) that `services/match_pipeline.py` and `scripts/backfill.py` build on. Distinct from `workers/ingestion.py` (the arq-facing queue producer / pressure-mode logic) — `ingest/` is the reusable discovery mechanics, `workers/ingestion.py` is one arq-facing consumer of it. Has its own test suite (`tests/ingest/`). |
| `ddragon/` | Data Dragon (Riot's official, ToS-compliant, key-less static CDN) client — champion names + champion/summoner icon URLs, so the frontend can show real icons instead of gradient placeholders. `cache.py` handles the version/champion-map cache. |
| `tournaments/` | The Campeonatos subsystem: `service.py` (`TournamentService` — list/get_detail/create/join/set_match_link/submit_result), `scoring.py` (pure standings computation), `provision.py` (admin creation helpers), `router.py` (public + admin routes). Reads return an honest empty list / 404 when nothing is provisioned — tournaments are operator-created and must never be presented as a sample/fake event (an earlier `sample.py` DTO-fallback module was removed as dead code; don't reintroduce that pattern here). |
| `schemas/` | Pydantic DTOs (`ArenaModel` base in `common.py` — camelCase aliases, PT-BR error strings). One file per API surface: `admin.py`, `champions.py`, `leaderboard.py`, `match.py`, `meta.py`, `player.py`, `tournaments.py`. This is the wire contract — keep in rough sync with `packages/shared-types`' DTOs conceptually, but nothing generates one from the other. |
| `db/` | `models.py` (SQLAlchemy models — the deployed schema, mirrors `packages/database`'s Prisma schema by hand, no generator), `session.py` (engine/session factory, PgBouncer tx-pool settings), `base.py`, `seed.py` (dev seed: champions + a dev season). |
| `core/` | `config.py` (`Settings`, pydantic-settings — every runtime knob lives here, never read `os.environ` directly elsewhere), `logging.py` (structured event-name logger), `metrics.py` (the admin console's over-time counters — `record`/`record_many` against Redis), `telemetry.py` (optional OTel wiring, `--extra otel`). |

## Payments (InfinitePay) — partial, by design

`api/routers/payments.py` + `services/infinitepay.py` are **Fatia 1** (slice 1)
of a paid tournament-entry design: a real, admin-gated InfinitePay Checkout
Links client that proves the integration live (creates a real handle-only
charge; nothing is charged unless the payer completes the hosted PIX page).
**Fatia 2** — the `tournament_payments` table and the webhook that would mark
an entry as paid — does not exist yet. `TournamentCreate`'s `entry_fee`/
`pix_info` fields are accepted by the schema but silently dropped by
`TournamentService` (never referenced in the scoring blob) — this is
intentional (not a bug to "fix" by wiring it up ad hoc), but it means any UI
that collects those fields today is building something that doesn't persist.
The original design doc this docstring used to point at is not in this repo;
treat `infinitepay.py` + `payments.py` as the source of truth for current
scope instead of chasing that reference.

## Riot client resilience stack — a retry/circuit-breaker subtlety

`riot/circuit_breaker.py` only counts **transport-level exceptions**
(`httpx.TransportError` — timeouts, connection refused, DNS failures) as
trip-worthy failures; a 429 or 5xx HTTP *response* is not an exception, so it
does not trip the breaker on its own (it's already handled by the token
bucket + `retry.py`'s backoff). When the breaker *does* trip, `CircuitOpenError`
carries its own `retry_after` (how long until the cooldown ends); a bare
`process_match` retry using the generic fixed backoff table
(`workers/processor.py::_RETRY_BACKOFF`, ~0–5s) would exhaust `MAX_TRIES`
inside the *same* 30s open window and dead-letter a match for no real reason
— `processor.py::_retry_after_hint` special-cases `CircuitOpenError`/
`RiotRateLimitError` to defer by their own `retry_after` instead, capped at 60s.
Keep that in mind if you touch the retry classification logic: a fixed backoff
schedule is fine for ordinary transient errors, but not for an error that
already tells you how long to wait.

## Scripts (`backend/scripts/`) — offline tools

All read the same DB the online write path uses; run with `uv run python -m scripts.<name>` from `backend/`.

| Script | Purpose |
|---|---|
| `backfill.py` | Unified Arena backfill CLI (`--mode refresh`\|`bootstrap`) — the reference implementation the online write path's ingestion logic mirrors. |
| `rerate_matches.py` | Replay every stored match through the *current* rating engine, in chronological order — how you repair historical ratings after a params/engine change. |
| `backfill_participant_telemetry.py` | One-time: re-fetch already-ingested matches from Riot to fill `match_participants.augments`/`.items` + combat telemetry (kills/deaths/assists/damage/gold/level and a few extras) — NULL on anything ingested before native capture landed. Idempotent/resumable — safe to kill and re-run. |
| `audit_missing_matches.py` | Read-only: diff Riot's known match ids per tracked player against what's in the DB. |
| `sweep_profile_icons.py` | Backfill `players.profile_icon_id` from already-stored match payloads (the field isn't on `match_participants`). |
| `sync_season_config.py` | Mirror the active season's `config` JSONB display column onto the current `DEFAULT_PARAMS` (the engine always reads params from code, not the DB — this keeps the DB's *display* copy honest after a recalibration). |
| `sim_params.py` / `sim_caps.py` | Non-destructive what-if simulators — replay stored matches in memory under candidate param/cap curves, no DB writes. |
| `diag_gates.py` / `diag_inflation.py` | Non-destructive diagnostics from the 2026-06-15 rating recalibration (see `docs/rating_recalibration_2026-06-15.md` and `docs/trinity/`) — empirical gates and CR-inflation decomposition. Historical-debugging tools, not part of any regular workflow. |
| `e2e_process_fixture.py` | Drive one real Arena match-v5 fixture through the full write path as a smoke test. |
| `sweep_profile_icons.py`, `replication/` | See above / EC2 replica-lag tooling companion to `services/replication_status.py`. |

## Design-history docs (`backend/docs/`)

`rating_recalibration_2026-06-15.md` plus `docs/trinity/*.md` (four escalation
briefs) document *why* the current rating params/caps look the way they do —
read them before changing `rating/params.py` or `rating/caps.py` if you want
the reasoning, not just the current numbers.

## Testing conventions specific to this package

- `tests/workers/conftest.py::FakeRedis` — a hand-rolled async Redis fake (no
  `fakeredis` dependency) implementing exactly the ops the workers use. Add a
  method here (mirroring real Redis semantics) rather than reaching for a
  heavier mock if a test needs an op it doesn't have yet.
- `tests/ingest/`, `tests/workers/`, `tests/services/`, `tests/riot/`,
  `tests/api/` roughly mirror `arena/`'s own layout.
- The rating/integrity engines are pure — their tests never touch DB/Redis.
  Everything else that does is either unit-tested against a fake, or gated
  behind a real `DATABASE_URL` (see root `README.md`'s Testing section).
