"""Admin authentication — a shared-key gate for operator/admin endpoints.

There is no user/identity system yet (SSO/RBAC is a later slice). Until then,
every admin + tournament-admin endpoint MUST be gated so the operator surface
(season create/transition, DLQ requeue/discard, integrity overrides, tournament
provisioning/results) is not world-callable. This is a single shared **admin API
key** check:

* the key is read from ``settings.admin_api_key`` (env ``ADMIN_API_KEY``);
* clients send it as ``X-Admin-Key: <key>`` or ``Authorization: Bearer <key>``;
* the comparison is constant-time (:func:`secrets.compare_digest`);
* **fail closed** — if no key is configured the gate denies every request (503)
  rather than silently allowing access.

Swap this for real JWT/RBAC when the identity slice lands; the dependency seam
(``Depends(require_admin)``) stays the same so call sites don't change.
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from arena.core.config import settings

#: Header carrying the shared admin key (case-insensitive on the wire).
ADMIN_KEY_HEADER = "X-Admin-Key"


def _extract_key(x_admin_key: str | None, authorization: str | None) -> str | None:
    """Pull the admin key from the dedicated header or a Bearer token."""
    if x_admin_key:
        return x_admin_key
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


async def require_admin(
    x_admin_key: str | None = Header(default=None, alias=ADMIN_KEY_HEADER),
    authorization: str | None = Header(default=None),
) -> None:
    """FastAPI dependency authorizing admin/operator requests.

    Raises 503 when admin access is not configured (fail closed) and 401 when the
    key is missing or wrong. Returns ``None`` (authorized) otherwise. Mounted via
    ``dependencies=[Depends(require_admin)]`` on the admin router / routes.
    """
    configured = settings.admin_api_key
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Acesso administrativo não está configurado (defina ADMIN_API_KEY).",
        )
    provided = _extract_key(x_admin_key, authorization)
    if not provided or not secrets.compare_digest(provided, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais administrativas inválidas ou ausentes.",
            headers={"WWW-Authenticate": "Bearer"},
        )


__all__ = ["require_admin", "ADMIN_KEY_HEADER"]
