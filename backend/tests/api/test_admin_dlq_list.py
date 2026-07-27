"""GET /admin/dlq must read the fields `processor._dead_letter` actually
writes (`tries`, `deadLetteredAt` epoch seconds) — a prior key-name mismatch
(`attempts`, `ts`/`failedAt`) meant every row read back as "0x" attempts and
"just now", regardless of the real values, since `_live_dlq_items` was
looking for keys that never existed on a real dead-letter entry.
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
    def __init__(self, dlq_entries: list[dict]) -> None:
        self.dlq: list[bytes] = [json.dumps(e).encode() for e in dlq_entries]

    async def lrange(self, key: str, start: int, stop: int) -> list[bytes]:
        return list(self.dlq)

    async def aclose(self) -> None:
        return None


class _FakeRuntime:
    def __init__(self, redis) -> None:
        self.redis_factory = lambda: redis


def test_list_dlq_reads_real_tries_and_timestamp(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    # Exactly the shape processor._dead_letter writes.
    fake = _FakeDlqRedis(
        [
            {
                "matchId": "BR1_3246371392",
                "error": "Circuit 'riot' is open; retry in ~17.2s",
                "tries": 3,
                "deadLetteredAt": 1_700_000_000.0,
            }
        ]
    )
    monkeypatch.setattr(admin_mod, "_runtime", lambda: _FakeRuntime(fake))

    r = client.get("/api/v1/admin/dlq", headers={"X-Admin-Key": _KEY})

    assert r.status_code == 200
    [item] = r.json()
    assert item["matchId"] == "BR1_3246371392"
    assert item["attempts"] == 3  # not 0 — the old key name never matched
    assert "Circuit 'riot' is open" in item["reason"]
    # 1_700_000_000s == 2023-11-14T22:13:20Z — not "now".
    assert item["ts"].startswith("2023-11-14")


def test_list_dlq_degrades_gracefully_without_deadletteredat(client, monkeypatch):
    """A hypothetical legacy entry with neither `deadLetteredAt` nor `tries`
    must not crash — it just falls back to 0 attempts and "now", the same
    degraded behavior as before this fix (never worse)."""
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    fake = _FakeDlqRedis([{"matchId": "BR1_LEGACY", "error": "boom"}])
    monkeypatch.setattr(admin_mod, "_runtime", lambda: _FakeRuntime(fake))

    r = client.get("/api/v1/admin/dlq", headers={"X-Admin-Key": _KEY})

    assert r.status_code == 200
    [item] = r.json()
    assert item["attempts"] == 0
    assert item["ts"]  # some ISO-ish string, not a crash
