# Runbook — Processing stalled (CRITICAL)

> Triggered by `ProcessingStalled`: no matches processed in 15m during an active
> season. This is page-worthy — the rating pipeline has stopped.

## Immediate triage (first 5 minutes)
1. **Are processors running?**
   - `kubectl -n processing get pods -l app.kubernetes.io/component=worker`
   - CrashLoopBackOff? → `kubectl -n processing logs <pod> --previous`.
2. **Is the queue empty or stuck?**
   - Empty (`job:crs_queue_depth:sum` ≈ 0): the problem is **upstream**
     (ingestion not enqueuing) — jump to step 4.
   - Non-empty but not draining: the problem is the **processors** — step 3.
3. **Processors not draining a non-empty queue:**
   - Redis reachable? `kubectl -n processing exec deploy/scheduler -- python -c "import os,redis;redis.from_url(os.environ['REDIS_URL']).ping()"`
   - DB reachable / not locked? Check `pg_replication_lag_seconds`, Performance
     Insights for a blocking lock, PgBouncer up in `data` namespace.
   - Roll the processors if wedged: `kubectl -n processing rollout restart deploy/processor-priority deploy/processor-standard`.
4. **Ingestion not enqueuing:**
   - `kubectl -n processing logs deploy/ingestion --since=15m`.
   - Riot auth failing (401/403)? → `riot-key-rotation.md`.
   - Ingestion pod down (Recreate strategy, single replica)? `kubectl -n processing get deploy ingestion`; roll it.
   - In pressure mode (§11.4) because depth > 100k? Then processing should still
     be running — re-check step 1/3.

## Common root causes
- Redis/ElastiCache failover in progress → wait for endpoint recovery, pods reconnect.
- RDS failover → see `database-failover.md`.
- Bad deploy → `kubectl -n processing rollout undo deploy/processor-standard`.
- Expired/blocked Riot key (ingestion side) → `riot-key-rotation.md`.

## Verify
`crs_matches_processed_total{outcome="success"}` advancing again; alert clears.
Post-incident: file the root cause; if a deploy caused it, add a smoke gate.
