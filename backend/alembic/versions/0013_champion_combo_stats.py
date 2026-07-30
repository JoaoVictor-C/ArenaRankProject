"""champion_combo_stats — sinergias (duplas/trios) materializadas

Revision ID: 0013_champion_combo_stats
Revises: 0012_season_record_cache

As rotas ``/champions/synergy*`` faziam um self-join de 2 ou 3 vias sobre
``match_participants`` a CADA request. Medido na temporada com 1,2M participações
elegíveis, cache quente, máquina de dev:

    /champions/synergy            8,0 s   63,5M buffers   ~285 MB em temp
    /champions/synergy/tierlist  19,1 s     22M buffers   ~530 MB em temp

O scan que fazia o OOM killer derrubar a api na t3.micro custava 1,35 s e 0,9M
buffers — ou seja, a sinergia é PIOR, e ficava fora do circuit breaker do Caddy.

Agregado por TEMPORADA, não por dia (ao contrário de champion_daily_stats): há
~309k trios distintos na temporada, e multiplicar isso por dia estouraria a
tabela. Cumulativo significa que o cron recomputa a temporada inteira a cada
tick, o que é aceitável de hora em hora.

Piso de ESCRITA (``settings.synergy_combo_min_games``, default 3) descarta a
cauda que nenhuma leitura pode alcançar: 309k trios caem para ~21k. O piso de
LEITURA é ``SYNERGY_MIN_GAMES`` (15) — manter o de escrita estritamente abaixo,
senão a rota silenciosamente perde combos válidos.

Backfill incluído: roda no PRIMÁRIO, uma vez. ToS: placement-derived.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_champion_combo_stats"
down_revision: str | None = "0012_season_record_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Piso de escrita do backfill. Espelha o default de
#: ``settings.synergy_combo_min_games``; a migração não importa a config (uma
#: migração tem de ser reproduzível independentemente do env atual).
_WRITE_FLOOR = 3


def upgrade() -> None:
    op.create_table(
        "champion_combo_stats",
        sa.Column("season_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("size", sa.SmallInteger(), nullable=False),
        sa.Column("c0", sa.Integer(), nullable=False),
        sa.Column("c1", sa.Integer(), nullable=False),
        sa.Column("c2", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("games", sa.Integer(), nullable=False),
        sa.Column("top4", sa.Integer(), nullable=False),
        sa.Column("first_place", sa.Integer(), nullable=False),
        sa.Column("placement_sum", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "season_id", "size", "c0", "c1", "c2", name="pk_champion_combo_stats"
        ),
    )
    op.create_index(
        "ix_champion_combo_stats_season_size_games",
        "champion_combo_stats",
        ["season_id", "size", "games"],
    )

    # Duplas (size=2, c2=0 sentinela).
    op.execute(
        f"""
        INSERT INTO champion_combo_stats
            (season_id, size, c0, c1, c2, games, top4, first_place, placement_sum)
        SELECT mm.season_id, 2, p0.champion_id, p1.champion_id, 0,
               count(*),
               count(*) FILTER (WHERE p0.placement <= 4),
               count(*) FILTER (WHERE p0.placement = 1),
               sum(p0.placement)
        FROM match_participants p0
        JOIN match_participants p1
          ON p1.match_id = p0.match_id AND p1.team_id = p0.team_id
         AND p0.champion_id < p1.champion_id
        JOIN matches mm ON mm.id = p0.match_id
        WHERE p0.eligible AND p1.eligible
        GROUP BY mm.season_id, p0.champion_id, p1.champion_id
        HAVING count(*) >= {_WRITE_FLOOR}
        ON CONFLICT ON CONSTRAINT pk_champion_combo_stats DO NOTHING
        """
    )

    # Trios (size=3).
    op.execute(
        f"""
        INSERT INTO champion_combo_stats
            (season_id, size, c0, c1, c2, games, top4, first_place, placement_sum)
        SELECT mm.season_id, 3, p0.champion_id, p1.champion_id, p2.champion_id,
               count(*),
               count(*) FILTER (WHERE p0.placement <= 4),
               count(*) FILTER (WHERE p0.placement = 1),
               sum(p0.placement)
        FROM match_participants p0
        JOIN match_participants p1
          ON p1.match_id = p0.match_id AND p1.team_id = p0.team_id
         AND p0.champion_id < p1.champion_id
        JOIN match_participants p2
          ON p2.match_id = p0.match_id AND p2.team_id = p0.team_id
         AND p1.champion_id < p2.champion_id
        JOIN matches mm ON mm.id = p0.match_id
        WHERE p0.eligible AND p1.eligible AND p2.eligible
        GROUP BY mm.season_id, p0.champion_id, p1.champion_id, p2.champion_id
        HAVING count(*) >= {_WRITE_FLOOR}
        ON CONFLICT ON CONSTRAINT pk_champion_combo_stats DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_champion_combo_stats_season_size_games", table_name="champion_combo_stats"
    )
    op.drop_table("champion_combo_stats")
