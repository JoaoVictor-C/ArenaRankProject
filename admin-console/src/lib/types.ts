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

/* ---- RBAC: GET/POST/DELETE /admin/operators, GET /admin/operators/permissions ---- */
export type OperatorRole = "owner" | "admin" | "moderator" | "analyst" | "support";

export interface OperatorInfo {
  id: string;
  email: string;
  role: OperatorRole;
  keyPrefix: string;
  createdAt: string;
  lastSeenAt: string | null;
  revoked: boolean;
}

export interface OperatorCreateBody {
  email: string;
  role: OperatorRole;
}

/** `apiKey` is the plaintext key — present ONLY in this create response,
 *  never again (mirrors tournament accessKey's "shown once" pattern). */
export interface OperatorCreateResult {
  id: string;
  email: string;
  role: OperatorRole;
  apiKey: string;
  message: string;
}

export interface OperatorRevokeResult {
  id: string;
  message: string;
}

export interface PermissionRow {
  scope: string;
  label: string;
  roles: OperatorRole[];
}

/* ---- GET /admin/audit ---- */
export type AuditKind = "workers" | "moderacao" | "dlq" | "temporada" | "campeonatos" | "acesso" | "outro";

export interface AuditEventInfo {
  id: string;
  occurredAt: string;
  actor: string;
  action: string;
  kind: AuditKind;
  target: string | null;
  sourceIp: string | null;
  result: string;
}

/* ---- GET /admin/players/search, PATCH /admin/players/{id}/moderation ---- */
export interface PlayerSearchRow {
  id: string;
  riotId: string;
  puuid: string;
  region: string | null;
  cr: number | null;
  active: boolean;
  banned: boolean;
  shadowbanned: boolean;
  restricted: boolean;
  flagCount: number;
  avatar: { c1: string; c2: string };
}

export interface PlayerModerationBody {
  banned?: boolean;
  shadowbanned?: boolean;
  restricted?: boolean;
  flagType?: string;
  note?: string;
}

export interface PlayerModerationResult {
  playerId: string;
  banned: boolean;
  shadowbanned: boolean;
  restricted: boolean;
  message: string;
}

/* ---- GET /admin/matches/daily ---- */
/** One UTC calendar day's match volume + whatever the `matches` row carries.
 *  No fabricated fields — a stat we can't reliably compute is just absent. */
export interface AdminDailyMatchStat {
  date: string; // YYYY-MM-DD (UTC)
  matches: number;
  avgDurationSeconds: number | null;
  duos: number;
  trios: number;
  withIntegrityFlags: number;
}
export interface AdminDailyMatches {
  ts: string;
  days: AdminDailyMatchStat[];
}

/* ---- GET /admin/riot/usage ---- */
/** What Riot itself reported via its rate-limit headers — ground truth, as
 *  opposed to the bucket gauges, which are our model of Riot's accounting. */
export interface RiotObservedWindow {
  limit: number;
  seconds: number;
  count: number;
  utilization: number;
  /** Epoch seconds of the response this came from (staleness indicator). */
  observedAt: number;
}
export interface RiotBucketUsage {
  name: string;
  label: string;
  /** What the limiter allows per window, after the headroom margin. */
  capacity: number;
  /** Riot's advertised ceiling, before headroom. Absent on an older backend. */
  advertised?: number;
  windowSeconds: number;
  available: number;
  used: number;
  /** 0..1 share of the window's budget currently spent. */
  utilization: number;
  lastMinute: number;
  lastHour: number;
  observed?: RiotObservedWindow | null;
  /** Set when our config exceeds what Riot advertises (PT-BR message). */
  drift?: string | null;
}
export interface RiotUsage {
  ts: string;
  /** Last 8 chars of the key — never the key itself. */
  keySuffix: string;
  keyConfigured: boolean;
  /** Fraction of Riot's advertised limits the limiter may spend. Absent on an
   *  older backend. */
  headroom?: number;
  buckets: RiotBucketUsage[];
  requestsLastMinute: number;
  requestsLastHour: number;
  rateLimitedLastHour: number;
  errorsLastHour: number;
  /** Empty/absent is healthy; non-empty means the key is being over-driven. */
  driftWarnings?: string[];
}

