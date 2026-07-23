#!/usr/bin/env bash
# init_replica.sh — bootstrap da réplica de leitura no EC2 (T2.4/T2.5).
#
# Roda NO EC2, na raiz do repo (~/arenarank), com a stack de prod de pé
# (docker compose -f docker-compose.prod.yml up -d pg-replica) e o túnel
# Tailscale ativo (T2.1). Faz:
#   1. espera o pg-replica ficar pronto;
#   2. puxa o schema do PRIMÁRIO (schema-only, sem objetos Timescale) e aplica;
#   3. cria a SUBSCRIPTION arena_read_sub apontando para o primário.
#
# Env obrigatória:
#   PRIMARY_HOST      IP tailnet do notebook (TS_NOTEBOOK_IP da T2.1)
#   PRIMARY_PASSWORD  senha do usuário arena no primário
# Env opcional:
#   PRIMARY_PORT=5432  PRIMARY_USER=arena  PRIMARY_DB=arena
#   COPY_DATA=true     true  -> a subscription copia os dados na criação
#                      false -> só streaming (use quando semear via pg_dump
#                               restaurado antes, p/ matches grandes demais
#                               pro uplink residencial; ver runbook §Seed)
#   COMPOSE_FILE=docker-compose.prod.yml
#
# DDL NÃO replica: depois deste bootstrap, toda migração segue o
# docs/runbook-replicacao.md (réplica primeiro, alembic no primário depois).

set -euo pipefail

PRIMARY_HOST="${PRIMARY_HOST:?defina PRIMARY_HOST (IP tailnet do notebook)}"
PRIMARY_PASSWORD="${PRIMARY_PASSWORD:?defina PRIMARY_PASSWORD (senha do arena no primário)}"
PRIMARY_PORT="${PRIMARY_PORT:-5432}"
PRIMARY_USER="${PRIMARY_USER:-arena}"
PRIMARY_DB="${PRIMARY_DB:-arena}"
COPY_DATA="${COPY_DATA:-true}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }
# Tudo roda DENTRO do container pg-replica: client tools pg18 + rota p/ tailnet
# via host. -T: sem TTY (script).
replica_exec() { compose exec -T -e PGPASSWORD="$PRIMARY_PASSWORD" pg-replica "$@"; }

echo ">> 1/3 aguardando pg-replica aceitar conexões..."
for _ in $(seq 1 30); do
  if compose exec -T pg-replica pg_isready -U arena -d arena >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
compose exec -T pg-replica pg_isready -U arena -d arena

echo ">> 2/3 aplicando schema do primário (${PRIMARY_HOST}:${PRIMARY_PORT}) na réplica..."
# --schema-only: dados vêm pela subscription (ou seed manual).
# --no-owner/--no-privileges: donos/grants do primário não existem na réplica.
# Filtro Timescale (defensivo — o primário do notebook é pg18 vanilla, mas um
# primário dev com Timescale não pode vazar a extensão pra réplica):
#   * esquemas internos _timescaledb_* excluídos no próprio pg_dump;
#   * CREATE EXTENSION/COMMENT timescaledb removidos do stream.
replica_exec bash -c "
  set -euo pipefail
  pg_dump 'host=${PRIMARY_HOST} port=${PRIMARY_PORT} user=${PRIMARY_USER} dbname=${PRIMARY_DB}' \
    --schema-only --no-owner --no-privileges \
    --exclude-schema '_timescaledb_*' \
  | grep -v -E '(CREATE|COMMENT ON) EXTENSION.*timescaledb' \
  | psql -v ON_ERROR_STOP=1 -U arena -d arena
"

echo ">> 3/3 criando a subscription arena_read_sub (copy_data=${COPY_DATA})..."
if replica_exec psql -U arena -d arena -tAc \
  "SELECT 1 FROM pg_subscription WHERE subname = 'arena_read_sub'" | grep -q 1; then
  echo "ERRO: subscription arena_read_sub já existe. Para um resync do zero," >&2
  echo "siga docs/runbook-replicacao.md §Resync (DROP SUBSCRIPTION primeiro)." >&2
  exit 1
fi
replica_exec psql -U arena -d arena -v ON_ERROR_STOP=1 -c \
  "CREATE SUBSCRIPTION arena_read_sub
     CONNECTION 'host=${PRIMARY_HOST} port=${PRIMARY_PORT} user=${PRIMARY_USER} password=${PRIMARY_PASSWORD} dbname=${PRIMARY_DB}'
     PUBLICATION arena_read
     WITH (copy_data = ${COPY_DATA});"

echo ">> pronto. estado da subscription:"
replica_exec psql -U arena -d arena -c \
  "SELECT subname, received_lsn, latest_end_lsn, latest_end_time
   FROM pg_stat_subscription;"
echo ">> acompanhe o catch-up com:"
echo "   docker compose -f ${COMPOSE_FILE} exec pg-replica psql -U arena -d arena -c 'SELECT * FROM pg_stat_subscription;'"
