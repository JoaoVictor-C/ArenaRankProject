"""Fiação do read path materializado — rotas montadas e crons registrados.

Dois modos de falha silenciosa que este arquivo trava:

1. **Rollup sem escritor.** No tree do EC2, ``rebuild_champion_daily`` existia e
   era citado na docstring da migração como escrito por um cron
   ``champion_daily_maintenance`` — que NUNCA foi escrito. O rollup só tinha o
   que o backfill da migração inseriu e envelhecia desde o primeiro dia. Uma
   tabela materializada sem cron é pior que nenhuma: serve número velho com cara
   de número novo.
2. **Rota nova que não sobe.** ``app.py`` monta cada router num try/except (por
   design, tolerância a dependência opcional), então um ImportError numa rota
   nova vira só um warning no log e um 404 em produção.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from arena.api.app import create_app


def _paths() -> set[str]:
    # ``app.routes`` traz wrappers de router, não as rotas finais; o schema
    # OpenAPI é a visão autoritativa do que está realmente montado.
    return set(create_app().openapi()["paths"])


def test_new_read_path_routes_are_mounted() -> None:
    paths = _paths()
    for path in (
        "/api/v1/champions/{champion_id}/trend",
        "/api/v1/champions/synergy/groups",
        "/api/v1/champions/synergy/tierlist",
        "/api/v1/payments/donation",
        "/api/v1/admin/ingest",
        "/api/v1/admin/ingest/bootstrap",
        "/api/v1/admin/ingest/stop",
    ):
        assert path in paths, f"rota não montada (try/except engoliu um erro?): {path}"


def test_refill_crons_are_registered() -> None:
    """Sem estes ticks um refill fica travado: nada drena o backlog em ordem,
    nada mede a fronteira, e a cauda fora de ordem nunca é reprocessada."""
    from arena.workers.scheduler import (
        CRON_JOBS,
        backlog_drain_tick,
        bootstrap_tick,
        rating_replay_tick,
    )

    registered = {job.coroutine for job in CRON_JOBS}
    assert backlog_drain_tick in registered
    assert bootstrap_tick in registered
    assert rating_replay_tick in registered


def test_synergy_literal_paths_win_over_the_champion_id_wildcard() -> None:
    """``/champions/synergy/...`` não pode ser capturado por ``/champions/{id}/...``.

    Ambos têm 3 segmentos; o FastAPI casa por ordem de registro. Se o wildcard
    vier antes, "synergy" vira um champion_id e a rota devolve 422.
    """
    client = TestClient(create_app(), raise_server_exceptions=False)
    for path in ("/api/v1/champions/synergy/groups", "/api/v1/champions/synergy/tierlist"):
        r = client.get(path)
        # Sem DB o handler pode falhar (500), mas NUNCA pode ser 404/422 de
        # roteamento — isso significaria que "synergy" foi lido como um id.
        assert r.status_code not in (404, 422), f"{path} caiu no wildcard: {r.status_code}"


def test_rollup_maintenance_crons_are_registered() -> None:
    """Uma tabela materializada sem cron serve dado velho para sempre."""
    from arena.workers.scheduler import (
        CRON_JOBS,
        champion_combo_maintenance,
        champion_daily_maintenance,
        season_records_maintenance,
    )

    registered = {job.coroutine for job in CRON_JOBS}
    assert champion_daily_maintenance in registered
    assert season_records_maintenance in registered
    assert champion_combo_maintenance in registered


def test_maintenance_crons_do_not_collide_on_the_same_minute() -> None:
    """O combo rebuild recomputa a temporada inteira (~26 s) — não pode empilhar
    em cima de outro tick pesado no mesmo minuto."""
    from arena.workers.scheduler import (
        CRON_JOBS,
        champion_combo_maintenance,
        cr_snapshot_maintenance,
        season_records_maintenance,
    )

    heavy = {champion_combo_maintenance, season_records_maintenance, cr_snapshot_maintenance}
    minutes = [
        sorted(j.minute or ()) for j in CRON_JOBS if j.coroutine in heavy
    ]
    flat = [m for mins in minutes for m in mins]
    assert len(flat) == len(set(flat)), f"ticks pesados colidindo: {minutes}"


def test_champion_daily_cron_runs_often_enough_to_keep_the_tierlist_fresh() -> None:
    """A tierlist inteira sai deste rollup — de hora em hora seria velho demais."""
    from arena.workers.scheduler import CRON_JOBS, champion_daily_maintenance

    job = next(j for j in CRON_JOBS if j.coroutine is champion_daily_maintenance)
    assert job.minute is not None and len(job.minute) >= 4  # <= 15 min entre ticks


def test_rollup_tables_are_in_the_read_replica_publication() -> None:
    """Sem estar na publicação, a réplica nunca vê a tabela e a rota volta vazia."""
    from pathlib import Path

    sql = Path("scripts/replication/create_publication.sql").read_text(encoding="utf-8")
    body = sql.split("CREATE PUBLICATION", 1)[1].split("WITH (", 1)[0]
    assert "champion_daily_stats" in body
    assert "season_record_cache" in body
    assert "champion_combo_stats" in body
