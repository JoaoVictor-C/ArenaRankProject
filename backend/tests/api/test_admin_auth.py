"""Auth-gate tests for the admin + tournament-admin surface (real app wiring).

Exercises the actual ``create_app`` wiring: the admin router is gated wholesale
and the four tournament ``/admin/...`` routes individually, while player-facing
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


def test_tournament_admin_detail_gated(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    # Same gate as create; an unknown id would otherwise 404 inside the handler,
    # so 401 here proves the gate runs before the service is ever reached.
    assert client.get("/api/v1/admin/tournament/does-not-exist").status_code == 401


def test_public_tournament_list_open(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    # A player-facing read must never be blocked by the admin gate (≠ 401), even
    # though it may degrade without a DB.
    assert client.get("/api/v1/tournaments").status_code != 401


# ---------------------------------------------------------------------------
# RBAC — per-operator scopes (arena/api/rbac.py). The env key above always
# resolves to "owner" (every scope) without touching the DB; these tests
# fake the operator lookup instead of requiring a live Postgres, so a
# per-role 403 is provable the same way test_admin_auth already proves a
# missing/wrong key is 401 — no DB dependency, same style as the rest of
# this file.
# ---------------------------------------------------------------------------


def _fake_operator(email: str, role: str, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _lookup(_provided: str) -> tuple[str, str]:
        return (email, role)

    monkeypatch.setattr("arena.api.rbac._lookup_operator", _lookup)


def test_operator_200_when_role_has_scope(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    _fake_operator("analista@arenarank.gg", "analyst", monkeypatch)
    # analyst has telemetry:read (every role does).
    r = client.get("/api/v1/admin/overview", headers={"X-Admin-Key": "operator-key-analyst"})
    assert r.status_code == 200


def test_operator_403_when_role_lacks_scope(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    _fake_operator("analista@arenarank.gg", "analyst", monkeypatch)
    # analyst has only telemetry:read — pausing a worker needs workers:write.
    r = client.post(
        "/api/v1/admin/workers/sweep/pause", headers={"X-Admin-Key": "operator-key-analyst"}
    )
    assert r.status_code == 403


def test_operator_moderator_can_dlq_write(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    _fake_operator("mod@arenarank.gg", "moderator", monkeypatch)
    # Never 403 for a scope the role does have — may still 503 without Redis.
    r = client.post(
        "/api/v1/admin/dlq/requeue-all", headers={"X-Admin-Key": "operator-key-moderator"}
    )
    assert r.status_code != 403


def test_operator_moderator_cannot_season_write(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    _fake_operator("mod@arenarank.gg", "moderator", monkeypatch)
    r = client.post(
        "/api/v1/admin/seasons/00000000-0000-0000-0000-000000000000/transition",
        json={},
        headers={"X-Admin-Key": "operator-key-moderator"},
    )
    assert r.status_code == 403


def test_integrity_override_needs_extra_scope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    # moderator has integrity:review but not integrity:override.
    _fake_operator("mod@arenarank.gg", "moderator", monkeypatch)
    r = client.post(
        "/api/v1/admin/integrity/some-event-id/review",
        json={"override": "eligible"},
        headers={"X-Admin-Key": "operator-key-moderator"},
    )
    assert r.status_code == 403


def test_operators_endpoint_needs_rbac_write(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    # Only "owner" has rbac:write — admin does not.
    _fake_operator("admin@arenarank.gg", "admin", monkeypatch)
    r = client.get("/api/v1/admin/operators", headers={"X-Admin-Key": "operator-key-admin"})
    assert r.status_code == 403


def test_operators_endpoint_ok_for_owner(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    # The env key is always "owner" — never resolved via the DB lookup.
    r = client.get("/api/v1/admin/operators/permissions", headers={"X-Admin-Key": _KEY})
    assert r.status_code == 200
    rows = r.json()
    assert any(row["scope"] == "rbac:write" for row in rows)


def test_audit_endpoint_needs_audit_read(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    # analyst has telemetry:read only — not audit:read.
    _fake_operator("analista@arenarank.gg", "analyst", monkeypatch)
    r = client.get("/api/v1/admin/audit", headers={"X-Admin-Key": "operator-key-analyst"})
    assert r.status_code == 403


def test_audit_endpoint_ok_for_owner(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    r = client.get("/api/v1/admin/audit", headers={"X-Admin-Key": _KEY})
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_player_search_ok_for_analyst(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    # Every role has telemetry:read. Never 403 for a scope the role does
    # have — may still 503 if the DB pool's connection is momentarily
    # unusable (same convention as the DLQ-write test above), which is a
    # pytest-asyncio-per-test-event-loop artifact of the shared cached
    # engine (arena/db/session.py), not a production concern (uvicorn runs
    # one persistent loop).
    _fake_operator("analista@arenarank.gg", "analyst", monkeypatch)
    r = client.get(
        "/api/v1/admin/players/search?q=ab", headers={"X-Admin-Key": "operator-key-analyst"}
    )
    assert r.status_code != 403


def test_player_moderation_needs_players_moderate(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    # analyst lacks players:moderate.
    _fake_operator("analista@arenarank.gg", "analyst", monkeypatch)
    r = client.patch(
        "/api/v1/admin/players/00000000-0000-0000-0000-000000000000/moderation",
        json={"banned": True},
        headers={"X-Admin-Key": "operator-key-analyst"},
    )
    assert r.status_code == 403


def test_player_moderation_ok_for_moderator(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "admin_api_key", _KEY)
    _fake_operator("mod@arenarank.gg", "moderator", monkeypatch)
    r = client.patch(
        "/api/v1/admin/players/00000000-0000-0000-0000-000000000000/moderation",
        json={"banned": True},
        headers={"X-Admin-Key": "operator-key-moderator"},
    )
    # Never 403 for a scope the role does have — 404 (unknown id) proves the
    # gate passed and the handler was reached, same pattern as the tournament
    # detail test above.
    assert r.status_code == 404