/* ---- GET /admin/stats/series ---- */
export interface StatSeries {
  event: string;
  label: string;
  /** One count per minute, oldest first, zero-filled. */
  points: number[];
  total: number;
}
export interface StatsSeries {
  ts: string;
  minutes: number;
  endMinute: number;
  series: StatSeries[];
}

/* ---- GET /tournaments, GET(/admin)/tournament/{id} ---- */
/** Mirrors backend/arena/schemas/tournaments.py. Wire types consumed directly
 *  (single source, no live/overview reconciliation needed like Telemetry). */
export type TournamentFormat = "2v2" | "3v3";
export type TournamentStatus = "upcoming" | "live" | "ended";
export type MatchStatus = "upcoming" | "live" | "ended";
export type Medal = "gold" | "silver" | "bronze" | "none";
export type Currency = "BRL" | "RP";

/** A roster slot: a real player, or `{ empty: true }` for an open slot. */
export type PlayerSlot =
  | { name: string; handle: string; riotId: string; avatar: { c1: string; c2: string } }
  | { empty: true };

export interface ScoringEntry {
  place: number;
  points: number;
}
export interface PrizeSplitEntry {
  place: number;
  pct: number;
}
export interface TournamentRules {
  format: string[];
  scoring: ScoringEntry[];
  tiebreak: string[];
  currency: string | null;
}

export interface TournamentListItem {
  id: string;
  title: string;
  format: string;
  startsAt: string;
  teams: number;
  prizeRp: number;
  bannerTone: "b1" | "b2" | "b3" | "b4";
  tag: string;
  amountLabel: string;
  whenLabel: string;
}

export interface TournamentMatchResultEntry {
  teamId: string;
  placement: number;
  bravura: number;
}
export interface TournamentMatch {
  n: number;
  status: MatchStatus;
  winnerTeamId: string | null;
  startsAt: string | null;
  lobbyMax: number;
  lobbyCount: number;
  magneticLink: string;
  result: TournamentMatchResultEntry[] | null;
}

export interface StandingRow {
  teamId: string;
  seed: number;
  teamName: string;
  players: PlayerSlot[];
  perMatch: number[];
  penalties: number;
  bonus: number;
  total: number;
}

export interface TeamRoster {
  teamId: string;
  teamName: string;
  seed: number;
  captain: string;
  players: PlayerSlot[];
}

export interface PrizeRow {
  place: number;
  rp: number;
  perPlayer: number;
  medal: Medal;
}

export interface TournamentMatchResultRow {
  teamName: string;
  points: number;
  place: number;
}
export interface TournamentMatchResult {
  n: number;
  status: MatchStatus;
  results: TournamentMatchResultRow[];
}

export interface TournamentDetail {
  id: string;
  title: string;
  format: string;
  prizeRp: number;
  prizeLabel: string;
  currency: string | null;
  status: TournamentStatus;
  currentMatch: number;
  matches: TournamentMatch[];
  standings: StandingRow[];
  rules: TournamentRules;
  prizes: PrizeRow[];
  registrations: TeamRoster[];
  history: TournamentMatchResult[];
  /** Only populated by the admin-gated detail route. */
  accessKey: string | null;
}

/* ---- Request bodies ---- */

/** POST /admin/tournaments. entryFee/pixInfo are deliberately NOT exposed here
 *  (see admin-console TournamentCreateForm) — the backend accepts them but
 *  never persists or surfaces them (payment flow is an unbuilt later slice). */
export interface TournamentCreateBody {
  title: string;
  format: TournamentFormat;
  numTeams: number;
  numMatches: number;
  prizeRp: number;
  startsAt?: string | null;
  bannerTone?: "b1" | "b2" | "b3" | "b4" | null;
  tag?: string | null;
  currency?: Currency | null;
}

/** POST /admin/tournament/{id}/match/{n}/link */
export interface SetMatchLinkBody {
  magneticLink: string;
  status: MatchStatus;
}

/** POST /admin/tournament/{id}/match/{n}/result */
export interface ResultPenalty {
  teamId: string;
  value: number;
}
export interface SubmitResultBody {
  results: TournamentMatchResultEntry[];
  penalties?: ResultPenalty[];
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
