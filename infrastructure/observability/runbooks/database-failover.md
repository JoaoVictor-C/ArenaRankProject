# Runbook — Database failover checklist

> Proposal §14.5 / §10.5. RDS Multi-AZ does automatic failover (< 60s); this is
> the human checklist for confirming health, and the manual PITR/restore path.

## Automatic failover (Multi-AZ)
RDS promotes the standby on AZ/instance failure automatically. The endpoint DNS
is unchanged; apps reconnect via PgBouncer.

### Checklist during/after a failover
1. **Confirm the event**: AWS console / `aws rds describe-events --source-identifier arenarank-prod-pg`.
2. **App reconnect**: PgBouncer pools recycle dead connections automatically; if a
   pod is stuck, roll it:
   - `kubectl -n api rollout restart deploy/api`
   - `kubectl -n processing rollout restart deploy/processor-priority deploy/processor-standard deploy/ingestion deploy/scheduler`
3. **Verify writes**: `crs_matches_processed_total{outcome="success"}` advancing;
   `DBReplicationLag` (replica) recovers within a few minutes.
4. **Replica health**: the read replica may need to be recreated if the old
   primary became the replica's source — check `read_replica_endpoint`.

## Manual restore / PITR (data corruption, bad migration, mis-run season reset)
1. **Stop writes**: freeze the leaderboard (`leaderboard-freeze.md`) and scale
   processors to 0 so nothing writes during the restore.
2. **Restore to a new instance** at a point in time:
   - `aws rds restore-db-instance-to-point-in-time --source-db-instance-identifier arenarank-prod-pg --target-db-instance-identifier arenarank-prod-pg-restore --restore-time <ISO8601>`
3. **Validate** the restored instance (row counts, latest `cr_snapshots`, the
   suspect table) before cutover.
4. **Cutover**: update the `DATABASE_URL` secret to the restored endpoint (via
   Secrets Manager + ESO sync), roll all pods.
5. **Resume**: unfreeze, scale processors back, re-enable KEDA.

## Notes
- `deletion_protection = true` on prod RDS — intentional; disable only for a
  deliberate teardown.
- Backups: daily snapshots retained 30 days; PITR enabled (§10.5).
- TimescaleDB hypertable (`cr_snapshots`) restores with the instance; no separate
  step.
