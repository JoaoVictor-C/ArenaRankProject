/* ============================================================
   ArenaRank — tipos do contrato de API v1
   Espelha spec/api_contract_v1.md 1:1. NÃO divergir sem atualizar o contrato.
   ============================================================ */

export type TierKey = "top1" | "top10" | "top50" | "top100" | "top500" | "none";

export interface AvatarColors {
  c1: string;
  c2: string;
}

export interface PlayerTag {
  kind: "global" | "region" | "hot" | "veteran" | "rookie" | "otp";
  label: string;
  icon: string; // nome do Material Symbol
}

/* ---------- 1. Leaderboard ---------- */
export interface LeaderboardResponse {
  updatedAt: string;
  total: number;
  season: number;
  format: string;
  rows: LeaderboardRow[];
}
export interface LeaderboardRow {
  rank: number;
  riotId: string;
  name: string;
  handle: string;
  avatar: AvatarColors;
  cr: number;
  delta7d: number;
  wins: number;
  losses: number;
  winrate: number;
  top4: number;
  /** Taxa de 1º lugar (placement==1), 0..100. */
  top1: number;
  /** Sequência atual de 1º lugares (placement==1) a partir da última partida; >=3 → "on fire". */
  top1Streak: number;
  tier: TierKey;
  tags: PlayerTag[];
  inGame?: boolean;
  champions: AvatarColors[];
  /** Ícone de invocador (Data Dragon — CDN oficial da Riot). Fallback: avatar gradiente. */
  profileIconUrl?: string;
  /** Ícones de campeão (ddragon), na mesma ordem de `champions`. Fallback: gradiente. */
  championIconUrls?: (string | null)[];
  /** Mini-stats do jogador com cada main (mesma ordem de `champions`) — hover do podium. */
  championsStats?: LeaderboardChampion[];
}

/** Stats do jogador com um campeão específico (card de hover no podium). */
export interface LeaderboardChampion {
  championId: number;
  name: string;
  iconUrl?: string | null;
  games: number;
  /** Winrate (1º lugar / vitórias de metade superior), 0..100. */
  winrate: number;
  /** Taxa de top-half (colocação na metade superior), 0..100. */
  topHalf: number;
  /** Colocação média (1 casa decimal). */
  avgPlace: number;
}

/* ---------- 1-bis. Player search (typeahead) ---------- */
/** Um resultado da busca global de jogadores (GET /players/search). */
export interface SearchPlayer {
  riotId: string; // "Nome#TAG"
  name: string;
  handle: string; // "#TAG"
  cr: number;
  rank: number; // rank global na temporada (1-based)
  tier: TierKey;
  avatar: AvatarColors;
  /** Ícone de invocador (ddragon). Ausente → fallback do gradiente do avatar. */
  profileIconUrl?: string;
}

/* ---------- 2. Player profile ---------- */
export interface PlayerProfile {
  riotId: string;
  name: string;
  handle: string;
  region: string;
  avatar: AvatarColors;
  cr: number;
  rank: number;
  tier: TierKey;
  provisional: boolean;
  delta7d: number;
  wins: number;
  losses: number;
  winrate: number;
  top4: number;
  avgPlace: number;
  form: FormDot[];
  crHistory: CrHistoryPoint[];
  tags: PlayerTag[];
  matches: PlayerMatch[];
  champions: ChampStat[];
  h2h: H2HRow[];
  seasons: SeasonArchive[];
  /** Ícone de invocador (ddragon — CDN oficial da Riot). Fallback: avatar gradiente. */
  profileIconUrl?: string;
}
export interface FormDot {
  place: number;
}
export interface CrHistoryPoint {
  ts: string;
  cr: number;
  lo: number;
  hi: number;
}
export interface PlayerMatch {
  matchId: string;
  ts: string;
  champion: AvatarColors;
  championName: string;
  /** Ícone de campeão (ddragon — CDN oficial da Riot). Fallback: gradiente. */
  championIconUrl?: string;
  place: number;
  crDelta: number;
  modifiers: Modifier[];
}
export interface Modifier {
  kind: string;
  label: string;
  value: number;
  icon: string;
}
/* ---------- 2-bis. Histórico paginado (GET /player/{riotId}/matches) ---------- */
export interface PlayerMatchRich extends PlayerMatch {
  crBefore: number;
  crAfter: number;
  format: string; // "3v3" | "2v2"
  teamCount: number; // 6 (3v3) | 8 (2v2)
  durationSec: number;
  premade: boolean;
}
export interface ChampFacet {
  championId: number;
  name: string;
  champion: AvatarColors;
  championIconUrl?: string | null;
  games: number;
}
/** Agregados do conjunto FILTRADO inteiro (não só a página carregada). */
export interface MatchesSummary {
  games: number;
  firstRate: number; // % 1º lugar
  top4: number; // % top-metade (mode-aware: ≤4 em 2v2, ≤3 em 3v3)
  avgPlace: number;
  crSum: number; // soma do crDelta do conjunto
  placements: number[]; // contagens por colocação; índice 0 → 1º
}
export interface PlayerMatchesResponse {
  total: number;
  offset: number;
  limit: number;
  summary: MatchesSummary;
  championsFacet: ChampFacet[];
  matches: PlayerMatchRich[];
}

