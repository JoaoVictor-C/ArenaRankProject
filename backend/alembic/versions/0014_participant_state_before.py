"""match_participants.state_before — ponto de restauração p/ replay cronológico

Revision ID: 0014_participant_state_before
Revises: 0013_champion_combo_stats

O motor de rating é dependente de ORDEM (Plackett-Luce sequencial, sequências,
janela provisória, camada de cap PDL), mas a ingestão é *reverso*-cronológica
(a Riot devolve ids do mais novo para o mais antigo) e roda 10–20 em paralelo.
Corrigir isso exige reprocessar "a partir de T" — e para isso é preciso
restaurar mu/sigma de cada jogador naquele instante.

Isso NÃO era recuperável:

* ``cr_snapshots.snapshot_at`` é o relógio de PROCESSAMENTO, não ``played_at``,
  logo não indexa tempo de jogo quando o processamento saiu de ordem;
* ``match_participants.cr_before`` sozinho não inverte
  ``cr = (mu - 3*sigma)*scale + offset`` — uma equação, duas incógnitas.

``match_participants`` já tem ``played_at`` denormalizado e uma linha por
jogador por partida, ou seja, já é o índice cronológico certo. Com
``state_before`` cada linha vira um ponto de restauração completo: os campos
INDEPENDENTES de ``PlayerState`` (mu, sigma, current_streak, matches_played,
placement_matches_remaining, peak_cr). ``cr`` e ``is_provisional`` são derivados
e recalculados na restauração.

NULLABLE de propósito: as linhas anteriores a esta migração não têm snapshot.
Backfill é impossível (o estado histórico não existe em lugar nenhum), então o
replay INCREMENTAL se recusa a atravessar um NULL — o primeiro replay depois
deste deploy precisa ser um rerate de temporada inteira, que reescreve todas as
linhas com snapshot. Daí em diante o incremental funciona.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_participant_state_before"
down_revision: str | None = "0013_champion_combo_stats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Sem server_default: uma linha nova SEM snapshot tem de ser distinguível de
    # uma com snapshot vazio. NULL = "não sei", e o replay incremental para.
    op.add_column(
        "match_participants",
        sa.Column("state_before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("match_participants", "state_before")
