"""Sample tournament DTOs (t001/t002) — fallback when the table is empty.

Per contract §5 the read endpoints fall back to a representative DTO sample when
the ``tournaments`` table has no rows (or the requested id is a known sample id).
The frontend renders these identically to real rows; swapping to real data is a
no-op for the UI.

These builders return fully-formed Pydantic DTOs (camelCase on the wire). All
user-facing strings are PT-BR.
"""

from __future__ import annotations

from arena.schemas.tournaments import (
    PlayerSlotFilled,
    PrizeRow,
    ScoringEntry,
    StandingRow,
    TeamRoster,
    TournamentDetail,
    TournamentListItem,
    TournamentMatch,
    TournamentMatchResult,
    TournamentMatchResultRow,
    TournamentRules,
)
from arena.tournaments.provision import avatar_from_seed

#: Known sample tournament ids (contract §5 fallback).
SAMPLE_IDS = frozenset({"t001", "t002"})


def _sample_players() -> list[PlayerSlotFilled]:
    return [
        PlayerSlotFilled(
            name=f"Jogador{i}",
            handle=f"#BR{i}",
            riot_id=f"Jogador{i}#BR{i}",
            avatar=avatar_from_seed(f"p{i}"),  # type: ignore[arg-type]
        )
        for i in range(1, 4)
    ]


def sample_list() -> list[TournamentListItem]:
    """Sample tournament list (``GET /tournaments`` fallback)."""
    return [
        TournamentListItem(
            id="t001",
            title="Arena Championship #1",
            format="3v3",
            starts_at="2026-06-10T18:00:00+00:00",
            teams=6,
            prize_rp=5000,
            banner_tone="b1",
            tag="ABERTO",
            amount_label="5.000 RP",
            when_label="em 3 dias",
        ),
        TournamentListItem(
            id="t002",
            title="Weekly Clash",
            format="3v3",
            starts_at="2026-06-14T20:00:00+00:00",
            teams=6,
            prize_rp=2000,
            banner_tone="b2",
            tag="SEMANAL",
            amount_label="2.000 RP",
            when_label="em 7 dias",
        ),
    ]


def sample_detail(tournament_id: str) -> TournamentDetail | None:
    """Sample tournament detail for a known sample id, else ``None``."""
    if tournament_id not in SAMPLE_IDS:
        return None

    players = _sample_players()
    registrations = [
        TeamRoster(
            team_id=f"tm{j}",
            team_name=f"Time {j}",
            seed=j,
            captain=f"Jogador{j * 3 - 2}",
            is_you=(j == 1),
            players=list(players),
        )
        for j in range(1, 7)
    ]

    matches = [
        TournamentMatch(
            n=n,
            status="ended" if n < 2 else ("live" if n == 2 else "upcoming"),
            winner_team_id="tm1" if n == 1 else None,
            starts_at=f"2026-06-10T{18 + n}:00:00+00:00",
            lobby_max=18,
            lobby_count=18 if n < 2 else 12,
            magnetic_link=f"magnet:?xt=urn:arenarank:match{n}",
        )
        for n in range(1, 4)
    ]

    standings = [
        StandingRow(
            team_id=f"tm{j}",
            seed=j,
            team_name=f"Time {j}",
            players=list(players),
            per_match=[6 - j, 4 - (j % 3)],  # only the 2 ended-ish matches
            penalties=0,
            bonus=0,
            total=(6 - j) + (4 - (j % 3)),
            is_you=(j == 1),
        )
        for j in range(1, 7)
    ]
    standings.sort(key=lambda s: -s.total)

    return TournamentDetail(
        id=tournament_id,
        title="Arena Championship #1",
        format="3v3",
        prize_rp=5000,
        prize_label="5.000 RP",
        currency="RP",
        status="live",
        current_match=2,
        matches=matches,
        standings=standings,
        rules=TournamentRules(
            format=["6 times × 3 jogadores", "3 partidas de Arena"],
            scoring=[ScoringEntry(place=p, points=7 - p) for p in range(1, 7)],
            tiebreak=["Total de vitórias", "Posição média"],
        ),
        prizes=[
            PrizeRow(place=1, rp=3000, per_player=1000, medal="gold"),
            PrizeRow(place=2, rp=1500, per_player=500, medal="silver"),
            PrizeRow(place=3, rp=500, per_player=166, medal="bronze"),
        ],
        registrations=registrations,
        history=[
            TournamentMatchResult(
                n=n,
                status="ended" if n < 2 else "upcoming",
                results=[
                    TournamentMatchResultRow(team_name=f"Time {j}", points=6 - j, place=j)
                    for j in range(1, 7)
                ],
            )
            for n in range(1, 4)
        ],
    )


__all__ = ["SAMPLE_IDS", "sample_list", "sample_detail"]