export interface ChampStat {
  champion: AvatarColors;
  /** Ícone de campeão (ddragon — CDN oficial da Riot). Fallback: gradiente. */
  championIconUrl?: string;
  name: string;
  games: number;
  firstRate: number;
  top4: number;
  avgPlace: number;
  crImpact: number;
  spark: number[];
}
export interface H2HRow {
  player: { name: string; handle: string; avatar: AvatarColors };
  games: number;
  winrate: number;
  synergy: "duo" | "rival";
}
export interface SeasonArchive {
  season: number;
  peakCr: number;
  finalRank: number;
  tier: TierKey;
}

/* ---------- 3. Match detail ---------- */
export interface MatchDetail {
  matchId: string;
  format: string;
  queueLabel: string;
  playedAt: string;
  durationSec: number;
  patch: string;
  processedAt: string;
  subteams: SubTeam[];
}
export interface SubTeam {
  placement: number;
  players: MatchPlayer[];
}
export interface MatchPlayer {
  riotId: string;
  name: string;
  handle: string;
  avatar: AvatarColors;
  champion: AvatarColors;
  championName: string;
  /** Ícone de campeão (ddragon — CDN oficial da Riot). Fallback: gradiente. */
  championIconUrl?: string;
  /** Ícone de invocador (ddragon — CDN oficial da Riot). Fallback: gradiente. */
  profileIconUrl?: string;
  crBefore: number;
  crAfter: number;
  crDelta: number;
  modifiers: Modifier[];
  integrity?: { kind: "info" | "warn" | "critical"; label: string }[];
}

/* ---------- 4. Champion tierlist ---------- */
export interface ChampTierlistResponse {
  updatedAt: string;
  patch: string;
  region: string;
  format: string;
  metric: string;
  sampleSize: number;
  tiers: ChampTier[];
  table: ChampRow[];
}
export interface ChampTier {
  key: "S+" | "S" | "A" | "B" | "C" | "D";
  label: string;
  color: string;
  champions: ChampRow[];
}
export interface ChampRow {
  rank: number;
  champion: AvatarColors;
  name: string;
  role: string;
  top4: number;
  first: number;
  avgPlace: number;
  pickRate: number;
  banRate: number;
  tier: string;
}

/* ---------- 5. Tournaments ---------- */
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
export interface TournamentRules {
  format: string[];
  scoring: { place: number; points: number }[];
  tiebreak: string[];
  currency?: string;
  conduct?: { icon: string; title: string; desc: string }[];
  entry?: { fee?: string | null; pix?: string | null };
  schedule?: string;
  prizeNote?: string;
}
/** Slot de jogador: real ou vago. */
export type PlayerSlot =
  | { name: string; handle: string; riotId: string; avatar: AvatarColors }
  | { empty: true };
export interface TournamentDetail {
  id: string;
  title: string;
  format: string;
  prizeRp: number;
  prizeLabel: string;
  currency?: string; // "BRL" | "RP"
  status: "upcoming" | "live" | "ended";
  currentMatch: number;
  matches: TournamentMatch[];
  standings: StandingRow[];
  rules: TournamentRules;
  prizes: PrizeRow[];
  registrations: TeamRoster[];
  history: TournamentMatchResult[];
  /** Chave de acesso gerada no provisionamento. Visível apenas no Admin. */
  accessKey?: string;
}
export interface TournamentMatch {
  n: number;
  status: "ended" | "live" | "upcoming";
  winnerTeamId?: string;
  startsAt?: string;
  lobbyMax: number;
  lobbyCount: number;
  magneticLink: string;
  /** Resultado lançado pelo Admin (presente só em partidas encerradas). */
  result?: { teamId: string; placement: number; bravura: number }[];
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
  isYou?: boolean;
}
export interface TeamRoster {
  teamId: string;
  teamName: string;
  seed: number;
  captain: string;
  isYou?: boolean;
  players: PlayerSlot[];
}
export interface PrizeRow {
  place: number;
  rp: number;
  perPlayer: number;
  medal: "gold" | "silver" | "bronze" | "none";
}
export interface TournamentMatchResult {
  n: number;
  status: "ended" | "live" | "upcoming";
  results: { teamName: string; points: number; place: number }[];
}

