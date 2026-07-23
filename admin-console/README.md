# ArenaRank · Console de Operações

A second, **admin-only** frontend — separate from the player app — that shows the
data pipeline in **real time**: workers and their processors, what each is doing,
its progress (tick activity, cursors, backlogs), queue depths, the DLQ, season,
integrity and account flags. You can **switch the target backend at runtime**
(Local ↔ Produção ↔ Custom) and pause/resume workers and reprocess failures.

It runs locally on its own port (**5174**) and is intentionally `noindex`.

```
 Sweeps ─▶ fila pendente ─▶ processador em lote ─▶ processadas
   │                                              └─▶ DLQ
```

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
> ("admin não configurado"). See **BACKEND_SETUP.md**.

## Backends

| Preset      | How it connects                         | CORS needed?            |
| ----------- | --------------------------------------- | ----------------------- |
| **Local**   | relative `/api` via the Vite dev proxy → `http://localhost:8000` | No |
| **Produção**| absolute URL you enter (persisted)      | Yes — allow `:5174`     |
| **Custom**  | any absolute URL you enter              | Yes — allow `:5174`     |

- Change the local proxy target with `VITE_LOCAL_API_TARGET` (see `.env.example`).
- Seed the production URL with `VITE_PROD_API_URL`, or just type it in the UI.
- The admin key is stored **per backend** in `localStorage` (this browser only).

## Real-time, two tiers

- **Fast (≈1.5s):** worker state + queue/pipeline depths.
  - Prefers the **SSE stream** `GET /admin/workers/stream` (toggle "Stream").
  - Auto-falls back to **polling** `GET /admin/workers/live` if the stream
    doesn't deliver (e.g. a buffering proxy) — a 6s watchdog handles it.
  - If the live endpoint isn't wired yet, it degrades to deriving worker/queue
    data from `/admin/overview` (top bar shows `parcial · overview`).
- **Slower (≈8s):** season, integrity queue, account flags, DLQ items, business
  metrics — polled from `GET /admin/overview`.

The top-bar status pill shows the mode (`ao vivo · stream`, `ao vivo · poll 1.5s`,
`parcial · overview`) and a heartbeat that pulses on every frame.

To unlock the rich live worker view + SSE, do the one-line backend wiring in
**BACKEND_SETUP.md** (a self-contained router was added to the backend for you).

## What you can do

- **Pause / resume** `sweep`, `priority_sweep`, `bulk_processor` (Redis enable flag).
- **Reprocess / discard** dead-lettered matches.
- **Mark integrity events reviewed**.
- See per-worker tick activity, cursor progress, backlog, cadence; live queue
  depths with sparklines; current season config; account flags.

## Scripts

```bash
npm run dev         # dev server on :5174
npm run build       # type-check + production build to dist/
npm run preview     # preview the production build
npm run typecheck   # tsc --noEmit
```

## Endpoints used

Read: `GET /admin/overview`, `GET /admin/workers/live`, `GET /admin/workers/stream`
Write: `POST /admin/workers/{name}/pause|resume`, `POST /admin/dlq/{id}/requeue`,
`DELETE /admin/dlq/{id}`, `POST /admin/integrity/{id}/review`.
All gated by `X-Admin-Key`.
