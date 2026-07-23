# Runbook — Redis memory high

> Triggered by `RedisMemoryHigh`: used memory > 80% of max for 5m.

## Why it matters
Redis backs the cache, arq queues, Redlock locks, and the token bucket. Under
memory pressure the `volatile-lru` policy evicts cache keys (which is fine —
they're read-through), but if durable keys (queues/locks, set without TTL) ever
approach the cap, jobs and locks are at risk. 80% is the early-warning line.

## Diagnosis
1. What's consuming memory? `kubectl -n processing exec deploy/scheduler -- python -c "import os,redis;r=redis.from_url(os.environ['REDIS_URL']);print(r.info('memory')['used_memory_human']); print(r.info('keyspace'))"`
2. Is it the queue backlog (`arena:priority`/`arena:standard` huge → also see
   `processing-lag.md`) or cache bloat?
   - Backlog: drain it (scale processors / fix the stall), memory recovers.
   - Cache bloat: check the largest keys / cache TTLs.
3. Eviction happening? `... r.info('stats')['evicted_keys']` climbing.

## Remediation
- **Backlog-driven**: resolve the lag (KEDA should already be scaling). Memory
  frees as the queues drain.
- **Genuine growth**: scale ElastiCache up a node size, or out (the terraform
  `elasticache` module: bump `node_type`, or enable cluster mode for sharding).
  Apply via terraform; ElastiCache supports online scaling for most paths.
- **Policy sanity**: confirm `maxmemory-policy=volatile-lru` so only TTL'd cache
  keys are evicted, never queue/lock keys.

## Verify
`redis_memory_used_bytes / redis_memory_max_bytes` back under 80%; no eviction of
durable keys; queues/locks intact (`crs_matches_processed_total` advancing).