/** Config enviada pelo Admin para provisionar um campeonato (POST). */
export interface TournamentCreate {
  title: string;
  format: "3v3" | "2v2";
  numTeams: number;
  numMatches: number;
  prizeRp: number;
  startsAt?: string;
  bannerTone?: "b1" | "b2" | "b3" | "b4";
  tag?: string;
  scoring?: { place: number; points: number }[];
  currency?: "BRL" | "RP";
  entryFee?: number;
  pixInfo?: string;
  schedule?: string;
  prizeNote?: string;
  prizeSplit?: { place: number; pct: number }[];
  conduct?: { icon: string; title: string; desc: string }[];
  tiebreak?: string[];
  formatLines?: string[];
  /** Chave de acesso customizada; se omitida, o backend gera ARENA-XXXXXX. */
  accessKey?: string;
}

/* ---------- 5-bis. Onboarding endpoints ---------- */

/** POST /api/v1/tournament/{id}/access  →  body */
export interface AccessRequest {
  key: string;
}
/** POST /api/v1/tournament/{id}/access  →  200 */
export interface AccessResponse {
  tournamentId: string;
  teams: { teamId: string; teamName: string; openSlots: number }[];
}

/** POST /api/v1/tournament/{id}/team  →  body */
export interface CreateTeamRequest {
  key: string;
  teamName: string;
  riotId: string;
}
/** POST /api/v1/tournament/{id}/team  →  201 */
export interface CreateTeamResponse {
  teamId: string;
}

/** POST /api/v1/tournament/{id}/join  →  body */
export interface JoinTeamRequest {
  key: string;
  teamId: string;
  riotId: string;
}
/** POST /api/v1/tournament/{id}/join  →  200 */
export interface JoinTeamResponse {
  teamId: string;
}

/** POST /api/v1/admin/tournament/{id}/match/{n}/link  →  body */
export interface SetMatchLinkRequest {
  magneticLink: string;
  status: "upcoming" | "live" | "ended";
}

/** POST /api/v1/admin/tournament/{id}/match/{n}/result  →  body */
export interface SubmitResultRequest {
  results: { teamId: string; placement: number; bravura: number }[];
  penalties?: { teamId: string; value: number }[];
}

/* ---------- 6. Admin ---------- */
export interface AdminOverview {
  metrics: { key: string; label: string; value: string; trend?: number }[];
  workers: { name: string; status: "ok" | "warn" | "down"; load: number }[];
  queues: { name: string; depth: number; rate: string }[];
  integrity: { id: string; player: string; reason: string; severity: "info" | "warn" | "critical"; ts: string }[];
  flags: { id: string; player: string; flag: string; severity: "info" | "warn" | "critical" }[];
  dlq: { matchId: string; attempts: number; reason: string; ts: string }[];
  season: { current: number; state: string; startedAt: string; config: Record<string, string> };
  riotApi: { name: string; status: "ok" | "warn"; usage: string }[];
}

/* ---------- 7. Meta / last update ---------- */
export interface LastUpdate {
  global: { lastTs: string; cycleSec: number; etaSec: number };
  tier: { rank: number; label: string; cadenceSec: number; etaSec: number };
}

/* ---------- 7-bis. Meta / activity + records (rail cards) ---------- */
export interface ActivityDay {
  label: string; // dia do mês, ex: "18"
  count: number; // partidas ranqueadas processadas no dia
}
export interface ActivityResponse {
  days: ActivityDay[];
  max: number;
}
export interface SeasonRecord {
  key: string; // streak | biggest_gain | most_today | first_rate | top4_rate
  label: string;
  value: string; // "14", "+72", "42%"
  name: string;
  handle: string; // "#TAG"
  avatar: AvatarColors;
  accent: string; // dica de cor de destaque
}
export interface RecordsResponse {
  records: SeasonRecord[];
}
