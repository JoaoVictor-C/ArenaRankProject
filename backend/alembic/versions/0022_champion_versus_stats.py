"""champion_versus_stats — cross-subteam champion matchups materializados

Revision ID: 0022_champion_versus_stats
Revises: 0021_participant_combat_stats

Backs GET /champions/{id}/matchups?kind=versus (the champion-page "quem ele
bate" grid). Mesma família de rollup que ``champion_combo_stats``, mas o
self-join é entre participantes de subteams DIFERENTES do mesmo match (não
do MESMO subteam) — cada campeão de um lado carrega sua PRÓPRIA colocação,
por isso ``c0``/``c1`` guardam contadores separados (ao contrário de
``champion_combo_stats``, onde os dois membros de uma dupla compartilham a
mesma colocação de subteam).

Sem backfill nesta migração — o cron (``champion_versus_maintenance``) e uma
população manual inicial preenchem depois. A tabela começa vazia.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_champion_versus_stats"
down_revision: str | None = "0021_participant_combat_stats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "champion_versus_stats",
        sa.Column("season_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("c0", sa.Integer(), nullable=False),  # champion ids, c0 < c1
        sa.Column("c1", sa.Integer(), nullable=False),
        sa.Column("games", sa.Integer(), nullable=False),  # matches c0/c1 faced (diff subteams)
        sa.Column("c0_top4", sa.Integer(), nullable=False),  # c0's OWN top4 count in these games
        sa.Column("c0_placement_sum", sa.Integer(), nullable=False),
        sa.Column("c1_top4", sa.Integer(), nullable=False),  # c1's OWN top4 count in these games
        sa.Column("c1_placement_sum", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("season_id", "c0", "c1", name="pk_champion_versus_stats"),
    )
    # Per-champion read (matchups?kind=versus): all opponents of a fixed champion,
    # from either side of the pair — two indexes, one per position.
    op.create_index(
        "ix_champion_versus_stats_season_c0_games",
        "champion_versus_stats",
        ["season_id", "c0", "games"],
    )
    op.create_index(
        "ix_champion_versus_stats_season_c1_games",
        "champion_versus_stats",
        ["season_id", "c1", "games"],
    )


def downgrade() -> None:
    op.drop_index("ix_champion_versus_stats_season_c1_games", table_name="champion_versus_stats")
    op.drop_index("ix_champion_versus_stats_season_c0_games", table_name="champion_versus_stats")
    op.drop_table("champion_versus_stats")
