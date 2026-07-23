"""Contrato do /healthz com REPLICA_LAG_CHECK (T3.1) + probe de lag.

* flag off (default): /healthz NÃO expõe o bloco ``replica`` (contrato antigo
  intacto — UptimeRobot etc. seguem felizes);
* flag on sem DB alcançável: probe degrada para ``status: unknown`` e o
  healthz continua 200 (observabilidade nunca derruba liveness);
* ``replica_sync_status``: lag correto com subscription ativa, ``None`` sem
  subscription, e nunca propaga erro de DB.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from arena.api.app import create_app
from arena.core.config import Settings
from arena.services.replication_status import replica_sync_status

NOW = datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar(self) -> Any:
        return self._value


class FakeSession:
    def __init__(self, value: Any = None, *, boom: bool = False) -> None:
        self._value = value
        self._boom = boom

    async def execute(self, _stmt: Any) -> _Result:
        if self._boom:
            raise ConnectionError("db fora")
        return _Result(self._value)


def test_healthz_without_flag_has_no_replica_block() -> None:
    client = TestClient(create_app(Settings(replica_lag_check=False)))
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert "replica" not in body


def test_healthz_with_flag_degrades_to_unknown_without_db() -> None:
    # Sem Postgres alcançável nesta máquina: o probe falha e o healthz segue 200.
    client = TestClient(create_app(Settings(replica_lag_check=True)))
    resp = client.get("/healthz")
    assert resp.status_code == 200
    replica = resp.json()["replica"]
    assert replica == {"status": "unknown", "lastSyncAt": None, "lagSeconds": None}


async def test_probe_reports_lag_with_active_subscription() -> None:
    ts = NOW - timedelta(seconds=42)
    sync = await replica_sync_status(FakeSession(ts), now=NOW)  # type: ignore[arg-type]
    assert sync.last_sync_at == ts
    assert sync.lag_seconds == 42.0


async def test_probe_none_without_subscription() -> None:
    sync = await replica_sync_status(FakeSession(None), now=NOW)  # type: ignore[arg-type]
    assert sync.last_sync_at is None and sync.lag_seconds is None


async def test_probe_swallows_db_errors() -> None:
    sync = await replica_sync_status(FakeSession(boom=True), now=NOW)  # type: ignore[arg-type]
    assert sync.last_sync_at is None and sync.lag_seconds is None
