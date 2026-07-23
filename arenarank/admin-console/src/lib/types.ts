/* ============================================================
   Wire types (camelCase) + the app's normalized telemetry shape.
   Mirrors the FastAPI DTOs:
     - LiveSnapshot   (arena/api/routers/admin_telemetry.py)
     - AdminOverview  (arena/schemas/admin.py)
   ============================================================ */

export type Severity = "info" | "warn" | "critical";

/* ---- GET /admin/workers/live ---- */
export interface LiveWorker {
  name: string;
  label: string;
  enabled: boolean;
  paused: boolean;
  active: boolean;
  tickLockTtl: number;
  cursor: number | null;
  feeds: string | null;
  pending: number;
  attemptsTracked: number | null;
  intervalMinutes: number;
  description: string;
}
export interface LiveQueue {
  name: string;
  depth: number;
  kind: string;
  label: string;
}
export interface LivePipeline {
  priorityQueue: number;
  standardQueue: number;
  dlq: number;
  sweepPendingPriority: number;
  sweepPendingStandard: number;
  sweepAttemptsTracked: number;
  topPlayersPool: number;
  totalBacklog: number;
}
export interface LiveSnapshot {
  ts: string;
  redisAvailable: boolean;
  workers: LiveWorker[];
  queues: LiveQueue[];
  pipeline: LivePipeline;
}

/* ---- GET /admin/overview ---- */
export interface AdminMetric {
  key: string;
  label: string;
  value: string;
  trend?: number | null;
}
export interface AdminWorker {
  name: string;
  status: "ok" | "warn" | "down";
  load: number;
}
export interface AdminQueue {
  name: string;
  depth: number;
  rate: string;
}
export interface AdminIntegrityItem {
  id: string;
  player: string;
  reason: string;
  severity: Severity;
  ts: string;
}
export interface AdminFlag {
  id: string;
  player: string;
  flag: string;
  severity: Severity;
}
export interface AdminDlqItem {
  matchId: string;
  attempts: number;
  reason: string;
  ts: string;
}
export interface AdminSeason {
  current: number;
  state: string;
  startedAt: string;
  config: Record<string, string>;
}
export interface AdminRiotApi {
  name: string;
  status: "ok" | "warn";
  usage: string;
}
export interface AdminOverview {
  metrics: AdminMetric[];
  workers: AdminWorker[];
  queues: AdminQueue[];
  integrity: AdminIntegrityItem[];
  flags: AdminFlag[];
  dlq: AdminDlqItem[];
  season: AdminSeason;
  riotApi: AdminRiotApi[];
}

/* ---- Normalized shape consumed by the UI (built from either source) ---- */
export type WorkerHealth = "active" | "idle" | "paused" | "warn" | "down";

export interface NormWorker {
  name: string;
  label: string;
  paused: boolean;
  active: boolean;
  health: WorkerHealth;
  tickLockTtl: number;
  cursor: number | null;
  pending: number | null;
  attemptsTracked: number | null;
  intervalMinutes: number | null;
  feeds: string | null;
  description: string | null;
  controllable: boolean;
  load: number | null;
}

export interface NormQueue {
  name: string;
  label: string;
  depth: number;
  kind: string;
}

export interface NormPipeline {
  priorityQueue: number;
  standardQueue: number;
  dlq: number;
  sweepPendingPriority: number | null;
  sweepPendingStandard: number | null;
  sweepAttemptsTracked: number | null;
  topPlayersPool: number | null;
  totalBacklog: number;
}

export interface Telemetry {
  ts: string;
  source: "live" | "overview";
  redisAvailable: boolean | null;
  workers: NormWorker[];
  queues: NormQueue[];
  pipeline: NormPipeline;
}
