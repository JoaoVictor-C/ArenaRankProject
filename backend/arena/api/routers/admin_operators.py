"""Operator management — GET/POST /admin/operators, DELETE /admin/operators/{id},
GET /admin/operators/permissions (arena/api/rbac.py's scope matrix, read-only).

All gated `rbac:write` (only Owner has it by default — see ROLE_SCOPES). Mirrors
admin.py's lazy-import-per-handler convention so this router stays importable
even without SQLAlchemy installed; only `arena.api.rbac` (FastAPI + stdlib only)
is imported eagerly.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status

from arena.api.rbac import ROLES, hash_key, key_prefix, permission_matrix, record_audit, require_scope
from arena.core.logging import get_logger
from arena.schemas.admin import (
    OperatorCreateRequest,
    OperatorCreateResult,
    OperatorInfo,
    OperatorRevokeResult,
    OperatorRoleName,
    PermissionRow,
)

_log = get_logger("arena.api.admin_operators")

router = APIRouter(
    prefix="/admin/operators",
    tags=["admin"],
    dependencies=[Depends(require_scope("rbac:write"))],
)


def _db_unavailable(action: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Camada de dados indisponível para {action}.",
    )


@router.get(
    "/permissions",
    response_model=list[PermissionRow],
    response_model_by_alias=True,
    summary="Matriz de permissões por papel",
)
async def list_permissions() -> list[PermissionRow]:
    return [
        PermissionRow(
            scope=row["scope"],
            label=row["label"],
            roles=cast("list[OperatorRoleName]", row["roles"]),
        )
        for row in permission_matrix()
    ]


@router.get(
    "",
    response_model=list[OperatorInfo],
    response_model_by_alias=True,
    summary="Listar operadores",
)
async def list_operators() -> list[OperatorInfo]:
    try:
        from sqlalchemy import select

        from arena.db import models as md
        from arena.db.session import get_sessionmaker

        async with get_sessionmaker()() as session:
            rows = (
                await session.execute(
                    select(md.AdminOperator).order_by(md.AdminOperator.created_at)
                )
            ).scalars().all()
    except Exception as exc:  # pragma: no cover - DB unreachable / not migrated
        raise _db_unavailable("listar operadores") from exc

    return [
        OperatorInfo(
            id=str(row.id),
            email=row.email,
            role=row.role.value,
            key_prefix=row.key_prefix,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            revoked=row.revoked_at is not None,
        )
        for row in rows
    ]


@router.post(
    "",
    response_model=OperatorCreateResult,
    status_code=status.HTTP_201_CREATED,
    response_model_by_alias=True,
    summary="Criar operador",
)
async def create_operator(request: Request, body: OperatorCreateRequest) -> OperatorCreateResult:
    if body.role not in ROLES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Papel inválido.")

    # Random, high-entropy, never user-chosen — shown to the caller exactly
    # once, same "shown once" pattern as tournament accessKey.
    plaintext = secrets.token_hex(24)

    try:
        from arena.db import models as md
        from arena.db.session import get_sessionmaker

        async with get_sessionmaker()() as session:
            operator = md.AdminOperator(
                email=body.email,
                role=md.OperatorRole(body.role),
                api_key_hash=hash_key(plaintext),
                key_prefix=key_prefix(plaintext),
            )
            session.add(operator)
            await session.commit()
            await session.refresh(operator)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - DB unreachable / not migrated / dup email
        raise _db_unavailable("criar operador") from exc

    _log.info(
        "admin.operator.created",
        operatorId=str(operator.id),
        email=operator.email,
        role=operator.role.value,
    )
    await record_audit(
        request, action="operator.created", target=operator.email, role=operator.role.value
    )
    return OperatorCreateResult(
        id=str(operator.id),
        email=operator.email,
        role=operator.role.value,
        api_key=plaintext,
        message="Operador criado. Copie a chave agora — ela não será mostrada novamente.",
    )


@router.delete(
    "/{operator_id}",
    response_model=OperatorRevokeResult,
    response_model_by_alias=True,
    summary="Revogar operador",
)
async def revoke_operator(
    request: Request,
    operator_id: str = Path(..., description="UUID do operador"),
) -> OperatorRevokeResult:
    try:
        from sqlalchemy import select

        from arena.db import models as md
        from arena.db.session import get_sessionmaker

        async with get_sessionmaker()() as session:
            operator = (
                await session.execute(
                    select(md.AdminOperator).where(md.AdminOperator.id == operator_id)
                )
            ).scalar_one_or_none()
            if operator is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Operador não encontrado."
                )
            operator.revoked_at = datetime.now(UTC)
            email = operator.email
            await session.commit()
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - DB unreachable / not migrated
        raise _db_unavailable("revogar operador") from exc

    _log.info("admin.operator.revoked", operatorId=operator_id)
    await record_audit(request, action="operator.revoked", target=email)
    return OperatorRevokeResult(id=operator_id, message="Operador revogado.")


__all__ = ["router"]
