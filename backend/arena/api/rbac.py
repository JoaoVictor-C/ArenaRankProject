"""Scope-based RBAC for the admin API — supersedes the old blanket ``require_admin``
gate (``arena/api/security.py``) with per-route ``require_scope(scope)`` checks
backed by the ``admin_operators`` table (``arena/db/models.py::AdminOperator``).

The env ``ADMIN_API_KEY`` (``arena/core/config.py``) stays a permanent,
non-revocable **Owner** bootstrap identity: it satisfies every scope and is
checked with a constant-time comparison directly against the header, never
looked up in the DB. This is deliberate, not a shortcut — it's what keeps
existing deployments (and ``tests/api/test_admin_auth.py``, which only ever
exercises this path) working unchanged after the retrofit. Per-operator keys
are the real multi-user path: hashed at rest (SHA-256 over a random
high-entropy token — not a slow password hash, since these are never
user-chosen), looked up by exact hash match. Any DB error during that lookup
is treated as "no operator found" (fail-closed, never fail-open) so a
briefly-unreachable Postgres degrades to a 401, not a 500.

Resolved identity is stashed on ``request.state`` (``actor``, ``role``,
``scopes``) for the audit-log hook (a later phase) to read without
re-resolving the key.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from fastapi import Header, HTTPException, Request, status

from arena.api.security import ADMIN_KEY_HEADER, _extract_key
from arena.core.config import settings
from arena.core.logging import get_logger

_log = get_logger("arena.api.rbac")

#: The full permission surface. Two of these (``players:moderate``,
#: ``audit:read``) have no row in the original design's 8-scope matrix — they
#: cover Player Search/moderation and the Audit Log, features the design
#: specified but that didn't exist as gated routes yet.
SCOPES: tuple[str, ...] = (
    "telemetry:read",
    "workers:write",
    "dlq:write",
    "integrity:review",
    "integrity:override",
    "tournaments:write",
    "season:write",
    "rbac:write",
    "players:moderate",
    "audit:read",
)

ROLES: tuple[str, ...] = ("owner", "admin", "moderator", "analyst", "support")

#: Role -> granted scopes. Mirrors the design's permission matrix exactly for
#: the 8 original scopes; the 2 additions follow the closest existing row
#: (players:moderate mirrors dlq:write's Owner/Admin/Moderador row; audit:read
#: mirrors integrity:override's Owner/Admin row — audit trails are sensitive).
ROLE_SCOPES: dict[str, frozenset[str]] = {
    "owner": frozenset(SCOPES),
    "admin": frozenset(
        {
            "telemetry:read",
            "workers:write",
            "dlq:write",
            "integrity:review",
            "integrity:override",
            "tournaments:write",
            "players:moderate",
            "audit:read",
        }
    ),
    "moderator": frozenset(
        {"telemetry:read", "dlq:write", "integrity:review", "players:moderate"}
    ),
    "analyst": frozenset({"telemetry:read"}),
    "support": frozenset({"telemetry:read"}),
}

#: Display label per scope, in matrix-row order — the single source of truth
#: the Roles & Permissions page reads (via `permission_matrix()`) instead of
#: duplicating this table client-side.
SCOPE_LABELS: dict[str, str] = {
    "telemetry:read": "Ver telemetria e métricas",
    "workers:write": "Pausar / retomar workers",
    "dlq:write": "Reprocessar e descartar DLQ",
    "integrity:review": "Revisar fila de integridade",
    "integrity:override": "Aplicar override de partida",
    "tournaments:write": "Provisionar campeonatos",
    "season:write": "Transicionar temporada",
    "rbac:write": "Gerir papéis e chaves",
    "players:moderate": "Moderar jogadores (ban / flag)",
    "audit:read": "Ver registro de auditoria",
}


class PermissionMatrixRow(TypedDict):
    scope: str
    label: str
    roles: list[str]


def permission_matrix() -> list[PermissionMatrixRow]:
    """The scope x role grid, ready for `PermissionRow` (arena/schemas/admin.py)."""
    return [
        {
            "scope": scope,
            "label": SCOPE_LABELS[scope],
            "roles": [role for role in ROLES if scope in ROLE_SCOPES[role]],
        }
        for scope in SCOPES
    ]


def hash_key(key: str) -> str:
    """Deterministic digest for a random high-entropy operator key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def key_prefix(key: str) -> str:
    """Last chars of the plaintext key, for display only (never the full key)."""
    return key[-6:] if len(key) > 6 else key


