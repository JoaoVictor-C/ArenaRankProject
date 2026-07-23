"""Tournament scoring engine — pure, DB-free. Source of truth for standings.

Núcleo de "computar corretamente" o resultado dos campeonatos: dada a colocação
de cada equipe por partida, computa os pontos (tabela de pontuação), o bônus de
bravura (1 ponto por jogador que pegou bravura, teto de 4 por partida), desconta
as penalidades do Admin e ordena com os critérios de desempate.

Espelha ``F:/arenarank/spec/tournament_onboarding_scoring_v1.md`` §5:

* Para cada partida encerrada e cada equipe: ``pts = scoring[placement]``.
* ``bravura_bonus = min(bravura_players, 4)`` por partida; ``bonus = Σ bravura_bonus``.
* ``total = Σ perMatch + bonus − penalties``.
* Ordenação: ``total`` desc → desempate (1) mais 1ºs lugares desc;
  (2) melhor colocação na última partida encerrada asc.
* ``perMatch`` contém pontos apenas das partidas encerradas (sem padding).

Sem dependência de DB nem de Pydantic — função pura, testável isoladamente.
Nenhuma string aqui é user-facing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Teto de bônus de bravura por partida (1 ponto por jogador, máx 4).
BRAVURA_CAP = 4

#: Sentinela de "não jogou a última partida" para o critério de desempate.
_NO_PLACEMENT = 10**9


@dataclass(slots=True)
class MatchResult:
    """Resultado de uma partida encerrada.

    ``placements``: ``teamId -> colocação`` (1..N).
    ``bravura``: ``teamId -> nº de jogadores que pegaram bravura`` (0..team_size).
    """

    placements: dict[str, int]
    bravura: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class TeamStanding:
    """Linha de classificação computada para uma equipe."""

    team_id: str
    per_match: list[int]
    bonus: int
    penalties: int
    total: int
    first_places: int
    last_placement: int  # colocação na última partida encerrada (grande se não jogou)


def compute_standings(
    team_ids: list[str],
    results: list[MatchResult | None],
    scoring: dict[int, int],
    penalties: dict[str, int] | None = None,
) -> list[TeamStanding]:
    """Computa a classificação. ``results[n] is None`` ⇒ partida n não encerrada.

    Ordenação: ``total`` desc · mais 1ºs lugares desc · melhor colocação na
    última partida encerrada asc.
    """
    penalties = penalties or {}
    ended = [(i, r) for i, r in enumerate(results) if r is not None]
    last_idx = ended[-1][0] if ended else None

    rows: list[TeamStanding] = []
    for tid in team_ids:
        per_match: list[int] = []
        bonus = 0
        firsts = 0
        last_place = _NO_PLACEMENT
        for i, r in ended:
            assert r is not None  # narrowed by the comprehension above
            place = r.placements.get(tid)
            if place is None:
                continue
            per_match.append(scoring.get(place, 0))
            bonus += min(r.bravura.get(tid, 0), BRAVURA_CAP)
            if place == 1:
                firsts += 1
            if i == last_idx:
                last_place = place
        pen = penalties.get(tid, 0)
        total = sum(per_match) + bonus - pen
        rows.append(
            TeamStanding(
                team_id=tid,
                per_match=per_match,
                bonus=bonus,
                penalties=pen,
                total=total,
                first_places=firsts,
                last_placement=last_place,
            )
        )

    rows.sort(key=lambda s: (-s.total, -s.first_places, s.last_placement))
    return rows


__all__ = ["BRAVURA_CAP", "MatchResult", "TeamStanding", "compute_standings"]
