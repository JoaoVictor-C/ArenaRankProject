"""match_backlog + season_ingest_state — refill com ordem cronológica

Revision ID: 0015_match_backlog_ingest_state
Revises: 0014_participant_state_before

``match_backlog`` é a área de espera do modo ``catching_up``: num refill (base
vazia, janela de temporada retroativa) a descoberta chega em ordem
essencialmente arbitrária — a Riot lista ids do mais novo para o mais antigo e
os consumidores rodam 10–20 em paralelo — então avaliar na chegada produz um
ladder que reflete ordem de CHEGADA, não de JOGO. As partidas são estacionadas
aqui e drenadas depois em ordem ``(played_at, riot_match_id)`` estrita.

Guarda a partida JÁ PARSEADA, não o payload cru: ~2,5 kB contra ~75 kB por
partida (≈180 MB em vez de ≈5 GB numa temporada de 71k) e nada precisa ser
re-buscado na Riot ao drenar (o cache de payload dura só 24 h).

``season_ingest_state`` guarda o modo por temporada, o ``replay_floor`` do
replay incremental e os contadores que o console mostra durante o refill.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_match_backlog_ingest_state"
down_revision: str | None = "0014_participant_state_before"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INGEST_MODE = postgresql.ENUM(
    "catching_up", "live", name="ingest_mode", create_type=False
)


def upgrade() -> None:
    _INGEST_MODE.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "match_backlog",
        sa.Column("riot_match_id", sa.String(length=32), primary_key=True),
        sa.Column("season_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("played_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("parsed", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "discovered_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # A drenagem lê exatamente nesta ordem.
    op.create_index(
        "ix_match_backlog_season_played", "match_backlog", ["season_id", "played_at"]
    )

    op.create_table(
        "season_ingest_state",
        sa.Column("season_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "mode", _INGEST_MODE, server_default=sa.text("'live'"), nullable=False
        ),
        sa.Column("replay_floor", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "frontier_pending", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "frontier_done", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("saturated_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("coverage_pct", sa.Float(), nullable=True),
        sa.Column("coverage_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("season_ingest_state")
    op.drop_index("ix_match_backlog_season_played", table_name="match_backlog")
    op.drop_table("match_backlog")
    _INGEST_MODE.drop(op.get_bind(), checkfirst=True)
