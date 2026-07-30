"""Gate de catch-up, codec do backlog e semeadura — as partes puras do refill.

A equivalência cronológica de ponta a ponta está em
``test_chronological_replay`` (precisa de Postgres). Aqui ficam as invariantes
que não precisam de banco, e que quebram silenciosamente se alguém mexer:

* o codec do ``match_backlog`` faz ida-e-volta EXATA — o que sai dele alimenta o
  mesmo caminho de escrita de uma partida ao vivo, então perder um campo aqui
  vira uma partida avaliada diferente;
* a semeadura tolera entrada malformada em vez de derrubar o refill;
* o modo de ingestão FALHA ABERTO em ``live``.
"""

from __future__ import annotations

import json

import pytest

from arena.core.config import settings
from arena.db import models as m
from arena.riot.arena import parse_arena_match, parsed_from_json, parsed_to_json
from arena.workers import bootstrap


def _payload(match_id: str = "BR1_GATE0001", started_ms: int = 1_784_246_400_000) -> dict:
    def part(puuid: str, sub: int, place: int, champ: int) -> dict:
        return {
            "puuid": puuid,
            "riotIdGameName": f"name-{puuid}",
            "riotIdTagline": "BR1",
            "championId": champ,
            "playerSubteamId": sub,
            "subteamPlacement": place,
            "profileIcon": 42,
            "timePlayed": 812,
            "gameEndedInEarlySurrender": False,
        }

    return {
        "metadata": {"matchId": match_id},
        "info": {
            "queueId": 1700,
            "gameDuration": 812,
            "gameStartTimestamp": started_ms,
            "participants": [
                part("p0", 1, 1, 11),
                part("p1", 1, 1, 22),
                part("p2", 2, 2, 33),
                part("p3", 2, 2, 44),
            ],
        },
    }


# ---------------------------------------------------------------------------
# Codec do backlog
# ---------------------------------------------------------------------------


def test_backlog_codec_round_trips_exactly() -> None:
    """Ida-e-volta idêntico — o drenador reusa isto como se fosse ingestão viva."""
    parsed = parse_arena_match(_payload())
    # Passa por JSON de verdade: a coluna é JSONB, não um dict em memória.
    back = parsed_from_json(json.loads(json.dumps(parsed_to_json(parsed))))
    assert back == parsed


def test_backlog_codec_preserves_played_at() -> None:
    """``started_at_ms`` é a CHAVE DE ORDENAÇÃO do backlog. Perdê-lo destrói o
    único motivo de o backlog existir."""
    parsed = parse_arena_match(_payload(started_ms=1_700_000_123_456))
    assert parsed_to_json(parsed)["startedAtMs"] == 1_700_000_123_456
    assert parsed_from_json(parsed_to_json(parsed)).started_at_ms == 1_700_000_123_456


def test_backlog_codec_preserves_eligibility_and_placement() -> None:
    """Elegibilidade e colocação decidem a nota — não podem se perder no trajeto."""
    parsed = parse_arena_match(_payload())
    back = parsed_from_json(parsed_to_json(parsed))
    original = {
        p.puuid: (p.placement, p.eligible_for_progression, p.champion_id)
        for t in parsed.subteams
        for p in t.participants
    }
    restored = {
        p.puuid: (p.placement, p.eligible_for_progression, p.champion_id)
        for t in back.subteams
        for p in t.participants
    }
    assert original == restored


def test_backlog_size_is_independent_of_payload_bloat() -> None:
    """É ISTO que faz o backlog caber: o parse é um conjunto FECHADO de campos.

    Um payload match-v5 real traz ~100 campos por participante (kills, itens,
    runas, challenges...) e pesa ~75 kB; o parse guarda 10 campos e pesa ~2,5 kB.
    Numa temporada de 71k partidas isso é a diferença entre ~5 GB e ~180 MB.

    A propriedade não dá para medir com um payload sintético (o nosso já é
    mínimo), então testamos o que a garante: inflar o payload com campos extras
    NÃO muda uma vírgula do que é estacionado. No dia em que alguém adicionar um
    passthrough genérico ao parser, isto quebra.
    """
    lean = _payload()
    bloated = _payload()
    bloated["info"]["gameVersion"] = "15.14.1"
    bloated["info"]["tournamentCode"] = "x" * 500
    for p in bloated["info"]["participants"]:
        p.update({f"junkField{i}": "y" * 40 for i in range(60)})
        p["challenges"] = {f"c{i}": i for i in range(80)}
        p["perks"] = {"styles": [{"selections": [{"perk": i} for i in range(9)]}]}

    assert len(json.dumps(bloated)) > 10 * len(json.dumps(lean))  # payload inchou
    assert parsed_to_json(parse_arena_match(bloated)) == parsed_to_json(
        parse_arena_match(lean)
    )


# ---------------------------------------------------------------------------
# Semeadura
# ---------------------------------------------------------------------------


def test_seed_parsing_accepts_well_formed_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings, "bootstrap_seed_riot_ids", "Alpha#BR1, Bravo#0000 ,Charlie#TAG"
    )
    assert bootstrap.seed_riot_ids() == [
        ("Alpha", "BR1"),
        ("Bravo", "0000"),
        ("Charlie", "TAG"),
    ]


@pytest.mark.parametrize(
    "value", ["", "   ", ",,,", "SemTag", "#semNome", "SoNome#", " # "]
)
def test_malformed_seeds_are_dropped_not_fatal(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uma vírgula sobrando no env não pode impedir um refill inteiro."""
    monkeypatch.setattr(settings, "bootstrap_seed_riot_ids", value)
    assert bootstrap.seed_riot_ids() == []


def test_malformed_entries_do_not_discard_the_good_ones(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "bootstrap_seed_riot_ids", "lixo,Bom#BR1,,#ruim")
    assert bootstrap.seed_riot_ids() == [("Bom", "BR1")]


async def test_bootstrap_refuses_without_seeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem semente não há como começar — falhar explícito, não silenciosamente."""
    monkeypatch.setattr(settings, "bootstrap_seed_riot_ids", "")
    result = await bootstrap.start_bootstrap(None, "season-x")
    assert result["status"] == "error"
    assert result["reason"] == "no seeds configured"


# ---------------------------------------------------------------------------
# Modo de ingestão
# ---------------------------------------------------------------------------


async def test_mode_fails_open_to_live() -> None:
    """Se a leitura do modo explodir, o padrão é AVALIAR.

    Um refill que perde o gate produz ordem ruim, e ordem ruim é reparável por
    replay. Um ``live`` que vira ``catching_up`` por engano PARA de avaliar
    partidas — isso é uma parada silenciosa do produto.
    """
    from arena.services import ingest_state

    class _Exploding:
        async def execute(self, *_a: object, **_k: object) -> object:
            raise RuntimeError("db caiu")

    ingest_state.invalidate_mode_cache()
    mode = await ingest_state.get_mode(_Exploding(), "season-y")  # type: ignore[arg-type]
    assert mode is m.IngestMode.live


def test_write_floor_of_replay_is_bounded() -> None:
    """O teto por tick existe para um piso muito antigo não virar uma transação
    gigante — e o replay RECUSA em vez de reprocessar meio intervalo."""
    assert settings.replay_max_matches_per_tick > 0
    assert settings.out_of_order_tolerance_ms > 0
    assert settings.replay_min_idle_seconds >= 0
