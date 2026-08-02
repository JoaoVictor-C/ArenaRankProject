"""champion_build_stats — augment/item build stats materializadas (nativas)

Revision ID: 0019_champion_build_stats
Revises: 0018_participant_picks

Substitui a fonte de dados do painel "Build recomendada" e da aba "Augments
em alta" (``/winrate``), até aqui um agregado de TERCEIROS (``champion_build_ref``,
PROVISIONAL — ver docstring de ``build_ref_service.py``). Com augments/items
agora capturados em ``match_participants`` (migração 0018), este rollup os
agrega por (temporada, campeão, augment/item) do mesmo jeito que
``champion_combo_stats`` agrega sinergias — ``unnest()`` sobre as colunas
ARRAY em vez de self-join, mas o mesmo raciocínio de custo: um agregado
por-request sobre ``match_participants`` seria o mesmo tipo de scan caro que
motivou os outros rollups desta série.

``kind`` discrimina augment/item porque o mesmo pick_id numérico não é
comparável entre os dois catálogos (augment 63 e item 63 não têm relação).

Sem backfill nesta migração: as colunas de origem (``augments``/``items``)
estão vazias em toda linha existente neste instante (a captura nativa só
começa a partir de agora, e o backfill histórico é uma operação separada —
ver ``scripts/backfill_augments.py``). A tabela começa vazia; o cron
(``champion_build_stats_maintenance``) e o backfill a populam depois.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_champion_build_stats"
down_revision: str | None = "0018_participant_picks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BUILD_PICK_KIND = postgresql.ENUM(
    "augment", "item", name="build_pick_kind", create_type=False
)


def upgrade() -> None:
    _BUILD_PICK_KIND.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "champion_build_stats",
        sa.Column("season_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", _BUILD_PICK_KIND, nullable=False),
        sa.Column("champion_id", sa.Integer(), nullable=False),
        sa.Column("pick_id", sa.Integer(), nullable=False),
        sa.Column("games", sa.Integer(), nullable=False),
        sa.Column("top1", sa.Integer(), nullable=False),  # placement == 1
        sa.Column("top4", sa.Integer(), nullable=False),  # placement <= 4
        sa.Column("placement_sum", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "season_id", "kind", "champion_id", "pick_id", name="pk_champion_build_stats"
        ),
    )
    # Per-champion read (champion_build): top picks within (season, kind, champion).
    op.create_index(
        "ix_champion_build_stats_champion_games",
        "champion_build_stats",
        ["season_id", "kind", "champion_id", "games"],
    )
    # Global cross-champion read (top_build / augment catalog tier): group by pick_id.
    op.create_index(
        "ix_champion_build_stats_pick_games",
        "champion_build_stats",
        ["season_id", "kind", "pick_id", "games"],
    )


def downgrade() -> None:
    op.drop_index("ix_champion_build_stats_pick_games", table_name="champion_build_stats")
    op.drop_index("ix_champion_build_stats_champion_games", table_name="champion_build_stats")
    op.drop_table("champion_build_stats")
    _BUILD_PICK_KIND.drop(op.get_bind(), checkfirst=True)
