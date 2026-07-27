/* Operator actions against the gated /admin/* surface. */
import { apiGet, apiSend, type Conn } from "./backend";
import type {
  AdminDailyMatches,
  AdminOverview,
  LiveSnapshot,
  RiotUsage,
  StatsSeries,
} from "./types";

export const fetchLive = (conn: Conn, signal?: AbortSignal): Promise<LiveSnapshot> =>
  apiGet<LiveSnapshot>(conn, "/admin/workers/live", signal);

export const fetchOverview = (conn: Conn, signal?: AbortSignal): Promise<AdminOverview> =>
  apiGet<AdminOverview>(conn, "/admin/overview", signal);

export const fetchDailyMatches = (
  conn: Conn,
  days: number,
  signal?: AbortSignal,
): Promise<AdminDailyMatches> =>
  apiGet<AdminDailyMatches>(conn, `/admin/matches/daily?days=${days}`, signal);

export const fetchRiotUsage = (conn: Conn, signal?: AbortSignal): Promise<RiotUsage> =>
  apiGet<RiotUsage>(conn, "/admin/riot/usage", signal);

export const fetchStats = (
  conn: Conn,
  minutes: number,
  signal?: AbortSignal,
): Promise<StatsSeries> =>
  apiGet<StatsSeries>(conn, `/admin/stats/series?minutes=${minutes}`, signal);

export interface WorkerControlResult {
  worker: string;
  status: string;
  message: string;
}

export const pauseWorker = (conn: Conn, name: string): Promise<WorkerControlResult> =>
  apiSend<WorkerControlResult>(conn, "POST", `/admin/workers/${encodeURIComponent(name)}/pause`);

export const resumeWorker = (conn: Conn, name: string): Promise<WorkerControlResult> =>
  apiSend<WorkerControlResult>(conn, "POST", `/admin/workers/${encodeURIComponent(name)}/resume`);

export interface DlqResult {
  matchId: string;
  message: string;
}

export const requeueDlq = (conn: Conn, matchId: string): Promise<DlqResult> =>
  apiSend<DlqResult>(conn, "POST", `/admin/dlq/${encodeURIComponent(matchId)}/requeue`);

export const discardDlq = (conn: Conn, matchId: string): Promise<DlqResult> =>
  apiSend<DlqResult>(conn, "DELETE", `/admin/dlq/${encodeURIComponent(matchId)}`);

export interface DlqRequeueAllResult {
  total: number;
  requeued: number;
  failed: number;
  queue: string;
  message: string;
}

export const requeueAllDlq = (conn: Conn): Promise<DlqRequeueAllResult> =>
  apiSend<DlqRequeueAllResult>(conn, "POST", "/admin/dlq/requeue-all");

export interface IntegrityReviewResult {
  eventId: string;
  message: string;
}

export const reviewIntegrity = (
  conn: Conn,
  eventId: string,
  override: "eligible" | "ineligible" | "none" = "none",
): Promise<IntegrityReviewResult> =>
  apiSend<IntegrityReviewResult>(
    conn,
    "POST",
    `/admin/integrity/${encodeURIComponent(eventId)}/review`,
    { override },
  );
