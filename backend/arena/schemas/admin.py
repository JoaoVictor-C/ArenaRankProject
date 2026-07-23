"""Contract §6 — GET /api/v1/admin/overview response DTOs (DTO sample subsystem)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from arena.schemas.common import ArenaModel, Severity

WorkerStatus = Literal["ok", "warn", "down"]
RiotApiStatus = Literal["ok", "warn"]


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


class AdminOverview(ArenaModel):
    metrics: list[AdminMetric] = Field(default_factory=list)
    workers: list[AdminWorker] = Field(default_factory=list)
    queues: list[AdminQueue] = Field(default_factory=list)
    integrity: list[AdminIntegrityItem] = Field(default_factory=list)
    flags: list[AdminFlag] = Field(default_factory=list)
    dlq: list[AdminDlqItem] = Field(default_factory=list)
    season: AdminSeason
    riot_api: list[AdminRiotApi] = Field(default_factory=list)
