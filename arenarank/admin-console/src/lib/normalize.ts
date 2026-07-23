/* Build the UI's normalized Telemetry from either data source. */
import type {
  AdminOverview,
  LiveSnapshot,
  NormQueue,
  NormWorker,
  Telemetry,
  WorkerHealth,
} from "./types";

/** Workers that expose pause/resume + priority controls (Redis enable flag). */
export const CONTROLLABLE = new Set(["sweep", "priority_sweep", "bulk_processor"]);

function liveHealth(paused: boolean, active: boolean): WorkerHealth {
  if (paused) return "paused";
  if (active) return "active";
  return "idle";
}

export function fromLive(snap: LiveSnapshot): Telemetry {
  const workers: NormWorker[] = snap.workers.map((w) => ({
    name: w.name,
    label: w.label,
    paused: w.paused,
    active: w.active,
    health: liveHealth(w.paused, w.active),
    tickLockTtl: w.tickLockTtl,
    cursor: w.cursor,
    pending: w.pending,
    attemptsTracked: w.attemptsTracked,
    intervalMinutes: w.intervalMinutes,
    feeds: w.feeds,
    description: w.description,
    controllable: CONTROLLABLE.has(w.name),
    load: null,
  }));
  const queues: NormQueue[] = snap.queues.map((q) => ({
    name: q.name,
    label: q.label,
    depth: q.depth,
    kind: q.kind,
  }));
  return {
    ts: snap.ts,
    source: "live",
    redisAvailable: snap.redisAvailable,
    workers,
    queues,
    pipeline: {
      priorityQueue: snap.pipeline.priorityQueue,
      standardQueue: snap.pipeline.standardQueue,
      dlq: snap.pipeline.dlq,
      sweepPendingPriority: snap.pipeline.sweepPendingPriority,
      sweepPendingStandard: snap.pipeline.sweepPendingStandard,
      sweepAttemptsTracked: snap.pipeline.sweepAttemptsTracked,
      topPlayersPool: snap.pipeline.topPlayersPool,
      totalBacklog: snap.pipeline.totalBacklog,
    },
  };
}

const overviewHealth = (status: string): WorkerHealth =>
  status === "down" ? "down" : status === "warn" ? "warn" : "idle";

function depthByName(ov: AdminOverview, needle: string): number {
  const q = ov.queues.find((x) => x.name.includes(needle));
  return q ? q.depth : 0;
}

export function fromOverview(ov: AdminOverview, tsFallback: string): Telemetry {
  const workers: NormWorker[] = ov.workers.map((w) => ({
    name: w.name,
    label: w.name,
    paused: false, // overview can't tell; live endpoint reveals true pause state
    active: false,
    health: overviewHealth(w.status),
    tickLockTtl: 0,
    cursor: null,
    pending: null,
    attemptsTracked: null,
    intervalMinutes: null,
    feeds: null,
    description: null,
    controllable: CONTROLLABLE.has(w.name),
    load: w.load,
  }));
  const queues: NormQueue[] = ov.queues.map((q) => ({
    name: q.name,
    label: q.name,
    depth: q.depth,
    kind: q.name.includes("dlq") ? "list" : "zset",
  }));
  const priorityQueue = depthByName(ov, "priority");
  const standardQueue = depthByName(ov, "standard");
  const dlq = depthByName(ov, "dlq");
  return {
    ts: tsFallback,
    source: "overview",
    redisAvailable: null,
    workers,
    queues,
    pipeline: {
      priorityQueue,
      standardQueue,
      dlq,
      sweepPendingPriority: null,
      sweepPendingStandard: null,
      sweepAttemptsTracked: null,
      topPlayersPool: null,
      totalBacklog: priorityQueue + standardQueue,
    },
  };
}
