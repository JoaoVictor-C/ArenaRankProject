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
  kind: "hot" | "otp" | "champrank";
  label: string;
  icon: string; // nome do Material Symbol ("" nas tags de campeão)
  /** Ícone ddragon do campeão da tag (otp/champrank) — o cliente extrai a cor
   *  dominante dele p/ tingir o chip (ex. Vladimir → degradê vermelho). */
  champIconUrl?: string | null;
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
  /** Impacto aditivo real do fator no resultado exibido, em PDL. */
  pdlImpact?: number;
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
  /** championId numérico + splash-art (ddragon) — capa do banner de perfil. */
  championId?: number | null;
  championSplashUrl?: string | null;
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
export type AugmentRarity = "prismatic" | "gold" | "silver" | "unknown";

/** Item ou augment já resolvido pelo backend — a tela mostra ícone e nome, não id. */
export interface LoadoutEntry {
  id: number;
  name: string;
  iconUrl: string | null;
  /** Custo total de compra (itens) — sempre ausente em augments (escolha de
      draft, não tem preço). */
  gold?: number | null;
  description?: string | null;
}
export interface AugmentEntry extends LoadoutEntry {
  rarity: AugmentRarity;
}

/** Telemetria de combate, ingerida do detail da Riot.
 *
 *  TODO campo é opcional, e isso é permanente: partidas processadas antes da
 *  ingestão de telemetria existir não têm como recuperá-la (o payload cru não é
 *  guardado). Ausente ≠ zero — a UI degrada para "aguardando ingestão" em vez de
 *  exibir 0/0/0. `killParticipation` e `damagePerMinute` são derivados no
 *  backend a partir dos primitivos, nunca persistidos. */
export interface CombatStats {
  level?: number;
  kills?: number;
  deaths?: number;
  assists?: number;
  /** 0..100 — (abates + assistências) sobre os abates do subteam. */
  killParticipation?: number;
  damageToChampions?: number;
  damagePerMinute?: number;
  goldEarned?: number;
}

export interface MatchPlayer extends CombatStats {
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
  premade?: boolean;
  modifiers: Modifier[];
  integrity?: { kind: "info" | "warn" | "critical"; label: string }[];
  /** Inventário final (até 7 slots; vazios já vêm descartados). */
  items?: LoadoutEntry[];
  /** Augments escolhidos (até 6; vazios já vêm descartados). */
  augments?: AugmentEntry[];
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
  championId: number;
  champion: AvatarColors;
  championIconUrl?: string | null; // ícone real ddragon; ausente → só gradiente
  name: string;
  role: string;
  games: number; // partidas-campeão elegíveis amostradas na temporada
  top4: number;
  first: number;
  avgPlace: number;
  pickRate: number;
  banRate: number;
  tier: string;
  /** Variação (pp) do top-half nos últimos 7d vs os 7d anteriores. 0 sem histórico. */
  winrateDelta: number;
  topPlayer?: ChampTopPlayer | null; // main de referência do campeão (mais jogado)
}

/** Um subteam (dupla/trio) de campeões por winrate — /champions/synergy/groups. */
export interface ChampionSynergyGroup {
  champions: SynergyChampion[];
  games: number;
  winRate: number; // 0..100 top-half
  firstRate: number; // 0..100 1º lugar
  avgPlace: number;
}
export interface ChampionSynergyGroupResponse {
  updatedAt: string;
  season: number;
  format: string;
  size: number; // 2 dupla, 3 trio
  sampleSize: number;
  minGames: number;
  groups: ChampionSynergyGroup[];
}
export interface SynergyTier {
  key: "S+" | "S" | "A" | "B" | "C" | "D";
  label: string;
  color: string;
  comps: ChampionSynergyGroup[];
}
export interface SynergyTierlistResponse {
  updatedAt: string;
  season: number;
  format: string;
  size: number;
  sampleSize: number;
  minGames: number;
  tiers: SynergyTier[];
  table: ChampionSynergyGroup[];
}

/** Série diária de winrate/pick/top4 de um campeão — /champions/{id}/trend. */
export interface ChampionTrendPoint {
  date: string; // ISO "2026-07-20"
  top4: number; // 0..100
  first: number; // 0..100
  pickRate: number; // 0..100
  games: number;
}
export interface ChampionTrendResponse {
  championId: number;
  name: string;
  championIconUrl?: string | null;
  days: number;
  series: ChampionTrendPoint[];
}

