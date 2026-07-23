# arenarank-realoficial — SAVE-POINT (atualizado 2026-06-15, pós-recalibração CRS)

> Para a próxima sessão. Estado: backend FastAPI completo + E2E verificado + dados REAIS (1.863 players, 191 matches Arena desde 2026-06-01). Frontend Vite/React existente, wired e com fidelidade de design corrigida. Branch `master`, tudo commitado (HEAD `9eb63c1`).
>
> ⚠️ A janela de contexto de 1M acabou ANTES deste save-point ser escrito na sessão anterior; reconstruído a partir do estado real do git. Gotchas de ambiente foram movidos p/ `workaround.md` (recriado — o original tinha se perdido).

---

## 1. Direção (TRAVADA)
Implementar o **design GAMIFICADO da proposta** (`casual_ranked_proposal.md`) como backend **FastAPI/Python** novo em `arenarank-realoficial`, servindo o **frontend existente** (`frontend/`, React+Vite). NÃO é o `formula_ranking_v1` austero de `F:\arenarank` (esse é o projeto irmão / referência). Ver memória ICM `backend-direction-fastapi-pivot`.

- Rating = openskill Plackett-Luce + camada de modifiers gamificados (μ−3σ, streak/placement/soft-cap/boosting/dispersão) + soft-reset + hardening Trinity (DEC-A σ-freeze flagged, DEC-B floor 0.25, C1 cap σ-escalado, M3 weights mean-1.0). Em `backend/arena/rating/` (Python, portado do TS slice-1).
- Contrato de API = `F:\arenarank\spec\api_contract_v1.md` (o frontend espelha em `frontend/src/lib/types.ts`). camelCase, `/api/v1`, porta 8000.

