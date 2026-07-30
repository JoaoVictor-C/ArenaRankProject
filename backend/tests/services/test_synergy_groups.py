"""Forma do self-join de sinergia — a invariante que desduplica os combos.

A propriedade que importa e não é óbvia: a cadeia de ``champion_id``
ESTRITAMENTE CRESCENTE (``c0 < c1 < ... < c{n-1}``) faz cada combo não-ordenado
se formar EXATAMENTE UMA vez. Sem ela, um trio {A,B,C} apareceria nas 6
permutações e a tierlist contaria o mesmo subteam seis vezes.

Esse self-join saiu do caminho de request (custava 8–19 s e centenas de MB de
spill) e passou a viver em dois lugares: ``rebuild_champion_combos``, que ESCREVE
``champion_combo_stats``, e ``_champion_synergies_n_live``, mantido só como
oráculo de paridade. É neles que a estrutura é verificada aqui — sem banco,
inspecionando o SQL gerado.

A checagem complementar (o método público agora LÊ o rollup, não reagrega) fica
no fim; a paridade numérica de verdade está em ``test_champion_combo_rollup``.
"""

from __future__ import annotations

from typing import Any

import pytest

from arena.services.stats_service import SYNERGY_MIN_GAMES, StatsService

_SEASON = "11111111-1111-1111-1111-111111111111"


class _CapturingSession:
    """Captura o statement e devolve zero linhas."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> Any:
        self.statements.append(stmt)

        class _Empty:
            @staticmethod
            def all() -> list[Any]:
                return []

        return _Empty()


async def _live_sql(size: int) -> str:
    """SQL do oráculo (o self-join preservado fora do caminho de request)."""
    session = _CapturingSession()
    rows = await StatsService()._champion_synergies_n_live(
        session,  # type: ignore[arg-type]
        season_id=_SEASON,
        size=size,
    )
    assert rows == []
    return str(session.statements[0])


@pytest.mark.parametrize("size", [2, 3])
async def test_combo_forms_exactly_once_via_increasing_champion_chain(size: int) -> None:
    """Uma comparação ``<`` por membro extra — é o que desduplica o combo."""
    sql = await _live_sql(size)
    # size=2 -> 1 elo (c0<c1); size=3 -> 2 elos (c0<c1, c1<c2).
    assert sql.count("champion_id <") == size - 1


@pytest.mark.parametrize("size", [2, 3])
async def test_members_share_match_and_subteam(size: int) -> None:
    """Sinergia é sobre o MESMO subteam da MESMA partida, não sobre o lobby."""
    sql = await _live_sql(size)
    assert sql.count("match_id =") == size - 1
    assert sql.count("team_id =") == size - 1


@pytest.mark.parametrize("size", [2, 3])
async def test_groups_by_every_member(size: int) -> None:
    sql = await _live_sql(size)
    group_by = sql.split("GROUP BY", 1)[1]
    assert group_by.count("champion_id") == size


async def test_size_is_clamped_to_arena_team_sizes() -> None:
    """Times de Arena são de 2 ou 3 — nada fora disso pode gerar SQL."""
    assert (await _live_sql(0)).count("champion_id <") == 1
    assert (await _live_sql(1)).count("champion_id <") == 1
    assert (await _live_sql(9)).count("champion_id <") == 2


@pytest.mark.parametrize("size", [2, 3])
async def test_scoped_to_season_and_eligible_only(size: int) -> None:
    """Mesmos predicados do resto do sistema: temporada + eligible por membro."""
    sql = await _live_sql(size)
    assert "matches.season_id" in sql
    assert sql.count("eligible IS true") == size


@pytest.mark.parametrize("size", [2, 3])
async def test_sample_floor_is_applied_in_sql(size: int) -> None:
    """O piso vira HAVING — um combo raro nunca chega ao re-rank em Python."""
    sql = await _live_sql(size)
    assert "HAVING" in sql
    assert SYNERGY_MIN_GAMES >= 10  # mesma guarda do showcase de duplas


@pytest.mark.parametrize("size", [2, 3])
async def test_public_method_reads_the_rollup_not_participants(size: int) -> None:
    """A rota não pode voltar a reagregar match_participants por request.

    Esta é a regressão cara: era 8 s (duplas) / 19 s (trios) com centenas de MB
    de spill para disco, pior que o scan que derrubava a api por OOM.
    """
    session = _CapturingSession()
    await StatsService().champion_synergies_n(
        session,  # type: ignore[arg-type]
        season_id=_SEASON,
        size=size,
    )
    sql = str(session.statements[0])
    assert "champion_combo_stats" in sql
    assert "match_participants" not in sql
    assert "JOIN" not in sql.upper()  # leitura de uma tabela só, sem self-join


async def test_pair_route_also_reads_the_rollup() -> None:
    """``/champions/synergy`` (DTO antigo a/b) compartilha o mesmo caminho."""
    session = _CapturingSession()
    await StatsService().champion_synergies(
        session,  # type: ignore[arg-type]
        season_id=_SEASON,
    )
    sql = str(session.statements[0])
    assert "champion_combo_stats" in sql
    assert "match_participants" not in sql
