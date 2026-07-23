# Runbook — DLQ backlog remediation

> Proposal §14.5. Triggered by `HighDLQRate` (warning) or a manual report of a
> growing `arena:dlq` Redis list.

## Symptom
`job:crs_dlq_ratio:5m` > 1%, or `LLEN arena:dlq` climbing. Matches are failing
their retries and landing in the dead-letter list instead of being rated.

## Quick diagnosis
1. Confirm the rate and the dominant failure reason:
   - Grafana → "Processing Pipeline" → DLQ ratio panel.
   - `kubectl -n processing logs deploy/processor-standard --since=15m | grep -i "dlq\|exhausted\|error"`
2. Inspect a sample DLQ entry (entries are JSON):
   - `kubectl -n processing exec deploy/scheduler -- python -c "import os,redis,json; r=redis.from_url(os.environ['REDIS_URL']); print(r.lindex('arena:dlq',0))"`
3. Classify the cause:
   - **Riot 5xx / timeouts** → upstream; see `riot-key-rotation.md` if 403/401.
   - **DB write errors** (deadlock, constraint) → see DB section below.
   - **Poison payload** (one bad match id loops) → quarantine it.

## Remediation
- **Transient upstream**: once Riot recovers, replay the DLQ:
  - `kubectl -n processing exec deploy/scheduler -- python -m arena.workers.tools.replay_dlq --limit 5000`
    (re-enqueues DLQ entries onto `arena:standard`; idempotent via the processed flag).
- **DB pressure**: check `pg_replication_lag_seconds` and connection saturation;
  if PgBouncer is saturated, scale the session pool or reduce processor replicas
  temporarily, then replay.
- **Poison payload**: pop and archive the offending entry to S3 for offline
  analysis instead of replaying:
  - `... r.lpop('arena:dlq')` and write to `s3://arenarank-prod-archives/dlq/`.

## Verify
- DLQ ratio back under 1% for 10m; `LLEN arena:dlq` draining.
- `crs_matches_processed_total{outcome="success"}` advancing.

## Escalate
If DLQ intake stays > 1% after upstream recovery and a replay, page the
processing on-call (it indicates a code-level pipeline bug, not a transient).
