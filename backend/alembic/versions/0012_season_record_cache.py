"""season_record_cache — resultado materializado de /meta/records

Revision ID: 0012_season_record_cache
Revises: 0011_champion_daily_stats

Os cinco records da temporada (``stats_service._compute_season_records``) custam
um GROUP BY player_id sobre TODOS os participants elegíveis — ~127k jogadores
materializados — mais um sort sem índice em ``cr_delta``. Era a segunda rota que
o OOM killer derrubava na réplica t3.micro (a outra, ``/champions``, virou
``champion_daily_stats``). Um rollup por jogador seria grande demais, então
cacheamos o RESULTADO: no máximo 5 linhas por temporada.

Sem backfill — a primeira execução do cron ``season_records_maintenance``
preenche. Até lá ``/meta/records`` devolve lista vazia (estado honesto, já
suportado pelo router). Tabela plana e minúscula: entra na publicação
``arena_read``.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_season_record_cache"
down_revision: str | None = "0011_champion_daily_stats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "season_record_cache",
        sa.Column("season_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("value", sa.String(length=32), nullable=False),
        sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("accent", sa.String(length=32), nullable=False),
        sa.Column(
            "computed_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("season_id", "key", name="pk_season_record_cache"),
    )


def downgrade() -> None:
    op.drop_table("season_record_cache")
