"""season_ingest_state.seeded_at + last_error — semeadura fora do processo da API

Revision ID: 0017_ingest_seeded_at
Revises: 0016_worker_telemetry

``POST /admin/ingest/bootstrap`` resolvia os Riot IDs de semente e enfileirava o
backfill DENTRO do processo da API. Isso só funciona quando a API compartilha
caixa com os workers. No deploy dividido ela precisa de duas coisas que a API do
EC2 não tem:

* a CHAVE DA RIOT, para resolver "Nome#TAG" em puuid via account-v1 — e a
  .env.example diz explicitamente que a chave "NOT needed by the EC2/API box";
* o REDIS DAS FILAS, para o ``enqueue_backfill`` cair onde algum worker vá
  consumir — o Redis do EC2 é só cache de leitura.

Ou seja: apertar "Iniciar refill" no console apontado para o EC2 falharia mesmo
com as sementes configuradas, e no melhor caso enfileiraria num Redis que
ninguém drena. Mesma classe do bug de telemetria resolvido em 0016.

A correção separa INTENÇÃO de EXECUÇÃO: a rota só marca a temporada como
``catching_up`` (banco, funciona de qualquer caixa) e o ``bootstrap_tick`` da
caixa de workers — que tem chave e fila — semeia e carimba ``seeded_at``.
``last_error`` leva a falha de volta ao console, porque quem clica está numa
caixa e quem executa está na outra.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_ingest_seeded_at"
down_revision: str | None = "0016_worker_telemetry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "season_ingest_state",
        sa.Column("seeded_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "season_ingest_state",
        sa.Column("last_error", sa.String(length=300), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("season_ingest_state", "last_error")
    op.drop_column("season_ingest_state", "seeded_at")
