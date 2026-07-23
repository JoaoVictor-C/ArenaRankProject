# Observability

Implements proposal §14 (Monitoring & Observability) for the arenarank backend.

| Area | Files | Proposal |
|---|---|---|
| Metrics & alerts | `prometheus/alert-rules.yaml`, `prometheus/recording-rules.yaml` | §14.1, §14.2 |
| Scrape / routing | `prometheus/prometheus.yaml`, `prometheus/servicemonitor.yaml`, `prometheus/alertmanager.yaml` | §14.1 |
| Dashboards | `grafana/dashboards/*.json`, `grafana/datasources.yaml`, `grafana/dashboard-provider.yaml` | §14.1 |
| Logs | `loki/loki-values.yaml`, `loki/promtail-config.yaml` | §14.3 |
| Traces | `tempo/tempo-values.yaml` | §14.4 |
| Collector | `otel/otel-collector.yaml` | §14.4 |
| Runbooks | `runbooks/*.md` | §14.5 |

## Alerts (§14.2) — implemented 1:1
| Alert | Condition | Severity |
|---|---|---|
| ProcessingLag | queue depth > 50k for 10m | warning |
| ProcessingStalled | no matches processed 15m (active season) | critical |
| HighDLQRate | DLQ intake > 1% of processed (5m) | warning |
| APIErrorSpike | 5xx rate > 1% over 2m | critical |
| LeaderboardStaleness | Top-1000 unupdated > 10m | warning |
| DBReplicationLag | replica lag > 5s | warning |
| RedisMemoryHigh | Redis memory > 80% | warning |

Plus supporting: `RiotRateLimitHits` (info), `TargetDown` (warning).

## Metric contract (must be emitted by the app)
The rules consume the §14.1 metric names. The backend must expose, on `/metrics`:
- Processing: `crs_matches_processed_total{outcome}`, `crs_queue_depth{queue}`,
  `crs_processing_duration_seconds_bucket`, `crs_worker_active_count`,
  `crs_riot_api_requests_total{status}`, `crs_riot_api_rate_limit_hits_total`,
  `crs_integrity_flags_total{flag}`.
- Business: `crs_players_registered_total`, `crs_active_season_player_count`,
  `crs_leaderboard_update_latency_seconds_bucket`,
  `crs_leaderboard_last_refresh_timestamp_seconds`.
- API (from the FastAPI instrumentator): `http_requests_total{job="api",status}`,
  `http_request_duration_seconds_bucket{job="api"}`.
- Exporters: `pg_replication_lag_seconds` (postgres_exporter),
  `redis_memory_used_bytes` / `redis_memory_max_bytes` (redis_exporter).

> Note: `crs_leaderboard_last_refresh_timestamp_seconds` is a small addition the
> scheduler should set on each refresh — the staleness alert/panel needs an
> "age" signal, which a counter alone can't provide.

## Trace/log correlation
Logs are structured JSON with `traceId` (§14.3). Grafana's Loki→Tempo derived
field links a log's `traceId` to its trace; Tempo→Loki and Tempo→Prometheus link
back (see `grafana/datasources.yaml`). The OTel collector redacts PUUIDs from
spans before export.

## Install order
1. kube-prometheus-stack (Operator + Prometheus + Alertmanager + Grafana).
2. `kubectl apply -k infrastructure/observability` (OTel collector + rules + monitors).
3. Loki / Tempo via their Helm charts with the values files here.
4. Wire Grafana datasources + dashboard provider (sidecar or ConfigMap mount).
