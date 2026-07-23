# Runbook — Processing lag (queue backlog)

> Triggered by `ProcessingLag` (warning): combined queue depth > 50k for 10m.

## Symptom
`job:crs_queue_depth:sum` > 50000. Matches are being ingested faster than the
processors drain them; player CR updates lag behind real games.

## Diagnosis
1. Confirm KEDA is scaling: `kubectl -n processing get scaledobject,hpa,deploy`.
   - Expected: processor replicas climbing toward `maxReplicaCount` (20).
2. If replicas are NOT scaling:
   - KEDA operator healthy? `kubectl -n keda get pods`.
   - Trigger reachable? KEDA reads `LLEN arena:priority|standard` on ElastiCache.
   - `kubectl -n processing describe scaledobject processor-standard` → events.
3. If replicas ARE at max but still lagging:
   - Per-job latency: "Processing Pipeline" → duration p95/p99 panel.
   - DB-bound? Check `pg_stat_statements` / Performance Insights for slow writes,
     PgBouncer saturation, replication lag.

## Remediation
- **KEDA not scaling**: fix the Redis trigger (address/auth) or temporarily raise
  the base `replicas` on the processor Deployments while KEDA is repaired.
- **At max, DB-bound**: this is the design ceiling (20 workers → ~2M matches/day,
  §11.3). If sustained, raise `maxReplicaCount` AND verify RDS headroom first;
  consider PgBouncer pool sizing.
- **Pressure mode** (§11.4): at depth > 100k ingestion auto-stops fetching new
  ids and lets processors drain — confirm `crs_queue_depth` is falling once
  ingestion backs off.

## Verify
`job:crs_queue_depth:sum` trending down under 50k; alert clears after 10m.
