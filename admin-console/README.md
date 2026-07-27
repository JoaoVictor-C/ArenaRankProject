# ArenaRank · Console de Operações

A second, **admin-only** frontend — separate from the player app — that shows the
match-processing pipeline in **real time**: discovery (sweeps), the arq queues
(`arena:standard`/`arena:priority`), continuous processing, the DLQ, season
state, integrity/account flags, Riot API usage, and daily match volume. You can
**switch the target backend at runtime** (Local ↔ Produção ↔ Custom),
pause/resume discovery workers, reprocess or discard DLQ entries (one at a
time or all at once), and manage tournaments (Campeonatos).

It runs locally on its own port (**5174**) and is intentionally `noindex`.

```
Sweeps (descoberta) ──▶ arena:standard/priority (fila arq) ──▶ StandardWorker/
                                                               PriorityWorker
                                                               (consumidores
                                                                contínuos)
                                                                  │      └─▶ DLQ
                                                                  └─▶ ratings/DB
```

`StandardWorker`/`PriorityWorker` are continuous arq consumers — no cron tick,
no idle window between batches. There is no "batch processor" stage; the queue
depth itself is the signal for how much work is in flight.

## Quick start

```bash
cd admin-console
npm install
npm run dev          # http://localhost:5174
```

Then in the browser:

1. Pick a backend in the top bar (**Local** is the default and needs no CORS).
2. Enter the admin key (the backend's `ADMIN_API_KEY`).
3. Watch it go live.

> The backend must have `ADMIN_API_KEY` set, or every admin call returns 503
> ("admin não configurado").

## Backends

| Preset      | How it connects                         | CORS needed?            |
| ----------- | ---------------------------------------- | ------------------------ |
| **Local**   | relative `/api` via the Vite dev proxy → `http://localhost:8000` | No |
| **Produção**| absolute URL you enter (persisted)      | Yes — allow `:5174`     |
| **Custom**  | any absolute URL you enter              | Yes — allow `:5174`     |

- Change the local proxy target with `VITE_LOCAL_API_TARGET` (see `.env.example`).
- Seed the production URL with `VITE_PROD_API_URL`, or just type it in the UI.
- The admin key is stored **per backend** in `localStorage` (this browser only).
- For **Produção**/**Custom**, the backend needs `CORS_ORIGINS` to include this
  console's origin, e.g. `CORS_ORIGINS=http://localhost:5173,http://localhost:5174`
  (`arena.core.config.Settings.cors_origins`).

## Real-time, two tiers

- **Fast (≈1.5s):** worker state + queue/pipeline depths.
  - Prefers the **SSE stream** `GET /admin/workers/stream`.
  - Auto-falls back to **polling** `GET /admin/workers/live` if the stream
    doesn't deliver (e.g. a buffering proxy) — a 6s watchdog handles it.
  - If the live endpoint isn't reachable, it degrades to deriving worker/queue
    data from `/admin/overview` (top bar shows `parcial · overview`).
- **Slower (≈8s–15s):** season, integrity queue, account flags, DLQ items,
  business metrics, daily match stats, Riot API usage, tournaments list —
  polled from their own endpoints (see below).

The top-bar status pill shows the mode (`ao vivo · stream`, `ao vivo · poll 1.5s`,
`parcial · overview`) and a heartbeat that pulses on every frame.

## What you can do

- **Pause / resume** discovery workers: `sweep`, `priority_sweep`, `backfill`,
  `rearm`, `reconcile` (Redis enable flag — see `PAUSABLE_WORKERS` in
  `backend/arena/workers/queues.py`). `StandardWorker`/`PriorityWorker` have no
  pause switch — they're plain arq consumers with no per-job concept of "idle".
- **Reprocess / discard** dead-lettered matches — one at a time, or **all at
  once** (`Reprocessar tudo`, safe/idempotent even under a large backlog).
- **Mark integrity events reviewed**.
- **Manage tournaments** (Campeonatos tab): create, view standings/rosters,
  set a match's stream link + status, submit results.
- See per-worker tick activity, cursor progress, backlog, cadence; live queue
  depths; current season config; account flags; Riot API rate-limit usage
  (per-bucket gauges, drift warnings vs Riot's own headers); matches-per-day
  trend.

## Scripts

```bash
npm run dev         # dev server on :5174
npm run build       # type-check + production build to dist/
npm run preview     # preview the production build
npm run typecheck   # tsc --noEmit
```

## Endpoints used

All under `/api/v1`, gated by `X-Admin-Key` (except the public tournament list/detail).

**Read:** `GET /admin/overview` · `GET /admin/workers/live` · `GET /admin/workers/stream` ·
`GET /admin/matches/daily` · `GET /admin/riot/usage` · `GET /admin/stats/series` ·
`GET /admin/dlq` · `GET /admin/integrity` · `GET /tournaments` ·
`GET /admin/tournament/{id}` (admin detail, includes the access key).

**Write:** `POST /admin/workers/{name}/pause|resume` ·
`POST /admin/dlq/{id}/requeue` · `POST /admin/dlq/requeue-all` ·
`DELETE /admin/dlq/{id}` · `POST /admin/integrity/{id}/review` ·
`PATCH /admin/players/{id}/select` · `POST /admin/seasons` ·
`PATCH /admin/seasons/{id}/config` · `POST /admin/seasons/{id}/transition` ·
`POST /admin/tournaments` (create) · `POST /admin/tournament/{id}/match/{n}/link` ·
`POST /admin/tournament/{id}/match/{n}/result`.
