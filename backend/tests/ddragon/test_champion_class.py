"""Classe de campeão (``champion_classes.json``) — os chips de filtro do /winrate.

Regressão que isto guarda: ``ChampRow.role`` vinha HARDCODED como ``""`` no
backend enquanto ``frontend/src/routes/Winrate.tsx`` filtra por ``c.role`` contra
os chips ``ATIRADOR/MAGO/TANQUE/LUTADOR/ASSASSINO/SUPORTE``. Resultado: escolher
qualquer chip devolvia ZERO campeões. Arena não tem lane/rota — isto é a
taxonomia de CLASSE do ddragon (``tags[0]``), não uma posição.

O acoplamento crítico é o vocabulário: se o JSON passar a emitir um rótulo que
não está na lista de chips do front, o filtro volta a não casar nada. Por isso o
teste afirma o CONJUNTO de classes, não só que o mapa carrega.
"""

from __future__ import annotations

from arena.ddragon.service import (
    FALLBACK_VERSION,
    DDragonService,
    _static_class_map,
)

#: Exatamente os chips de ``Winrate.tsx`` (menos "TODOS"), em PT-BR como o JSON.
_FRONTEND_CHIPS = {"Atirador", "Mago", "Tanque", "Lutador", "Assassino", "Suporte"}


def test_class_map_loads_the_full_roster() -> None:
    classes = _static_class_map()
    assert len(classes) > 150  # roster completo, não um arquivo vazio/corrompido


def test_every_class_is_a_chip_the_frontend_knows() -> None:
    """Um rótulo fora deste conjunto reabre o bug do filtro que não casa nada."""
    emitted = set(_static_class_map().values())
    assert emitted <= _FRONTEND_CHIPS, f"classes desconhecidas pelo front: {emitted - _FRONTEND_CHIPS}"
    # E o contrário: todo chip do front precisa existir em algum campeão, senão
    # ele é um filtro morto na UI.
    assert emitted == _FRONTEND_CHIPS


def test_cold_cache_resolves_class_without_network() -> None:
    svc = DDragonService(redis=None)
    # tags[0] do ddragon, não uma opinião nossa: Pyke vem como Suporte.
    assert svc.champion_class_sync(555) == "Suporte"  # Pyke
    assert svc.champion_class_sync(29) == "Atirador"  # Twitch


def test_unknown_and_none_ids_degrade_to_empty_string() -> None:
    """None-safe: id desconhecido => "" (a UI simplesmente omite o chip)."""
    svc = DDragonService(redis=None)
    assert svc.champion_class_sync(None) == ""
    assert svc.champion_class_sync(999_999) == ""


def test_class_map_covers_the_catalog() -> None:
    """Todo campeão do catálogo tem classe — senão ele some de todos os chips."""
    from arena.ddragon.service import _static_champion_map

    missing = set(_static_champion_map()) - set(_static_class_map())
    assert not missing, f"campeões sem classe: {sorted(missing)[:10]}"


def test_splash_url_is_versionless_base_skin() -> None:
    """ddragon serve splash FORA da árvore /cdn/{version} — daí o path sem versão."""
    svc = DDragonService(redis=None)
    url = svc.champion_splash_url_sync(555)
    assert url is not None
    assert url.endswith("/cdn/img/champion/splash/Pyke_0.jpg")
    assert FALLBACK_VERSION not in url


def test_splash_url_is_none_for_unknown_id() -> None:
    svc = DDragonService(redis=None)
    assert svc.champion_splash_url_sync(999_999) is None
    assert svc.champion_splash_url_sync(None) is None
