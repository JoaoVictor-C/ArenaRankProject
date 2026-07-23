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

-- materialized leaderboard view (D2.3 / §11.1)
CREATE MATERIALIZED VIEW IF NOT EXISTS leaderboard_mv AS
  SELECT season_id, player_id, cr, mu, sigma,
         RANK() OVER (PARTITION BY season_id ORDER BY cr DESC) AS rank
  FROM player_seasons;

CREATE UNIQUE INDEX IF NOT EXISTS leaderboard_mv_pk ON leaderboard_mv (season_id, player_id);
CREATE INDEX IF NOT EXISTS leaderboard_mv_rank ON leaderboard_mv (season_id, rank);

-- refresh fn (called by scheduler every 30s per §11.1)
CREATE OR REPLACE FUNCTION refresh_leaderboard() RETURNS void AS $$
  REFRESH MATERIALIZED VIEW CONCURRENTLY leaderboard_mv;
$$ LANGUAGE sql;
