"""Admin worker control (pause/resume) + player selection endpoints."""
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


class _FakeRedis:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def set(self, key, value, **kw):
        self.calls.append(("set", key, value))
        return True

    async def delete(self, *keys):
        self.calls.append(("delete", keys))
        return 1

    async def aclose(self):
        return None


class _FakeRuntime:
    def __init__(self, redis) -> None:
        self.redis_factory = lambda: redis
        self.sessionmaker = None
        self.season_service = None


def _patch_runtime(monkeypatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(admin_mod, "_runtime", lambda: _FakeRuntime(fake))
    return fake


def test_pause_worker_sets_flag(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    fake = _patch_runtime(monkeypatch)
    r = client.post("/api/v1/admin/workers/sweep/pause", headers={"X-Admin-Key": _KEY})
    assert r.status_code == 200
    assert ("set", "arena:worker:enabled:sweep", "0") in fake.calls


def test_resume_worker_deletes_flag(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    fake = _patch_runtime(monkeypatch)
    r = client.post("/api/v1/admin/workers/priority_sweep/resume", headers={"X-Admin-Key": _KEY})
    assert r.status_code == 200
    assert ("delete", ("arena:worker:enabled:priority_sweep",)) in fake.calls


def test_unknown_worker_404(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    _patch_runtime(monkeypatch)
    r = client.post("/api/v1/admin/workers/bogus/pause", headers={"X-Admin-Key": _KEY})
    assert r.status_code == 404


def test_pause_requires_admin_key(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    r = client.post("/api/v1/admin/workers/sweep/pause")  # no key
    assert r.status_code == 401


# --- player selection: mocked async session (no DB, deterministic) ----------


class _FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeSession:
    def __init__(self, player):
        self._player = player
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def execute(self, _stmt):
        return _FakeResult(self._player)

    async def commit(self):
        self.committed = True


class _FakeRuntimeDb:
    def __init__(self, player):
        self.redis_factory = None
        self.season_service = None
        self.sessionmaker = lambda: _FakeSession(player)


class _Player:
    def __init__(self):
        self.is_selected = False


def test_select_existing_player_updates(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    player = _Player()
    monkeypatch.setattr(admin_mod, "_runtime", lambda: _FakeRuntimeDb(player))
    r = client.patch(
        "/api/v1/admin/players/abc-123/select",
        headers={"X-Admin-Key": _KEY},
        json={"isSelected": True},
    )
    assert r.status_code == 200
    assert r.json()["isSelected"] is True
    assert player.is_selected is True  # handler mutated + would commit


def test_select_nonexistent_player_404(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    monkeypatch.setattr(admin_mod, "_runtime", lambda: _FakeRuntimeDb(None))
    r = client.patch(
        "/api/v1/admin/players/00000000-0000-0000-0000-000000000000/select",
        headers={"X-Admin-Key": _KEY},
        json={"isSelected": True},
    )
    assert r.status_code == 404
