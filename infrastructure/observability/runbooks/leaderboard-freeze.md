# Runbook — Emergency leaderboard freeze

> Proposal §14.5. Freeze leaderboard updates during an incident (rating bug,
> integrity exploit, season transition) so players don't see corrupt rankings.

## When
- A rating/CR bug is suspected to be writing bad values.
- A live integrity exploit is being investigated.
- Pre-step for a manual season transition (`season-transition.md`).

## Freeze
The leaderboard is served read-through from Redis (Top-1000 set + cached page).
Freezing = stop the scheduler's refresh and pin the cache.
1. **Pause the refresh cron**:
   - `kubectl -n processing scale deploy/scheduler --replicas=0`
2. **Pin the current cache** (extend TTL so it doesn't expire while frozen):
   - `kubectl -n processing exec deploy/ingestion -- python -m arena.workers.tools.leaderboard_freeze --on`
     (sets `arena:leaderboard:frozen=1`; the read path serves the last good page
     and skips recompute).
3. (Optional, hard freeze) **Pause processors** so no CR writes happen at all:
   - `kubectl -n processing scale deploy/processor-priority deploy/processor-standard --replicas=0`
   - Note: KEDA will try to scale these back up; also suspend the ScaledObjects:
     `kubectl -n processing patch scaledobject processor-priority processor-standard --type merge -p '{"metadata":{"annotations":{"autoscaling.keda.sh/paused":"true"}}}'`

## Thaw
1. Clear the freeze flag: `... leaderboard_freeze --off`.
2. Resume KEDA: remove the `autoscaling.keda.sh/paused` annotation.
3. Scale processors back: `kubectl -n processing scale deploy/processor-priority --replicas=2` (KEDA takes over).
4. Restore the scheduler: `kubectl -n processing scale deploy/scheduler --replicas=1`.

## Verify
- `crs_leaderboard_last_refresh_timestamp_seconds` advances again.
- `LeaderboardStaleness` alert clears.
- Spot-check the Top-1000 page matches recomputed CR.
