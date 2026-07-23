# Runbook — Riot API key rotation

> Proposal §14.5. Routine (production keys expire) or emergency (key leaked /
> revoked → ingestion 401/403 storm).

## When
- Scheduled rotation of the production Riot key.
- `RiotRateLimitHits` persistently firing with 403/401 (key throttled/blocked).
- Security event: key exposed.

## Procedure
1. **Obtain the new key** from the Riot Developer Portal (production key).
2. **Store it in AWS Secrets Manager** (the source of truth; ESO syncs it):
   - `aws secretsmanager put-secret-value --secret-id arenarank/prod/riot-api-key --secret-string '<NEW_KEY>'`
3. **Force the External Secrets sync** (or wait for the 1h refreshInterval):
   - `kubectl -n processing annotate externalsecret arenarank-secrets force-sync=$(date +%s) --overwrite`
   - Confirm the Secret updated: `kubectl -n processing get secret arenarank-secrets -o jsonpath='{.data.RIOT_API_KEY}' | base64 -d | head -c 8`
4. **Roll the ingestion pod** so it reloads the env (Settings reads at startup):
   - `kubectl -n processing rollout restart deploy/ingestion`
   - `kubectl -n processing rollout status deploy/ingestion`
5. **Processors** also use the key for match enrichment — roll them too:
   - `kubectl -n processing rollout restart deploy/processor-priority deploy/processor-standard`

## Verify
- `crs_riot_api_requests_total{status="200"}` resumes; 401/403 stop.
- Ingestion logs show successful polls: `kubectl -n processing logs deploy/ingestion --since=5m`.

## Notes
- The token-bucket rate limiter (Redis Lua, §9.3) is keyed per API key; a new key
  starts with a fresh budget — no manual reset needed.
- If using a bridge window, keep the old key valid until step 5 verifies, then
  revoke it in the portal.
