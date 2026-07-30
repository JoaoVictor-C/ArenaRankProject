"""Contract §6 — GET /api/v1/admin/overview response DTOs (DTO sample subsystem)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from arena.schemas.common import ArenaModel, AvatarColors, Severity

WorkerStatus = Literal["ok", "warn", "down"]
RiotApiStatus = Literal["ok", "warn"]
OperatorRoleName = Literal["owner", "admin", "moderator", "analyst", "support"]


class AdminMetric(ArenaModel):
    key: str
    label: str
    value: str
    trend: float | None = None


class AdminWorker(ArenaModel):
    name: str
    status: WorkerStatus
    load: float


class AdminQueue(ArenaModel):
    name: str
    depth: int
    rate: str


class AdminIntegrityItem(ArenaModel):
    id: str
    player: str
    reason: str
    severity: Severity
    ts: str


class AdminFlag(ArenaModel):
    id: str
    player: str
    flag: str
    severity: Severity


class AdminDlqItem(ArenaModel):
    match_id: str
    attempts: int
    reason: str
    ts: str


class AdminSeason(ArenaModel):
    current: int
    state: str
    started_at: str
    config: dict[str, str] = Field(default_factory=dict)


class AdminRiotApi(ArenaModel):
    name: str
    status: RiotApiStatus
    usage: str


class AdminDailyMatchStat(ArenaModel):
    """One calendar day's match volume + whatever stats the `matches` row
    already carries (duration, mode split, integrity flags). No fabricated
    fields — a stat we can't reliably compute (e.g. per-day DLQ failures,
    which aren't timestamped in a way that survives a requeue) is simply
    absent rather than guessed."""

    date: str  # YYYY-MM-DD (UTC)
    matches: int
    avg_duration_seconds: float | None = None
    duos: int = 0
    trios: int = 0
    with_integrity_flags: int = 0


class AdminDailyMatches(ArenaModel):
    ts: str
    days: list[AdminDailyMatchStat] = Field(default_factory=list)


class AdminOverview(ArenaModel):
    metrics: list[AdminMetric] = Field(default_factory=list)
    workers: list[AdminWorker] = Field(default_factory=list)
    queues: list[AdminQueue] = Field(default_factory=list)
    integrity: list[AdminIntegrityItem] = Field(default_factory=list)
    flags: list[AdminFlag] = Field(default_factory=list)
    dlq: list[AdminDlqItem] = Field(default_factory=list)
    season: AdminSeason
    riot_api: list[AdminRiotApi] = Field(default_factory=list)


# ---- RBAC — /admin/operators (arena/api/rbac.py, arena/api/routers/admin_operators.py) ----


class OperatorInfo(ArenaModel):
    id: str
    email: str
    role: OperatorRoleName
    key_prefix: str
    created_at: datetime
    last_seen_at: datetime | None = None
    revoked: bool = False


class OperatorCreateRequest(ArenaModel):
    email: str
    role: OperatorRoleName


class OperatorCreateResult(ArenaModel):
    id: str
    email: str
    role: OperatorRoleName
    api_key: str
    message: str


class OperatorRevokeResult(ArenaModel):
    id: str
    message: str


class PermissionRow(ArenaModel):
    scope: str
    label: str
    roles: list[OperatorRoleName]


# ---- Audit log — GET /admin/audit (arena/api/rbac.py::record_audit) ----


class AuditEventInfo(ArenaModel):
    id: str
    occurred_at: datetime
    actor: str
    action: str
    kind: str
    target: str | None = None
    source_ip: str | None = None
    result: str


# ---- Player search + moderation — arena/api/routers/admin_players.py ----


class PlayerSearchRow(ArenaModel):
    id: str
    riot_id: str
    puuid: str
    region: str | None = None
    cr: int | None = None
    active: bool
    banned: bool
    shadowbanned: bool
    restricted: bool
    flag_count: int
    avatar: AvatarColors


class PlayerModerationRequest(ArenaModel):
    banned: bool | None = None
    shadowbanned: bool | None = None
    restricted: bool | None = None
    flag_type: str | None = Field(default=None, description="Tipo da flag anexada (opcional).")
    note: str | None = Field(default=None, max_length=500)


class PlayerModerationResult(ArenaModel):
    player_id: str
    banned: bool
    shadowbanned: bool
    restricted: bool
    message: str


# ---- Refill de temporada — arena/api/routers/admin_ingest.py ----


class IngestStatus(ArenaModel):
    """Estado do refill de uma temporada (console de operação).

    ``mode`` é ``catching_up`` durante um refill — descoberta continua, mas nada
    é avaliado na chegada: as partidas ficam em ``match_backlog`` e são avaliadas
    depois em ordem cronológica estrita. ``live`` é o regime normal.
    """

    season_id: str
    mode: str  # catching_up | live
    staged: int  # partidas estacionadas aguardando avaliação ordenada
    oldest_staged_at: str | None = None  # ISO; o começo da fila cronológica
    frontier_pending: int = 0  # puuids aguardando import de histórico
    frontier_done: int = 0  # jogadores já conhecidos
    saturated_at: str | None = None  # quando a descoberta parou de crescer
    coverage_pct: float | None = None  # estimativa da última amostragem do audit
    coverage_at: str | None = None
    # Piso do replay incremental: há cauda fora de ordem esperando reprocessamento.
    replay_floor: str | None = None
