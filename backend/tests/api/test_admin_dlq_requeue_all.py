"""POST /admin/dlq/requeue-all — bulk drain of the DLQ.

Must claim the list by captured length (LRANGE + LTRIM), not clear the whole
key outright, so an entry dead-lettered *during* the call (appended after the
read) survives the drain. A per-entry enqueue failure must be pushed back
onto the DLQ, not lost.
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


class _FakeBulkDlqRedis:
    """Fake supporting exactly the ops requeue_all_dlq needs."""

    def __init__(self, dlq_entries: list[dict], *, fail_match_ids: set[str] | None = None) -> None:
        self.dlq: list[bytes] = [json.dumps(e).encode() for e in dlq_entries]
        self.enqueued: list[dict] = []
        self.ltrim_calls: list[tuple[int, int]] = []
        self._fail_match_ids = fail_match_ids or set()

    async def lrange(self, key: str, start: int, stop: int) -> list[bytes]:
        return list(self.dlq)

    async def ltrim(self, key: str, start: int, stop: int) -> bool:
        self.ltrim_calls.append((start, stop))
        # Mirror real LTRIM semantics for the (n, -1) shape this endpoint uses.
        if stop == -1:
            self.dlq = self.dlq[start:]
        return True

    async def rpush(self, key: str, value: bytes) -> int:
        self.dlq.append(value)
        return len(self.dlq)

    async def enqueue_job(self, function: str, *args: object, **kwargs: object) -> object:
        match_id = args[0] if args else None
        if match_id in self._fail_match_ids:
            raise RuntimeError("redis blip")
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


def test_requeue_all_drains_every_entry(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    fake = _FakeBulkDlqRedis(
        [
            {"matchId": "NA1_1", "error": "boom"},
            {"matchId": "NA1_2", "error": "boom"},
            {"matchId": "NA1_3", "error": "boom"},
        ]
    )
    monkeypatch.setattr(admin_mod, "_runtime", lambda: _FakeRuntime(fake))

    r = client.post("/api/v1/admin/dlq/requeue-all", headers={"X-Admin-Key": _KEY})

    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert body["requeued"] == 3
    assert body["failed"] == 0
    assert body["queue"] == "arena:priority"
    assert fake.dlq == []
    assert {j["args"][0] for j in fake.enqueued} == {"NA1_1", "NA1_2", "NA1_3"}
    # Every requeue gets a fresh, unique job id (not the plain discovery scheme).
    job_ids = [j["_job_id"] for j in fake.enqueued]
    assert len(set(job_ids)) == 3
    assert all(jid.startswith("process_match:NA1_") and ":requeue:" in jid for jid in job_ids)


def test_requeue_all_claims_by_captured_length_not_a_blind_clear(client, monkeypatch):
    """LTRIM must drop exactly the range read, not DEL the whole key — an
    entry appended after the read (a fresh dead-letter mid-drain) must not be
    silently discarded."""
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    fake = _FakeBulkDlqRedis([{"matchId": "NA1_1", "error": "boom"}])
    monkeypatch.setattr(admin_mod, "_runtime", lambda: _FakeRuntime(fake))

    r = client.post("/api/v1/admin/dlq/requeue-all", headers={"X-Admin-Key": _KEY})

    assert r.status_code == 200
    assert fake.ltrim_calls == [(1, -1)]


def test_requeue_all_puts_failed_entries_back_on_the_dlq(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    fake = _FakeBulkDlqRedis(
        [
            {"matchId": "NA1_1", "error": "boom"},
            {"matchId": "NA1_BAD", "error": "boom"},
        ],
        fail_match_ids={"NA1_BAD"},
    )
    monkeypatch.setattr(admin_mod, "_runtime", lambda: _FakeRuntime(fake))

    r = client.post("/api/v1/admin/dlq/requeue-all", headers={"X-Admin-Key": _KEY})

    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["requeued"] == 1
    assert body["failed"] == 1
    remaining = [json.loads(e) for e in fake.dlq]
    assert remaining == [{"matchId": "NA1_BAD", "error": "boom"}]


def test_requeue_all_on_empty_dlq_is_a_no_op(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    fake = _FakeBulkDlqRedis([])
    monkeypatch.setattr(admin_mod, "_runtime", lambda: _FakeRuntime(fake))

    r = client.post("/api/v1/admin/dlq/requeue-all", headers={"X-Admin-Key": _KEY})

    assert r.status_code == 200
    body = r.json()
    assert body == {
        "total": 0,
        "requeued": 0,
        "failed": 0,
        "queue": "arena:priority",
        "message": "0 partida(s) reenviada(s) para processamento.",
    }
    assert fake.ltrim_calls == []
