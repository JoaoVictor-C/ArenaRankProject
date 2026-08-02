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
            # 4 real picks + 2 zero-padded unused slots — the common shape.
            "playerAugment1": 63,
            "playerAugment2": 220,
            "playerAugment3": 120,
            "playerAugment4": 251,
            "playerAugment5": 0,
            "playerAugment6": 0,
            "item0": 223008,
            "item1": 443090,
            "item2": 0,  # empty slot
            "item3": 226672,
            "item4": 223091,
            "item5": 222517,
            "item6": 3348,
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


def test_extracts_augment_and_item_picks_dropping_zero_slots() -> None:
    """Riot pads unused slots with 0 rather than omitting the key — those must
    not read as real picks, and the payload's specific values must survive."""
    parsed = parse_arena_match(_payload())
    p0 = next(p for t in parsed.subteams for p in t.participants if p.puuid == "p0")
    assert p0.augments == [63, 220, 120, 251]  # the two 0-padded slots dropped
    # item2=0 (empty slot) dropped; item6=3348 (the auto-equipped Arena
    # trinket) dropped too — see test_excludes_the_auto_equipped_arena_trinket.
    assert p0.items == [223008, 443090, 226672, 223091, 222517]


def test_excludes_the_auto_equipped_arena_trinket() -> None:
    """Item 3348 ("Analisador Arcano" / Arcane Sweeper) is auto-equipped for
    every participant in every Arena game — not a real build choice — so it
    must never land in captured items, or it pollutes champion_build_stats
    with a ~100%-pick-rate item nobody actually picked."""
    parsed = parse_arena_match(_payload())
    for t in parsed.subteams:
        for p in t.participants:
            assert 3348 not in p.items


def test_augment_grant_effect_can_push_a_fifth_or_sixth_real_pick() -> None:
    """Some augments grant an EXTRA augment (observed live: id 390 twice on a
    single participant) — a real 5th/6th pick, not padding. Must not be
    deduped or truncated to 4."""
    payload = _payload()
    payload["info"]["participants"][0]["playerAugment5"] = 390
    payload["info"]["participants"][0]["playerAugment6"] = 390
    parsed = parse_arena_match(payload)
    p0 = next(p for t in parsed.subteams for p in t.participants if p.puuid == "p0")
    assert p0.augments == [63, 220, 120, 251, 390, 390]


def test_backlog_codec_round_trips_augments_and_items_exactly() -> None:
    parsed = parse_arena_match(_payload())
    back = parsed_from_json(json.loads(json.dumps(parsed_to_json(parsed))))
    for original, restored in zip(
        (p for t in parsed.subteams for p in t.participants),
        (p for t in back.subteams for p in t.participants),
        strict=True,
    ):
        assert restored.augments == original.augments
        assert restored.items == original.items


def test_backlog_codec_round_trips_combat_telemetry_exactly() -> None:
    payload = _payload()
    payload["info"]["participants"][0].update(
        {
            "kills": 7,
            "deaths": 2,
            "assists": 11,
            "totalDamageDealtToChampions": 18770,
            "goldEarned": 7206,
            "champLevel": 13,
            "totalDamageTaken": 20008,
            "totalHeal": 4961,
            "damageSelfMitigated": 19843,
            "largestMultiKill": 2,
            "killingSprees": 1,
            "totalTimeSpentDead": 243,
        }
    )
    parsed = parse_arena_match(payload)
    back = parsed_from_json(json.loads(json.dumps(parsed_to_json(parsed))))
    assert back == parsed
    p0 = next(p for t in back.subteams for p in t.participants if p.puuid == "p0")
    assert p0.kills == 7
    assert p0.damage_to_champions == 18770
    assert p0.champion_level == 13
    assert p0.time_spent_dead == 243


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


async def test_seeding_refuses_without_seeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem semente não há como começar — falhar explícito, não silenciosamente.

    A checagem vive em ``seed_now`` (caixa de workers), não na rota de admin: só
    a caixa que semeia sabe se ELA tem as sementes configuradas. A mensagem volta
    ao console por ``season_ingest_state.last_error``.
    """
    monkeypatch.setattr(settings, "bootstrap_seed_riot_ids", "")
    result = await bootstrap.seed_now(None, "season-x")
    assert result["status"] == "error"
    assert "BOOTSTRAP_SEED_RIOT_IDS" in result["reason"]


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


# ---------------------------------------------------------------------------
# Regressões do refill (bugs reais encontrados ao apertar o botão)
# ---------------------------------------------------------------------------


def test_seed_region_is_coerced_to_the_routing_enum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A config é texto; os construtores de URL usam ``region.host``.

    Passar a string crua levantava ``AttributeError: 'str' object has no
    attribute 'host'`` DENTRO do try/except que envolve a resolução, então toda
    semente era descartada como se a Riot tivesse recusado e o operador via
    "Nenhuma semente resolvida na Riot" com a chave perfeitamente válida.
    """
    from arena.riot.routing import Region

    monkeypatch.setattr(settings, "bootstrap_seed_region", "americas")
    region = bootstrap.seed_region()
    assert isinstance(region, Region)
    assert region.host  # é o atributo cujo acesso quebrava


def test_bad_seed_region_falls_back_instead_of_exploding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arena.riot.routing import Region

    monkeypatch.setattr(settings, "bootstrap_seed_region", "nao-existe")
    assert bootstrap.seed_region() is Region.AMERICAS


def test_requesting_a_refill_needs_no_riot_key_or_queue_redis() -> None:
    """A rota de admin só registra INTENÇÃO — nada de Riot, nada de fila.

    Semear exige a chave da Riot e o Redis das FILAS, e a API do EC2 não tem
    nenhum dos dois. Enquanto a rota tentava semear, o botão era inutilizável a
    partir do EC2. Se alguém reintroduzir isso aqui, este teste quebra.
    """
    import inspect

    src = inspect.getsource(bootstrap.request_bootstrap)
    assert "resolve_seed_puuids" not in src
    assert "enqueue_backfill" not in src
    assert "get_client" not in src


def test_backlog_drain_does_not_depend_on_ingest_mode() -> None:
    """O drenador tem de rodar em QUALQUER modo.

    Ele pulava fora de ``catching_up``, então encerrar um refill encalhava o
    backlog para sempre — 215 partidas já descobertas paradas sem nunca virar
    rating, o oposto do que ``stop_bootstrap`` promete. O modo decide se
    partidas NOVAS são estacionadas; o que já está estacionado tem de sair.
    """
    import inspect

    from arena.workers.scheduler import backlog_drain_tick

    src = inspect.getsource(backlog_drain_tick)
    assert "not catching up" not in src
    assert "IngestMode.catching_up" not in src
