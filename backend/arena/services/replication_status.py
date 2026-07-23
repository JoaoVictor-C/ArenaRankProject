"""Replica-lag probe (T3.1 — observabilidade do read path desacoplado).

Na réplica (EC2), ``pg_stat_subscription.latest_end_time`` é o instante do
último apply recebido do primário. A idade disso é o *lag de replicação* — o
quão "velhos" estão os dados que o site serve. Exposto no ``/healthz`` (gate
``REPLICA_LAG_CHECK=true``) e usado para tornar honesto o ``updatedAt`` /
``/meta/last-update`` que a UI já consome.

Fora da réplica (dev, primário, DB sem subscriptions) a view existe e vem
vazia → ``ReplicaSync(None, None)`` e os chamadores degradam para o
comportamento antigo (``now()``). Falha de DB nunca propaga: probe é
observabilidade, não disponibilidade.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from arena.core.logging import get_logger

_log = get_logger("arena.services.replication")


@dataclass(slots=True)
class ReplicaSync:
    """Estado de sync da réplica. Campos ``None`` = sem subscription/indisponível."""

    last_sync_at: datetime | None
    lag_seconds: float | None


async def replica_sync_status(
    session: AsyncSession, *, now: datetime | None = None
) -> ReplicaSync:
    """Read the newest ``latest_end_time`` across subscriptions, with lag.

    Emite o log estruturado ``replication.lag`` quando há subscription ativa.
    Nunca levanta: qualquer erro degrada para ``ReplicaSync(None, None)``.
    """
    try:
        result = await session.execute(
            text("SELECT max(latest_end_time) FROM pg_stat_subscription")
        )
        ts = result.scalar()
    except Exception:
        _log.warning("replication.lag_probe_failed", exc_info=True)
        return ReplicaSync(None, None)

    if ts is None:
        return ReplicaSync(None, None)

    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    lag = ((now or datetime.now(UTC)) - ts).total_seconds()
    _log.info("replication.lag", lag_seconds=round(lag, 3), last_sync_at=ts.isoformat())
    return ReplicaSync(last_sync_at=ts, lag_seconds=lag)


__all__ = ["ReplicaSync", "replica_sync_status"]
