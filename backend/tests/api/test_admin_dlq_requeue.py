"""Admin DLQ requeue — must push the bare match id onto the real sweep
pending list (SWEEP_PENDING_PRIORITY), not the legacy arena:standard arq
queue. Nothing has consumed that queue since ingestion/priority-worker were
retired in favor of the sweep pipeline, so the old requeue was a silent no-op.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from arena.api.app import create_app
from arena.api.routers import admin as admin_mod
from arena.core.config import settings

_KEY = "s3cret-admin-key"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


class _FakeDlqRedis:
    """Fake supporting exactly the ops requeue_dlq needs."""

    def __init__(self, dlq_entries: list[dict]) -> None:
        self.dlq: list[bytes] = [json.dumps(e).encode() for e in dlq_entries]
        self.pushed: dict[str, list[str]] = {}

    async def lrange(self, key: str, start: int, stop: int) -> list[bytes]:
        return list(self.dlq)

    async def lrem(self, key: str, count: int, value: bytes) -> int:
        if value in self.dlq:
            self.dlq.remove(value)
            return 1
        return 0

    async def lpush(self, key: str, *values: str) -> int:
        bucket = self.pushed.setdefault(key, [])
        for v in values:
            bucket.insert(0, v)
        return len(bucket)

    async def aclose(self) -> None:
        return None


class _FakeRuntime:
    def __init__(self, redis) -> None:
        self.redis_factory = lambda: redis
        self.sessionmaker = None
        self.season_service = None


def test_requeue_pushes_bare_match_id_onto_priority_pending_list(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    fake = _FakeDlqRedis([{"riotMatchId": "NA1_123", "error": "boom"}])
    monkeypatch.setattr(admin_mod, "_runtime", lambda: _FakeRuntime(fake))

    r = client.post("/api/v1/admin/dlq/NA1_123/requeue", headers={"X-Admin-Key": _KEY})

    assert r.status_code == 200
    body = r.json()
    assert body["requeued"] is True
    assert body["queue"] == "arena:sweep:pending:priority"

    # Removed from the DLQ...
    assert fake.dlq == []
    # ...and pushed as a bare match id (not a JSON blob, not the dead arq
    # queue) onto the list BulkProcessorWorker actually drains.
    assert fake.pushed == {"arena:sweep:pending:priority": ["NA1_123"]}


def test_requeue_leaves_other_dlq_entries_untouched(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    fake = _FakeDlqRedis(
        [
            {"riotMatchId": "NA1_123", "error": "boom"},
            {"riotMatchId": "NA1_999", "error": "other"},
        ]
    )
    monkeypatch.setattr(admin_mod, "_runtime", lambda: _FakeRuntime(fake))

    r = client.post("/api/v1/admin/dlq/NA1_123/requeue", headers={"X-Admin-Key": _KEY})

    assert r.status_code == 200
    remaining = [json.loads(e) for e in fake.dlq]
    assert remaining == [{"riotMatchId": "NA1_999", "error": "other"}]


def test_requeue_404_when_not_in_dlq(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    fake = _FakeDlqRedis([])
    monkeypatch.setattr(admin_mod, "_runtime", lambda: _FakeRuntime(fake))

    r = client.post("/api/v1/admin/dlq/does-not-exist/requeue", headers={"X-Admin-Key": _KEY})

    assert r.status_code == 404
    assert fake.pushed == {}
