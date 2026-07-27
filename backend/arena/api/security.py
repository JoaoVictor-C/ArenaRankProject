"""Shared admin-key extraction primitive.

The actual authorization gate lives in :mod:`arena.api.rbac`
(``require_scope``), which replaced the old blanket ``require_admin`` — see
that module's docstring for the full RBAC design (per-operator keys +
scopes, with ``settings.admin_api_key`` kept as a permanent, non-revocable
"Owner" bootstrap identity). This module only holds the header-parsing bit
both the env-key check and the per-operator lookup share.
"""

from __future__ import annotations

#: Header carrying the shared admin key (case-insensitive on the wire).
ADMIN_KEY_HEADER = "X-Admin-Key"


def _extract_key(x_admin_key: str | None, authorization: str | None) -> str | None:
    """Pull the admin key from the dedicated header or a Bearer token."""
    if x_admin_key:
        return x_admin_key
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


__all__ = ["ADMIN_KEY_HEADER", "_extract_key"]
