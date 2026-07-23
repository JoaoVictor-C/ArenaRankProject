"""Auth-gate tests for the admin + tournament-admin surface (real app wiring).

Exercises the actual ``create_app`` wiring: the admin router is gated wholesale
and the three tournament ``/admin/...`` routes individually, while player-facing
tournament reads stay open. Uses the handlers' representative-data fallback so no
live DB/Redis is required.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arena.api.app import create_app
from arena.core.config import settings

_KEY = "s3cret-admin-key"


@pytest.fixture
def client() -> TestClient:
    # raise_server_exceptions=False: a handler that fails on a missing DB (e.g. the
    # public tournaments route with no Postgres) returns 500 instead of propagating,
    # so the auth-gate assertions (== 401 / != 401) stay meaningful offline.
    return TestClient(create_app(), raise_server_exceptions=False)


def test_admin_503_when_unconfigured(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_api_key", "")  # fail closed
    assert client.get("/api/v1/admin/overview").status_code == 503


def test_admin_401_without_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    assert client.get("/api/v1/admin/overview").status_code == 401


def test_admin_401_with_wrong_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    r = client.get("/api/v1/admin/overview", headers={"X-Admin-Key": "wrong"})
    assert r.status_code == 401


def test_admin_ok_with_header_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    r = client.get("/api/v1/admin/overview", headers={"X-Admin-Key": _KEY})
    assert r.status_code == 200  # passes the gate (data degrades to representative)


def test_admin_ok_with_bearer_token(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    r = client.get("/api/v1/admin/overview", headers={"Authorization": f"Bearer {_KEY}"})
    assert r.status_code == 200


def test_tournament_admin_create_gated(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    # The admin gate runs before body validation, so a keyless POST is 401 (not 422).
    assert client.post("/api/v1/admin/tournaments", json={}).status_code == 401


def test_public_tournament_list_open(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    # A player-facing read must never be blocked by the admin gate (≠ 401), even
    # though it may degrade without a DB.
    assert client.get("/api/v1/tournaments").status_code != 401
