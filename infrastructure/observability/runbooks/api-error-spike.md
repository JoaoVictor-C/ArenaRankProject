# Runbook — API error spike (CRITICAL)

> Triggered by `APIErrorSpike`: 5xx rate > 1% over 2m on the api.

## Immediate triage
1. **Scope**: "API & SLO" dashboard → 5xx ratio + request-rate-by-status. Is it
   all endpoints or one route?
2. **Logs**: `kubectl -n api logs deploy/api --since=5m | grep -E '"level":"(error|critical)"'`
   - Structured JSON; group by `message` / `traceId`. Pull a `traceId` and open
     the trace in Tempo to see where it fails (DB? cache? downstream?).
3. **Dependencies**:
   - DB: `pg_replication_lag_seconds`, connection saturation, PgBouncer up?
   - Redis: `redis_memory` alert? cache read-through failing → DB overload?
4. **Recent change**: did a deploy just land? `kubectl -n api rollout history deploy/api`.

## Remediation
- **Bad deploy**: `kubectl -n api rollout undo deploy/api` and confirm 5xx drops.
- **DB overload**: the read path should hit Redis first; if cache is cold/evicted
  (see `redis-memory.md`), warm it or scale Redis. Temporarily scale the API up
  (`kubectl -n api scale deploy/api --replicas=8`) only if the bottleneck is
  API-CPU, not the DB.
- **Downstream (Riot) bleed-through**: read endpoints should never call Riot
  synchronously; if they do via a bug, the trace shows it — hotfix/rollback.

## Verify
5xx ratio back under 1% for 2m; latency p95 normal; alert clears.

## Escalate
If 5xx persists after rollback and dependencies are healthy, page the API on-call;
it indicates a data-level issue (e.g., a poisoned cache entry) needing investigation.
