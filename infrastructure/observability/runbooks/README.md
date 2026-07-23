# arenarank operational runbooks

Implements proposal §14.5. Each alert in `prometheus/alert-rules.yaml` links to
its runbook via the `runbook_url` annotation.

| Runbook | Trigger / use |
|---|---|
| [processing-lag.md](processing-lag.md) | `ProcessingLag` — queue depth > 50k for 10m (WARNING) |
| [processing-stalled.md](processing-stalled.md) | `ProcessingStalled` — no matches processed 15m in active season (CRITICAL) |
| [dlq-backlog.md](dlq-backlog.md) | `HighDLQRate` — DLQ intake > 1% of processed (WARNING) / DLQ remediation |
| [api-error-spike.md](api-error-spike.md) | `APIErrorSpike` — 5xx > 1% over 2m (CRITICAL) |
| [leaderboard-freeze.md](leaderboard-freeze.md) | `LeaderboardStaleness` / emergency leaderboard freeze |
| [database-failover.md](database-failover.md) | `DBReplicationLag` / RDS failover + PITR restore |
| [redis-memory.md](redis-memory.md) | `RedisMemoryHigh` — Redis memory > 80% (WARNING) |
| [riot-key-rotation.md](riot-key-rotation.md) | Riot API key rotation (routine + emergency) |
| [season-transition.md](season-transition.md) | Manual season transition override (§13.3) |

## §14.5 required runbooks — coverage
- DLQ backlog remediation → `dlq-backlog.md`
- Riot API key rotation → `riot-key-rotation.md`
- Season transition manual override → `season-transition.md`
- Emergency leaderboard freeze → `leaderboard-freeze.md`
- Database failover checklist → `database-failover.md`

## Conventions
- `kubectl` examples assume the deployed namespaces (`api`, `processing`, `data`,
  `observability`). Switch context per environment first
  (`aws eks update-kubeconfig --name arenarank-prod`).
- The `arena.workers.tools.*` helper modules referenced (replay_dlq,
  season_transition, leaderboard_freeze) are operator entrypoints in the backend;
  if a tool is not yet implemented, the equivalent Redis/SQL command is given
  inline.
