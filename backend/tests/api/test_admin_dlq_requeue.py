"""Admin DLQ requeue — must enqueue a real process_match arq job onto
arena:priority (enqueue_job), not push a bare id onto the retired sweep
pending list. PriorityWorker consumes it immediately, no cron tick involved.
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
    """Fake supporting exactly the ops requeue_dlq needs, including the
    ArqRedis-only enqueue_job (requeue_dlq now goes through the arq_redis_factory
    seam rather than the plain redis_factory)."""

    def __init__(self, dlq_entries: list[dict]) -> None:
        self.dlq: list[bytes] = [json.dumps(e).encode() for e in dlq_entries]
        self.enqueued: list[dict] = []

    async def lrange(self, key: str, start: int, stop: int) -> list[bytes]:
        return list(self.dlq)

    async def lrem(self, key: str, count: int, value: bytes) -> int:
        if value in self.dlq:
            self.dlq.remove(value)
            return 1
        return 0

    async def enqueue_job(self, function: str, *args: object, **kwargs: object) -> object:
        self.enqueued.append({"function": function, "args": args, **kwargs})
        return object()

    async def aclose(self) -> None:
        return None


class _FakeRuntime:
    def __init__(self, redis) -> None:
        self.redis_factory = lambda: redis

        async def _arq_factory():
            return redis

        self.arq_redis_factory = _arq_factory
        self.sessionmaker = None
        self.season_service = None


def test_requeue_enqueues_a_process_match_job_on_the_priority_queue(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    fake = _FakeDlqRedis([{"riotMatchId": "NA1_123", "error": "boom"}])
    monkeypatch.setattr(admin_mod, "_runtime", lambda: _FakeRuntime(fake))

    r = client.post("/api/v1/admin/dlq/NA1_123/requeue", headers={"X-Admin-Key": _KEY})

    assert r.status_code == 200
    body = r.json()
    assert body["requeued"] is True
    assert body["queue"] == "arena:priority"

    # Removed from the DLQ...
    assert fake.dlq == []
    # ...and enqueued as a real arq job (not a bare-id list push).
    assert len(fake.enqueued) == 1
    job = fake.enqueued[0]
    assert job["function"] == "process_match"
    assert job["args"] == ("NA1_123",)
    assert job["_queue_name"] == "arena:priority"
    # NOT the plain "process_match:{id}" scheme discovery uses — that id may
    # already have a cached (failed) result from the dead-letter, which would
    # make arq silently collapse the requeue as a duplicate.
    assert job["_job_id"].startswith("process_match:NA1_123:requeue:")


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
    assert fake.enqueued == []
