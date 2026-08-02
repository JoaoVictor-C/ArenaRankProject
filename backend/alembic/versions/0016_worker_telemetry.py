"""worker_telemetry — snapshot publicado pela caixa de workers

Revision ID: 0016_worker_telemetry
Revises: 0015_match_backlog_ingest_state

Num deploy dividido (API no EC2, workers no notebook) as duas caixas têm Redis
SEPARADOS — filas, heartbeats de worker e o token-bucket da Riot só existem na
caixa de workers. Medido: o mesmo endpoint de admin devolve, do EC2,
``queueDepth: 0`` contra 166 reais, todo worker como ``active: false`` e a chave
da Riot como não configurada. Não é uma degradação visível, é uma resposta
confiante e errada — o operador conclui que a ingestão parou.

Esta tabela é o canal por onde a caixa de workers publica o que só ela enxerga.
Usa o RDS, que as duas caixas JÁ compartilham, então não exige VPN, IP fixo nem
porta de entrada no notebook (que fica atrás de NAT e às vezes desligado): o
fluxo é de dentro para fora.

``as_of`` é o que permite degradar com honestidade — o EC2 sabe a idade do
último snapshot e a UI mostra "visto há N min" em vez de zeros.

Sem índice além da PK: a tabela tem uma linha por caixa publicadora (hoje uma).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_worker_telemetry"
down_revision: str | None = "0015_match_backlog_ingest_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "worker_telemetry",
        sa.Column("source", sa.String(length=32), primary_key=True),
        sa.Column("as_of", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("worker_telemetry")
