-- Raw-SQL migration (spec §4) — applied AFTER `prisma migrate`.
-- Idempotent: safe to re-run. Degrades gracefully when timescaledb is absent.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- hypertable (D2.1) — degrades gracefully: skip if extension missing
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
    PERFORM create_hypertable(
      'cr_snapshots', 'snapshot_at',
      chunk_time_interval => INTERVAL '7 days',
      if_not_exists => TRUE
    );
  END IF;
END
$$;

-- partial index for ingestion scan (D2 §3)
CREATE INDEX IF NOT EXISTS idx_matches_unprocessed
  ON matches (played_at)
  WHERE processed = false;

-- NOTE: an earlier design (D2.3 / §11.1) had the leaderboard served by a
-- `leaderboard_mv` materialized view refreshed every 30s. That was replaced
-- (see docs/superpowers/specs/2026-06-14-fastapi-backend-master-plan.md) by a
-- Redis sorted-set read-through with a Postgres fallback — see the deployed
-- `backend/arena/services/leaderboard_service.py`'s own docstring: "the
-- leaderboard is not a 30-second materialized view." Do not recreate
-- `leaderboard_mv`/`refresh_leaderboard()` without updating that decision.
