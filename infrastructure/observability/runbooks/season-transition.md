# Runbook — Season transition manual override

> Proposal §14.5 / §13.3 (season lifecycle). The scheduler normally runs the
> season transition cron automatically; this is the manual override for an
> off-schedule or stuck transition.

## What a transition does (§13.3)
1. Freeze the ending season (no new matches processed into it).
2. Soft-reset every player: `new_sigma = min(sigma * 1.5, 350)`; create a fresh
   `player_seasons` row; CR recomputed from the reset (μ,σ).
3. Ingestion begins processing the new season's matches.

## Manual trigger
1. **Pre-checks**:
   - Queue is drained for the ending season: `job:crs_queue_depth:sum` ≈ 0.
   - No active alerts on the processing pipeline.
2. **Freeze first** (prevents in-flight writes racing the reset) — see
   `leaderboard-freeze.md`, then:
3. **Invoke the transition** on the scheduler pod:
   - `kubectl -n processing exec deploy/scheduler -- python -m arena.workers.tools.season_transition --from <SEASON_ID> --to <NEW_SEASON_ID> --confirm`
   - The job is transactional and idempotent (re-running on a completed season
     is a no-op guarded by the new `player_seasons` rows).
4. **Unfreeze** and let ingestion resume.

## Verify
- `crs_active_season_player_count` reflects the new season's enrolled players.
- Spot-check a player: their new-season CR derives from `sigma*1.5` (capped 350).
- `player_seasons` has one new row per active player for `<NEW_SEASON_ID>`.

## Rollback
The transition is forward-only by design (soft-reset is intended). If invoked on
the wrong season, restore from the pre-transition RDS snapshot (see
`database-failover.md` for the PITR procedure) — do NOT attempt to "un-reset".
