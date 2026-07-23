# arenarank-realoficial — WORKAROUNDS / GOTCHAS de ambiente

> Recriado 2026-06-15. O `workaround.md` original referenciado pelo `prompt.md` foi
> perdido; este reconstrói os gotchas a partir do save-point + doc de recalibração +
> estado vivo da stack. Mantenha junto com `prompt.md`.

---

## 1. Docker Desktop precisa estar VIVO antes de tudo
O daemon Linux do Docker Desktop (`npipe:////./pipe/dockerDesktopLinuxEngine`) **não
sobe sozinho** no boot às vezes. Sintoma:
```
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine;
check if the path is correct and if the daemon is running
```
Fix: iniciar a GUI e esperar ~30-60s o daemon:
```powershell
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
# poll até responder:
docker version --format "{{.Server.Version}}"
```
Só DEPOIS rode `docker start arena-e2e-pg arenarank-redis-1`.

## 2. Postgres STANDALONE na porta 5433 — NÃO é compose (FRÁGIL)
O Postgres/TimescaleDB roda como container avulso `arena-e2e-pg` em **5433** (não 5432,
p/ não colidir com pg local). **Não foi criado via docker-compose** e **não tem volume
nomeado** — os dados (1.863 players, 191 matches) vivem na camada de escrita do próprio
container. `docker rm arena-e2e-pg` = **PERDA TOTAL** dos dados. Use só `docker stop/start`.
- DSN: `postgresql+asyncpg://arena:arena@localhost:5433/arena`
- Redis: container `arenarank-redis-1` em 6379.
- Se for migrar p/ algo durável: `pg_dump` antes (ver §6) e criar volume nomeado.

## 3. Dual-vite IPv4/IPv6 — suba UM vite só com `--host`
Rodar dois `vite` (um default + um extra) causa confusão de bind IPv4 vs IPv6
(`localhost` resolve `::1`, vite às vezes só escuta `127.0.0.1` ou vice-versa). Solução:
**um único** dev server escutando todas as interfaces:
```bash
cd F:/arenarank-realoficial/frontend && npm run dev -- --host
```
Acesse por `http://localhost:5173` ou `http://127.0.0.1:5173`. Não suba uma segunda instância.

## 4. Cache do leaderboard serve STALE após mudança no backend
O leaderboard é cacheado no Redis. Após QUALQUER edição no backend (params de rating,
services, routers) o reload do uvicorn **não** invalida o cache. Sempre:
```bash
# reinicia uvicorn  +  limpa o cache
docker exec arenarank-redis-1 redis-cli FLUSHALL
```
Senão o frontend renderiza dados antigos e parece que a mudança "não pegou".

## 5. Riot API key = PROD key (corrigido 2026-06-15)
`RIOT_API_KEY` em `backend/.env` é uma **PROD key** (NÃO dev) — rate limit alto, sem
expiração de 24h. Logo backfill de centenas/milhares de matches é rápido (não é gargalo).
A nota anterior ("dev key 24h") estava errada. Só necessária p/ ingerir novas partidas,
não p/ servir dados já backfillados.

## 6. Backups de rating (revert do recalibration CRS)
Antes da recalibração de 2026-06-15 foram salvos backups fora do git:
- Código: `backend/_rating_backups/2026-06-15_pre-trinity/{params,modifiers,engine,types}.py`
- Dados: `backend/_rating_backups/2026-06-15_pre-rerate_db.sql` (pg_dump completo pré-re-rate)
Reverter: `git revert 9eb63c1` (ou restaurar os .py) e então
`python -m scripts.rerate_matches --apply`. Re-rate é não-destrutivo e idempotente.

## 7. `delta7d` aparece inflado (ex +827) — known issue, fix-forward
O backfill antigo carimbou `played_at = now()`, colapsando todas as partidas na janela
de ingestão → a janela de 7 dias cobre o histórico inteiro. Corrigido p/ frente em
`arena/riot/arena.py` (parseia `gameStartTimestamp`) + `scripts/backfill.py` (via `arena/ingest`),
mas **linhas existentes mantêm o timestamp comprimido** até um backfill fresco. Normaliza
sozinho com mais dias de dados reais.

## 8. Widgets ainda SAMPLE (por design do contrato, não bug)
Feed "Atividade ao vivo", champion tierlist (página Winrate), admin overview servem dados
de exemplo de propósito. Ligar a tabelas reais é trabalho futuro, não regressão.
