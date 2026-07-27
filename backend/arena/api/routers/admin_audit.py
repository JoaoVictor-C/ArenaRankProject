"""GET /admin/audit — read the trail arena/api/rbac.py::record_audit writes.

Self-gated `audit:read` (Owner + Admin by default — see rbac.ROLE_SCOPES).
Reused, unfiltered and newest-first, by the Activity Feed page too (same
data, timeline-styled on the frontend instead of table-styled).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from arena.api.rbac import audit_kind, require_scope
from arena.core.logging import get_logger
from arena.schemas.admin import AuditEventInfo

_log = get_logger("arena.api.admin_audit")

router = APIRouter(
    prefix="/admin/audit",
    tags=["admin"],
    dependencies=[Depends(require_scope("audit:read"))],
)


def _db_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Camada de dados indisponível para o registro de auditoria.",
    )


@router.get(
    "",
    response_model=list[AuditEventInfo],
    response_model_by_alias=True,
    summary="Registro de auditoria (ações privilegiadas)",
)
async def list_audit_events(
    kind: str | None = Query(
        default=None,
        description="Filtra por categoria (workers|moderacao|dlq|temporada|campeonatos|acesso).",
    ),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[AuditEventInfo]:
    try:
        from sqlalchemy import select

        from arena.db import models as md
        from arena.db.session import get_sessionmaker

        async with get_sessionmaker()() as session:
            rows = (
                await session.execute(
                    select(md.AdminAuditEvent)
                    .order_by(md.AdminAuditEvent.occurred_at.desc())
                    .limit(limit)
                )
            ).scalars().all()
    except Exception as exc:  # pragma: no cover - DB unreachable / not migrated
        _log.warning("admin.audit.list_failed", exc_info=True)
        raise _db_unavailable() from exc

    events = [
        AuditEventInfo(
            id=str(row.id),
            occurred_at=row.occurred_at,
            actor=row.actor,
            action=row.action,
            kind=audit_kind(row.action),
            target=row.target,
            source_ip=row.source_ip,
            result=row.result,
        )
        for row in rows
    ]
    if kind:
        events = [e for e in events if e.kind == kind]
    return events


__all__ = ["router"]