## 2. O que está pronto
- **backend/** (FastAPI, ~72 arq Python): rating (portado) · db (SQLAlchemy schema Trinity-particionado + Alembic 0001+0002) · integrity (RDS/flags) · riot (httpx client) · **ddragon** (champion map + icon URLs) · schemas (Pydantic == contrato) · services (rating/stats/season/leaderboard) · api/routers (leaderboard/player/match/champions/meta/admin/**search**) · tournaments · workers (arq) · core.
- **Dados reais**: 191 matches Arena (queue 1750) backfillados desde 01/06 → 1.863 players. Scripts: `scripts/backfill.py` (unified CLI, `--mode refresh` / `--mode bootstrap`), `scripts/sweep_profile_icons.py`, `scripts/e2e_process_fixture.py`.
- **E2E verificado**: leaderboard/profile/match/tournaments/search funcionam; frontend renderiza dados reais com ícones ddragon (campeão + invocador).
- **Fixes de design (sessão)**: reveal-on-load (anim engine) · search global autocomplete · tags reais (TOP N GLOBAL/regional/Em alta/OTP) · delta7d · fix top4>100% · ícones ddragon · cor do card do pódio extraída do ÍCONE (`useIconColors` histograma) · glow externo removido (`overflow:hidden`) · paleta avatar HSL harmônica.
- **Winstreak "on fire"** (commit `1b24120`, ✅ MERGEADO): linha da TABELA (não pódio) com bg quente animado quando player em 3+ top-1 (placement==1) consecutivos. `top1_streak_by_player` em `stats_service.py` · `top1_streak` no schema/router · `top1Streak` em types.ts · classe `.row.on-fire` em `Leaderboard.tsx`/`.css`.
- **PDL cap layer** (✅ APLICADO ao DB 2026-06-15, NÃO commitado ainda): cap assimétrico de ganho/perda por colocação. `arena/rating/caps.py` (puro, 15 testes) + wired em `engine.rate()` (opção B-pura: clampa μ p/ atingir cr_delta capado, sem ledger — arenarank não faz matchmaking). Ativo em `DEFAULT_PARAMS` (`CapParams(loss_clamp=68.0)`): GANHO tabela `{40,34,26,26,34,40}`+mismatch→~50, PERDA flat 68 (≈P95, dolorosa+sem inflação). AFTER: cr_delta `−68…+49.8` avg +3.66, 0 neg. Backup `_rating_backups/2026-06-15_pre-caps_db.sql`. Sims: `scripts/sim_caps.py`/`diag_inflation.py`/`diag_gates.py`. Briefs Trinity: `trinity_{caps,premade,inflation}_brief.md`. Detalhes + dívida na memória ICM `pdl-cap-layer`.
- **Recalibração CRS** (commit `9eb63c1`, ✅ MERGEADO): matava CR negativo (15.8% dos players, min −360) + swings exorbitantes (Δ até −572). Escalado p/ Trinity (`claw_max`/opus); adotado path Bayesiano-coerente. **Pure params** em `rating/params.py` (reversível): `sigma0` 350→200, `beta` 175→100, `tau` 3.5→1.5, `placement_amp` 2.0→1.0, `max_delta_mu` 150→80, `dispersion_sigma_ref` 85→200 (reverte C1), `streak_loss_floor` 0.25→0.5, `sigma_reset_cap` 350→200. Resultado (re-rate 191 matches): **0% CR negativo**, Δ stddev 119.6→34.1, 0 matches com \|Δ\|>100. Doc: `backend/docs/rating_recalibration_2026-06-15.md`. Novos scripts: `rerate_matches.py` (não-destrutivo, idempotente), `sim_params.py` (what-if offline), `sync_season_config.py`. Backups pré-mudança em `backend/_rating_backups/` (ver `workaround.md` §6).

## 3. COMO SUBIR A STACK (comandos exatos)
```bash
# 0. Docker Desktop daemon DEVE estar vivo primeiro (ver workaround.md §1) — não sobe sozinho no boot
#    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"; esperar ~30-60s

# Postgres (TimescaleDB) — standalone na porta 5433 (NÃO compose; ver workaround.md §2)
docker start arena-e2e-pg   # se parado. Dados persistem no container (sem volume nomeado — frágil)
docker start arenarank-redis-1

# API
cd F:/arenarank-realoficial/backend
DATABASE_URL="postgresql+asyncpg://arena:arena@localhost:5433/arena" \
  REDIS_URL="redis://localhost:6379/0" CORS_ORIGINS="http://localhost:5173" \
  python -m uvicorn arena.api.app:app --host 127.0.0.1 --port 8000

# Frontend (UM vite só, TODAS interfaces — ver gotcha dual-vite IPv4/IPv6)
cd F:/arenarank-realoficial/frontend && npm run dev -- --host

# Design de referência (opcional, p/ comparar)
cd F:/arenarank/frontend/Design && python -m http.server 8899 --bind 127.0.0.1
```
**Após QUALQUER mudança no backend:** reinicie uvicorn **+** `docker exec arenarank-redis-1 redis-cli FLUSHALL` (senão o cache do leaderboard serve stale).

**Backfillar mais partidas** (RIOT_API_KEY em `backend/.env`; dev key expira 24h → pode estar morta, re-cole fresca):
```bash
cd backend && DATABASE_URL="postgresql+asyncpg://arena:arena@localhost:5433/arena" \
  python -m scripts.backfill --mode refresh --start-date 2026-06-01 --max-matches 200 --depth 1
```

## 4. Winstreak "on fire" — ✅ CONCLUÍDA (commit `1b24120`)
A feature que estava interrompida no save-point anterior **foi implementada e mergeada**.
Linha da TABELA (não pódio) recebe bg quente animado + 🔥 quando `top1Streak >= 3`
(top-1/placement==1 consecutivos a partir do match mais recente). Implementação exata:
`top1_streak_by_player` em `stats_service.py` (window `row_number()` + `min(case)`),
hidratado no router, `top1_streak` no schema, `top1Streak` em `types.ts`, classe
`.row.on-fire` em `Leaderboard.tsx`/`.css`. Nada pendente aqui.

## 5. Próximos passos (livres — pedir diretiva nova)
- **Verificar a stack viva** após esta sessão (docker daemon caiu; ver workaround.md §1).
- **CRS Phase-2 (deferido, não bloqueia)**: σ ainda converge devagar (~190 após muitos jogos) → termo −3σ ~constante, CR ≈ μ − const. Convergência real exigiria β menor ou Trinity R3 (amplificar σ-shrink na janela provisória) = cirurgia de engine. Ver `backend/trinity_rating_brief.md` + doc de recalibração.
- **Widgets ainda SAMPLE** (por design do contrato): feed "Atividade ao vivo", champion tierlist (página Winrate), admin overview. Ligar a tabelas reais se quiser.
- **delta7d inflado** (ex +827): backfill antigo carimbou `played_at = now()`; fix-forward já no código, mas linhas existentes só normalizam com backfill fresco (workaround.md §7).
- **Infra/CI-CD/observability** (Wave-Infra) ainda não rodou no FastAPI (tentativa anterior caiu no session-limit). Dockerfile/compose existem; k8s/terraform/CI faltam adaptar.
- **Teste final/E2E abrangente**: deferido (cadência "sem test-gate por slice").
