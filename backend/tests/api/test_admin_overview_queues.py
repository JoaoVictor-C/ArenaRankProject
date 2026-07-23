"""Admin overview — queue-depth reporting must reflect the real sweep/bulk
pipeline (SWEEP_PENDING_* lists), not the legacy arena:priority/arena:standard
arq queues that have had no producer since ingestion/priority-worker were
retired. See docker-compose.prod.yml's design note for that history.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arena.api.app import create_app
from arena.api.routers import admin as admin_mod
from arena.core.config import settings

_KEY = "s3cret-admin-key"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


class _FakeQueueRedis:
    """Fake supporting exactly the ops _live_queues needs (llen + hlen)."""

    def __init__(self, lens: dict[str, int]) -> None:
        self._lens = lens

    async def llen(self, key: str) -> int:
        return self._lens.get(key, 0)

    async def hlen(self, key: str) -> int:
        return self._lens.get(key, 0)

    async def aclose(self) -> None:
        return None


class _FakeRuntime:
    def __init__(self, redis) -> None:
        self.redis_factory = lambda: redis
        self.sessionmaker = None
        self.season_service = None


def test_overview_reports_sweep_pending_depths_not_legacy_arq_queues(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    fake = _FakeQueueRedis(
        {
            "arena:sweep:pending:priority": 7,
            "arena:sweep:pending:standard": 42,
            "arena:dlq": 3,
            "arena:sweep:attempts": 5,
        }
    )
    monkeypatch.setattr(admin_mod, "_runtime", lambda: _FakeRuntime(fake))

    r = client.get("/api/v1/admin/overview", headers={"X-Admin-Key": _KEY})
    assert r.status_code == 200
    body = r.json()

    queue_names = {q["name"] for q in body["queues"]}
    assert queue_names == {
        "arena:sweep:pending:priority",
        "arena:sweep:pending:standard",
        "arena:dlq",
        "arena:sweep:attempts",
    }
    # The legacy arq queue names must never resurface here — they'd always
    # read back 0 and silently hide the real backlog.
    assert "arena:priority" not in queue_names
    assert "arena:standard" not in queue_names

    depths = {q["name"]: q["depth"] for q in body["queues"]}
    assert depths["arena:sweep:pending:priority"] == 7
    assert depths["arena:sweep:pending:standard"] == 42
    assert depths["arena:dlq"] == 3
    assert depths["arena:sweep:attempts"] == 5

    metrics = {m["key"]: m["value"] for m in body["metrics"]}
    assert metrics["queueDepth"] == "49"  # priority(7) + standard(42)
    assert metrics["dlqDepth"] == "3"


def test_overview_falls_back_to_representative_when_redis_absent(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", _KEY)

    class _NoRedisRuntime:
        redis_factory = None
        sessionmaker = None
        season_service = None

    monkeypatch.setattr(admin_mod, "_runtime", lambda: _NoRedisRuntime())

    r = client.get("/api/v1/admin/overview", headers={"X-Admin-Key": _KEY})
    assert r.status_code == 200
    queue_names = {q["name"] for q in r.json()["queues"]}
    assert queue_names == {
        "arena:sweep:pending:priority",
        "arena:sweep:pending:standard",
        "arena:dlq",
        "arena:sweep:attempts",
    }
