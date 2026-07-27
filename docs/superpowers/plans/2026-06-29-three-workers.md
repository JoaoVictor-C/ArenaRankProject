# Three Workers Implementation Plan

> **Superseded — do not implement as written.** This plan's `BulkProcessorWorker`
> (cron-tick batch drain of `arena:sweep:pending:priority`/`:standard` Redis
> lists) shipped, then was later **retired** in favor of continuous arq
> consumers (`StandardWorker`/`PriorityWorker` draining `arena:standard`/
> `arena:priority` directly, no cron tick, no idle window — see root
> `CLAUDE.md`'s worker-pool section). The `SEEN_MATCHES_SET`/`SWEEP_CURSOR_KEY`
> Redis keys this doc's dedup relies on were also removed as dead code. Kept
> as a historical record of the earlier architecture, not a build guide.

> Execute task-by-task (subagent-driven). Steps use checkbox tracking.

**Goal:** Add 3 independently start/stoppable, Docker-compatible workers: (1) **Sweep** — discover new matches every X min across ALL players (standard lane); (2) **Priority Sweep** — every X min for Top-1000 ∪ admin-selected players (priority lane, processed first); (3) **Bulk Processor** — every few min, drain pending matches priority-first and process in bulk via the existing `process_match`.

**Architecture (Option A):** Sweep workers push discovered match-ids onto two Redis lists (`arena:sweep:pending:priority` / `:standard`). BulkProcessorWorker's cron drains priority-first (`RPOP COUNT`) and calls the proven `process_match(fake_ctx, mid)`. Zero change to the rating pipeline; clean "bulk every N min" semantics. New pipeline shares only `SEEN_MATCHES_SET` dedup with the legacy `poll_riot`→consumers path (left intact, backward-compatible).

## Global Constraints
- Branch `feat/three-workers`. Modules start `from __future__ import annotations`.
- **Test runner** (venv interpreter broken; site-packages intact): from `backend/`, `PYTHONPATH="<backend>;<backend>/.venv/Lib/site-packages"`, run `C:/Users/João/AppData/Local/Programs/Python/Python312/python.exe -m pytest …`. pytest 9.1.1, asyncio_mode=auto.
- **No fakeredis available** (no package network). Build a minimal hand-rolled async fake redis in `backend/tests/workers/conftest.py` (Task 3) supporting exactly: `get`, `set(nx=,ex=)`, `delete`, `exists`, `lpush`, `rpop(count=)`, `zadd`, `zrange`, `sadd`, `scard`, `zcard`, `sismember`, `hincrby`, `hdel`, `expire`. Bytes return values like redis-py. Later worker tasks reuse it.
- DB-gated tests opt in via `pytest.mark.skipif(not os.getenv("DATABASE_URL"))`; live PG at `postgresql+asyncpg://arena:arena@localhost:5432/arena`, Redis at `redis://localhost:6379/0`.
- **Resilience invariant (critical):** every cron tick (`sweep_tick`, `priority_sweep_tick`, `bulk_process_tick`) wraps its whole body in `try/except Exception` and RETURNS a dict (never raises) — arq does NOT catch cron exceptions, so an uncaught Redis `BusyLoadingError`/`ConnectionResetError` would kill the worker. This is the exact failure that just killed the backfill.
- Reuse existing: `_dedup_new` (ingestion.py), `_update_pressure_mode` (ingestion.py), `process_match`/`MAX_TRIES` (processor.py), `get_riot_client` (deps.py), admin `_runtime()`/`_close_redis`/`require_admin`.
- Keep legacy `IngestionWorker`/`StandardWorker`/`PriorityWorker` unchanged; the existing `worker` compose service stays.

## Design specifics (binding)
- **Enable flag:** key `arena:worker:enabled:{name}` — value `b"0"` = paused; absent/other = enabled. Checked at top of each tick.
- **Tick lock:** `arena:lock:worker:tick:{name}` via `SET NX EX (interval*60-5, min 10)`. Skip tick if held.
- **Sweep cursor:** `arena:sweep:cursor` (int DB OFFSET). Page `LIMIT batch OFFSET cursor` over `SELECT DISTINCT p.puuid FROM players p JOIN player_seasons ps ON ps.player_id=p.id WHERE ps.matches_played>0 ORDER BY p.puuid`. Advance by batch; reset to 0 when fewer than batch returned. Refresh latency = ceil(N/batch)*interval.
- **Priority seeds:** `ZRANGE arena:top_players 0 -1` ∪ `SELECT puuid FROM players WHERE is_selected=true`, deduped; paginate via `arena:priority_sweep:cursor`.
- **Bulk drain:** `RPOP arena:sweep:pending:priority COUNT batch`; fill remainder from `:standard`. Per mid: `HINCRBY arena:sweep:attempts mid 1` → job_try; call `process_match({"redis":redis,"job_try":job_try}, mid)`; on success `HDEL`; on `arq.worker.Retry` (job_try<MAX_TRIES) `LPUSH :standard mid` (requeue); bounded by `asyncio.Semaphore(bulk_concurrency)`.
- **Config (Settings, env-driven):** `sweep_interval_minutes=5`, `priority_sweep_interval_minutes=5`, `bulk_processor_interval_minutes=2`, `sweep_batch_size=100`, `priority_sweep_batch_size=200`, `sweep_matches_per_player=10`, `bulk_batch_size=50`, `bulk_concurrency=10`. Interval values must divide 60.
- **arq cron:** `cron(fn, minute=set(range(0,60,interval)), run_at_startup=True)`.

## Tasks
- [ ] **Task 1 — queues.py constants + helpers + config fields.** Append to `queues.py`: `SWEEP_PENDING_PRIORITY/STANDARD`, `SWEEP_CURSOR_KEY`, `PRIORITY_SWEEP_CURSOR_KEY`, `SWEEP_ATTEMPTS_KEY`, `_WORKER_ENABLED_PREFIX`, `_WORKER_TICK_LOCK_PREFIX`, and fns `worker_enabled_key`, `worker_tick_lock_key`, `sweep_pending_key` (+ `__all__`). Add the 8 Settings fields to `config.py`. Deliverable: import works, `settings.sweep_batch_size==100`; small unit test asserts the key helpers' format.
- [ ] **Task 2 — migration + ORM `is_selected`.** Create `alembic/versions/0003_player_is_selected.py` (down_revision `0002_profile_icon`): add `players.is_selected BOOLEAN NOT NULL DEFAULT false` + partial index `ix_players_is_selected_true … WHERE is_selected=true`. Add the mapped column + Index to `models.py` Player. Deliverable (DB-gated): `alembic upgrade head` then `downgrade -1` round-trips; `hasattr(Player,'is_selected')`.
- [ ] **Task 3 — sweep.py standard sweep + the FakeRedis test helper.** Create `backend/tests/workers/conftest.py` hand-rolled async `FakeRedis` (ops listed above). Create `sweep.py` with `sweep_tick`, `_check_enabled`, `_acquire_tick_lock`, `_tracked_puuids_page`, `_fetch_and_enqueue` (reusing `_dedup_new`,`_update_pressure_mode`). Deliverable: unit test with FakeRedis + mock client (list_match_ids→3 ids): `sweep_tick` pushes 3 to `:standard`, advances cursor; second call while locked → `skip_locked`; enabled flag `"0"` → `paused`.
- [ ] **Task 4 — priority sweep.** Add `priority_sweep_tick`, `_priority_seeds`, `_selected_puuids` to `sweep.py`. Deliverable: FakeRedis with `TOP_PLAYERS_SET` ZSET + one is_selected player (mock `_selected_puuids`): pushes to `:priority`; union dedup (member in both appears once); cursor resets at end.
- [ ] **Task 5 — bulk_processor.py.** Create with `bulk_process_tick`, `_drain_pending`, `_process_one` (import `process_match`,`MAX_TRIES` from processor; `Retry` from `arq.worker`). Deliverable: FakeRedis, mock `process_match`: priority(5)+standard(10), batch 8 → drains 5 priority + 3 standard in order; success path `HDEL`s attempts; `Retry` path requeues to standard; lock prevents double-tick; enabled `"0"` → paused.
- [ ] **Task 6 — main.py WorkerSettings.** Add imports + `SweepWorker`/`PrioritySweepWorker`/`BulkProcessorWorker` (cron per config) + `__all__`. Deliverable: import the 3 classes; each has 1 cron_job; `arq arena.workers.main.SweepWorker --help` exits 0.
- [ ] **Task 7 — admin pause/resume endpoints.** Append `WorkerControlResult` + `POST /workers/{name}/pause` (set enabled `"0"`), `/resume` (del). Valid names {sweep,priority_sweep,bulk_processor}, else 404; require X-Admin-Key. Deliverable: TestClient + monkeypatched `_runtime` redis: pause→200 sets key, resume→200 deletes, bogus→404, no key→401.
- [ ] **Task 8 — admin player select.** Append `PlayerSelectRequest/Result` + `PATCH /players/{player_id}/select` updating `players.is_selected`. Deliverable: 200 updates row, missing→404, require admin. (DB-gated or mock sessionmaker.)
- [ ] **Task 9 — docker-compose services.** Add `worker-sweep`, `worker-priority-sweep`, `worker-bulk-processor` (copy `worker` block; differ in `command`+`SERVICE_NAME`+interval envs). Deliverable: `docker compose config --quiet` passes.
- [ ] **Task 10 — resilience test.** Test: monkeypatch a tick's `redis.get`/first redis op to raise `redis.exceptions.BusyLoadingError` (and `ConnectionResetError`); assert each tick returns `{"status":"error",…}` (no raise). Confirms a Redis blip can't kill the worker.
- [ ] **Task 11 — e2e integration (fakeredis-style).** `sweep_tick` (3 matches) → `:standard` has 3 → `bulk_process_tick` drains → mock `process_match` called 3× with right ids; priority lane drained first; attempts hash clean after success.

## Verification
- Per task: the listed unit test green via the wrapper; ruff clean on new files.
- Final: `pytest tests/workers tests/ingest -q` green; `docker compose config --quiet`; resilience test proves no-crash-on-Redis-error. Optional live smoke: start `worker-sweep` + `worker-bulk-processor`, watch pending lists fill and matches count climb.
