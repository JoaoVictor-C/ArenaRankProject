# Backend wiring (one line) — unlocks the live telemetry stream

The console **works immediately with no backend changes** by polling the existing
`GET /api/v1/admin/overview` (real queue/DLQ/season/integrity data). To unlock the
richer real-time worker view (true paused/active state, tick locks, cursors,
pending-list depths, attempts in-flight) and the **SSE push stream**, mount the
new telemetry router that ships in this repo.

A new, self-contained file was added for you:

    backend/arena/api/routers/admin_telemetry.py

It is **additive and self-gated** (it applies `Depends(require_admin)` itself).
You only need to include it once.

## 1. Mount the router

Open `backend/arena/api/app.py`. Right after the existing admin-router block
(the `try: … include_router(_admin_router, …)` block, ~line 96), add:

```python
try:
    from arena.api.routers.admin_telemetry import router as _admin_telemetry_router

    api_router.include_router(_admin_telemetry_router)
except Exception:  # pragma: no cover - import-order / optional-dep tolerance
    _log.warning("api.router.admin_telemetry_unavailable", exc_info=True)
```

That exposes:

- `GET /api/v1/admin/workers/live`   — one live snapshot (JSON)
- `GET /api/v1/admin/workers/stream` — Server-Sent Events, pushed every ~1.5s

Both require the same `X-Admin-Key`. The console **auto-detects** the endpoint:
once it returns 200, the top-bar status flips from `parcial · overview` to
`ao vivo · stream`. No console change needed.

## 2. CORS (only for the "Produção"/"Custom" presets)

The **Local** preset needs nothing — it rides the Vite dev proxy (relative
`/api`), so there is no cross-origin request.

For **Produção/Custom** (the console calls an absolute URL), that backend must
allow the console origin. Set on the backend:

    CORS_ORIGINS=http://localhost:5173,http://localhost:5174

(`arena.core.config.Settings.cors_origins` reads this comma-separated env var.)

## 3. Admin key

Admin endpoints fail closed until `ADMIN_API_KEY` is set on the backend:

    # backend/.env
    ADMIN_API_KEY=dev-super-secret

Enter that same value in the console's lock screen.

## Notes

- The SSE stream is consumed via `fetch` (not `EventSource`) so the key header
  can be sent. If a proxy buffers the stream, the console’s 6s watchdog falls
  back to polling `/workers/live` automatically — you still get live data.
- The telemetry snapshot is Redis-only (fast). Season/integrity/flags/DLQ come
  from the slower `/admin/overview` poll. No new DB load on the 1.5s path.