/** Força do campeão por estágio de draft ("power spike") — /champions/{id}/rounds.

    NÃO é um round literal da partida: a Riot não publica timeline nenhuma
    para a fila Arena (CHERRY) em nenhum endpoint, então força round-a-round
    de verdade não é algo que dá pra medir (investigado e confirmado — não é
    falta de ingestão, é buraco na API pública). O eixo usa os três estágios
    reais do draft de augments (prata → ouro → prismático), que são os
    spikes de força de fato definidos pelo próprio modo Arena. Cada ponto é
    o top4 rate do MELHOR pick do campeão naquele estágio — honesto sobre o
    que é: "o quanto esse estágio pode te elevar", não uma curva temporal. */
export interface ChampionRoundPoint {
  /** 1 prata, 2 ouro, 3 prismático. */
  round: number;
  label: string; // "Prata" | "Ouro" | "Prismático"
  winRate: number; // 0..100 — top4 rate do melhor pick do campeão neste estágio
  games: number; // amostra por trás desse melhor pick
}
export interface ChampionRoundsResponse {
  championId: number;
  name: string;
  championIconUrl?: string | null;
  season: number;
  format: string;
  sampleSize: number;
  /** Piso de jogos por pick — abaixo dele o estágio não é servido. */
  minGames: number;
  /** Estágio de pico (1..3); 0 quando não há amostra. */
  peakRound: number;
  rounds: ChampionRoundPoint[];
}

/* ---------- Matchups & sinergia (grid de tiles do campeão) ----------
   Duas leituras da mesma partida: com quem o campeão joga bem (`duo`,
   dentro do subteam) e contra quem ele ganha (`versus`, entre subteams).
   Cada uma precisa dos DOIS extremos — o agregado de build só devolve a
   ponta boa, então a ponta ruim depende deste endpoint. */
export type MatchupKind = "duo" | "versus";
export interface MatchupEntry {
  championId: number;
  name: string;
  championIconUrl?: string | null;
  colors: AvatarColors;
  games: number;
  winRate: number; // 0..100 — top-half com/contra este campeão
  /** Variação (pp) sobre o winrate-base do campeão da página. */
  delta: number;
  avgPlace: number;
}
export interface ChampionMatchupsResponse {
  championId: number;
  name: string;
  season: number;
  format: string;
  kind: MatchupKind;
  sampleSize: number;
  minGames: number;
  /** Winrate-base do campeão — origem do `delta` de cada entrada. */
  baseWinRate: number;
  best: MatchupEntry[];
  worst: MatchupEntry[];
}

/* ---------- Variantes de build (a tabela de builds do campeão) ----------
   Uma itemização só funciona com os augments que a sustentam — no Arena o
   augment é pré-requisito, não enfeite. Cada variante entrega o par
   completo: os itens na ordem e os augments SEM OS QUAIS ela não fecha. */
export interface ChampionBuildVariant {
  id: string;
  name: string; // "Burst AP", "Drain Tank"…
  tier: BuildTierKey; // ordenadas do maior tier ao pior
  games: number;
  pickRate: number; // 0..100 — fatia das partidas do campeão
  top4: number;
  top1: number;
  avgPlace: number;
  /** Itemização na ordem de compra. */
  items: BuildEntry[];
  /** Augments/prismáticos NECESSÁRIOS para essa itemização dar certo. */
  requiredAugments: BuildEntry[];
}
export interface ChampionBuildVariantsResponse {
  championId: number;
  name: string;
  patch: string;
  updatedAt: string;
  games: number;
  minGames: number;
  variants: ChampionBuildVariant[];
}

/** Jogador de referência (main) de um campeão — winrate = taxa top-half no campeão. */
export interface ChampTopPlayer {
  name: string;
  handle: string; // "#TAG"
  avatar: AvatarColors;
  profileIconUrl?: string | null;
  games: number;
  winrate: number; // 0..100 (top-half / jogos no campeão)
  avgPlace: number;
}