async def _lookup_operator(provided: str) -> tuple[str, str] | None:
    """Resolve a per-operator key to (email, role). ``None`` on no match OR any
    DB error — auth failures must degrade to "deny", never to "allow"."""
    try:
        from sqlalchemy import select

        from arena.db import models as md
        from arena.db.session import get_sessionmaker

        async with get_sessionmaker()() as session:
            operator = (
                await session.execute(
                    select(md.AdminOperator).where(
                        md.AdminOperator.api_key_hash == hash_key(provided),
                        md.AdminOperator.revoked_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
    except Exception:  # pragma: no cover - DB unreachable / not migrated
        return None
    if operator is None:
        return None
    return operator.email, operator.role.value


def require_scope(scope: str) -> Callable[..., Awaitable[None]]:
    """FastAPI dependency factory: authorize a request needing ``scope``."""

    async def _dep(
        request: Request,
        x_admin_key: str | None = Header(default=None, alias=ADMIN_KEY_HEADER),
        authorization: str | None = Header(default=None),
    ) -> None:
        configured = settings.admin_api_key
        if not configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Acesso administrativo não está configurado (defina ADMIN_API_KEY).",
            )

        provided = _extract_key(x_admin_key, authorization)
        if not provided:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credenciais administrativas inválidas ou ausentes.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if secrets.compare_digest(provided, configured):
            request.state.actor = "env:ADMIN_API_KEY"
            request.state.role = "owner"
            request.state.scopes = ROLE_SCOPES["owner"]
            return

        resolved = await _lookup_operator(provided)
        if resolved is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credenciais administrativas inválidas ou ausentes.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        actor, role = resolved
        scopes = ROLE_SCOPES.get(role, frozenset())
        request.state.actor = actor
        request.state.role = role
        request.state.scopes = scopes

        if scope not in scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Este operador não tem permissão para esta ação.",
            )

    return _dep


#: action prefix (before the first ".") -> audit-log filter chip. Matches the
#: design's chips (Tudo/Workers/Moderação/DLQ/Acesso) plus two the design's
#: mock data didn't happen to cover (Temporada, Campeonatos) — real,
#: audit-worthy action families in this system.
_KIND_PREFIXES: dict[str, str] = {
    "worker": "workers",
    "integrity": "moderacao",
    "player": "moderacao",
    "dlq": "dlq",
    "season": "temporada",
    "tournament": "campeonatos",
    "operator": "acesso",
}

KIND_LABELS: dict[str, str] = {
    "workers": "Workers",
    "moderacao": "Moderação",
    "dlq": "DLQ",
    "temporada": "Temporada",
    "campeonatos": "Campeonatos",
    "acesso": "Acesso",
}


def audit_kind(action: str) -> str:
    """Bucket an audit action (e.g. "worker.paused") into a UI filter kind."""
    prefix = action.split(".", 1)[0]
    return _KIND_PREFIXES.get(prefix, "outro")


async def record_audit(
    request: Request,
    *,
    action: str,
    target: str | None = None,
    result: str = "ok",
    **metadata: Any,
) -> None:
    """Stage + commit one audit-trail row, in its own short transaction.

    Independent of whatever DB/Redis transaction the mutation itself used
    (several admin actions — DLQ/worker/queue ops — only ever touch Redis and
    have no DB session to piggyback on). Never raises: a logging failure must
    never break the real admin action it's recording. Actor comes off
    ``request.state.actor``, set by ``require_scope`` earlier in the same
    request.
    """
    try:
        from arena.db import models as md
        from arena.db.session import get_sessionmaker

        actor = getattr(request.state, "actor", "unknown")
        source_ip = request.client.host if request.client else None
        async with get_sessionmaker()() as session:
            session.add(
                md.AdminAuditEvent(
                    actor=actor,
                    action=action,
                    target=target,
                    source_ip=source_ip,
                    result=result,
                    metadata_=dict(metadata),
                )
            )
            await session.commit()
    except Exception:  # pragma: no cover - audit logging must never break the action
        _log.warning("rbac.audit.write_failed", action=action, exc_info=True)


__all__ = [
    "SCOPES",
    "ROLES",
    "ROLE_SCOPES",
    "require_scope",
    "hash_key",
    "key_prefix",
    "permission_matrix",
    "audit_kind",
    "KIND_LABELS",
    "record_audit",
]