/** Um campeão dentro de um par de sinergia. */
export interface SynergyChampion {
  championId: number;
  name: string;
  championIconUrl?: string | null;
  colors: AvatarColors;
}
export interface ChampionSynergy {
  championA: SynergyChampion;
  championB: SynergyChampion;
  games: number;
  winRate: number; // 0..100 (top-half do subteam)
  firstRate: number; // 0..100 (1º lugar)
  avgPlace: number;
}
export interface ChampionSynergyResponse {
  updatedAt: string;
  season: number;
  format: string;
  sampleSize: number;
  /** Piso de partidas por dupla — a UI declara o critério do ranking. */
  minGames: number;
  pairs: ChampionSynergy[];
}
export interface ChampionMainsResponse {
  championId: number;
  name: string;
  championIconUrl?: string | null;
  players: ChampTopPlayer[];
}

/** Resposta adaptada da página OTP. `truncated` sinaliza a compatibilidade
    temporária com backends que ainda limitam `/mains` a 20 jogadores. */
export interface ChampionOtpsResponse extends ChampionMainsResponse {
  limit: 20 | 100;
  truncated: boolean;
}

/* Build de referência (PROVISÓRIO — agregado global externo por patch, não a
   ladder BR; cai junto com champion_build_ref quando a ingestão nativa de
   augments chegar). Stats placement-derived: nunca winrate cru de augment/item. */
/** Rampa de 6 tiers. Item/augment NÃO expõe winrate em % (a Riot não permite
    publicar taxa de vitória de item/augment) — a força vira TIER; só a taxa de
    ESCOLHA sai como porcentagem. */
export type BuildTierKey = "S+" | "S" | "A" | "B" | "C" | "D";
export interface BuildEntry {
  id: number;
  name: string; // nome PT-BR (CDragon)
  iconUrl?: string | null;
  tier: BuildTierKey;
  games: number;
  avgPlace: number;
  top1: number; // 0..100 — taxa de 1º lugar com essa escolha
  top4: number; // 0..100 — taxa top-half com essa escolha
  pickRate: number; // 0..100
  /** Raridade do augment no draft — define a moldura colorida do tile. Só
      dá para inferir pela lista quando o augment vem agrupado; em listas
      soltas (ex.: `requiredAugments`) o backend precisa dizer. */
  rarity?: "prismatic" | "gold" | "silver";
  /** IDs dos campeões que mais rendem com essa escolha (top-N). Preenchido só
      no rail de top augments; resolvido p/ face via tabela de campeões. */
  champions?: number[];
}
export interface BuildTeammate {
  championId: number;
  name: string;
  championIconUrl?: string | null;
  colors: AvatarColors;
  tier: BuildTierKey;
  games: number;
  avgPlace: number;
  top1: number;
  top4: number;
  pickRate: number;
}
/** Augments agrupados pela raridade real do draft (3 rodadas de escolha). */
export interface ChampionAugments {
  prismatic: BuildEntry[];
  gold: BuildEntry[];
  silver: BuildEntry[];
}
/** Top global de augments/itens do patch (rail do /winrate). Ordem = games
    desc ("em alta"); tier = bucket por colocação média ponderada; pickRate =
    fatia dos games da categoria (0..100). */
export interface TopBuildResponse {
  updatedAt: string;
  patch: string;
  games: number; // 0 = sem snapshots ainda
  champions: number;
  minGames: number;
  augments: BuildEntry[];
  items: BuildEntry[];
}

export interface ChampionBuildResponse {
  championId: number;
  name: string;
  championIconUrl?: string | null;
  patch: string; // patch do agregado ("16.14"); "" sem snapshot
  updatedAt: string; // data do snapshot ("2026-07-19"); "" sem snapshot
  games: number; // amostra global do campeão no agregado (0 = sem snapshot)
  avgPlace: number;
  tier: BuildTierKey | null;
  top1: number;
  top4: number;
  /** Piso de jogos por entrada — a UI declara o critério. */
  minGames: number;
  augments: ChampionAugments;
  items: BuildEntry[];
  /** Itens PRISMÁTICOS do campeão (os 9 itens marcantes exclusivos do Arena,
      id 228xxx — ver build_ref_service.is_prismatic_item). Excluídos de
      `items` acima, não duplicados nela. */
  prismaticItems?: BuildEntry[];
  boots: BuildEntry[];
  teammates: BuildTeammate[];
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
  profileIconUrl?: string | null; // ícone real ddragon; ausente → só gradiente
  accent: string; // dica de cor de destaque
}
export interface RecordsResponse {
  records: SeasonRecord[];
}

/** Doação para a premiação da Season (InfinitePay). */
export interface DonationResult {
  orderNsu: string;
  checkoutUrl: string;
  amountCents: number;
}
