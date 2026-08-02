/* ============================================================
   ArenaRank — cliente da read-API (FastAPI). Tipado contra types.ts.
   Em dev, VITE_API_URL vazio → usa o proxy /api do Vite (porta 8000).
   Em produção, VITE_API_URL aponta para a API real.
   ============================================================ */
import type {
  LeaderboardResponse,
  PlayerProfile,
  MatchDetail,
  ChampTierlistResponse,
  ChampionSynergyResponse,
  ChampionSynergyGroupResponse,
  SynergyTierlistResponse,
  ChampionTrendResponse,
  ChampionRoundsResponse,
  ChampionMatchupsResponse,
  ChampionBuildVariantsResponse,
  MatchupKind,
  ChampionMainsResponse,
  ChampionOtpsResponse,
  ChampionBuildResponse,
  TopBuildResponse,
  TournamentListItem,
  TournamentDetail,
  TournamentCreate,
  AdminOverview,
  LastUpdate,
  SearchPlayer,
  ActivityResponse,
  RecordsResponse,
  PlayerMatchesResponse,
  DonationResult,
} from "./types";

const BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");

/* --- Auth de admin: chave compartilhada que protege /admin/* no backend
   (enviada como X-Admin-Key). Guardada em sessionStorage (some ao fechar a
   aba). A imposição real é no servidor; aqui só carregamos a chave. --- */
const ADMIN_KEY_STORAGE = "arenarank.adminKey";
let adminKey: string | null =
  typeof sessionStorage !== "undefined" ? sessionStorage.getItem(ADMIN_KEY_STORAGE) : null;

export function setAdminKey(key: string): void {
  adminKey = key.trim() || null;
  try {
    if (adminKey) sessionStorage.setItem(ADMIN_KEY_STORAGE, adminKey);
    else sessionStorage.removeItem(ADMIN_KEY_STORAGE);
  } catch {
    /* sessionStorage indisponível (modo privado) — mantém só em memória */
  }
}

export function getAdminKey(): string | null {
  return adminKey;
}

export function clearAdminKey(): void {
  setAdminKey("");
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function qs(params: Record<string, string | number | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function get<T>(path: string): Promise<T> {
  /* Fixture dos endpoints ainda não implementados (só em dev, só com
     ?mock=1). Import dinâmico: o build de produção não inclui o módulo. */
  if (import.meta.env.DEV) {
    const { devMockResponse, devMockPatch } = await import("./devMock");
    const mocked = await devMockResponse(path);
    if (mocked !== null) return mocked as T;
    return devMockPatch(path, await request<T>("GET", path));
  }
  return request<T>("GET", path);
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const isAdmin = path.startsWith("/admin");
  const res = await fetch(`${BASE}/api/v1${path}`, {
    method,
    headers: {
      Accept: "application/json",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(isAdmin && adminKey ? { "X-Admin-Key": adminKey } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      // FastAPI 422: detail pode ser array de erros de validação
      detail = typeof data?.detail === "string" ? data.detail : (data?.detail ? JSON.stringify(data.detail) : detail);
    } catch {
      /* corpo não-JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const api = {
  leaderboard(opts: {
    format?: string;
    scope?: "global" | "br" | "friends";
    season?: number;
    limit?: number;
    offset?: number;
  } = {}): Promise<LeaderboardResponse> {
    return get<LeaderboardResponse>(`/leaderboard${qs(opts)}`);
  },

  player(riotId: string): Promise<PlayerProfile> {
    return get<PlayerProfile>(`/player/${encodeURIComponent(riotId)}`);
  },

  /** Histórico paginado de partidas (aba Histórico do perfil). */
  playerMatches(
    riotId: string,
    opts: {
      offset?: number;
      limit?: number;
      result?: "first" | "top" | "bottom";
      champion?: number;
    } = {},
  ): Promise<PlayerMatchesResponse> {
    return get<PlayerMatchesResponse>(`/player/${encodeURIComponent(riotId)}/matches${qs(opts)}`);
  },

  /** Busca global de jogadores por nome (typeahead do leaderboard). */
  searchPlayers(opts: {
    q: string;
    format?: string;
    limit?: number;
  }): Promise<SearchPlayer[]> {
    return get<SearchPlayer[]>(`/players/search${qs(opts)}`);
  },

  match(matchId: string): Promise<MatchDetail> {
    return get<MatchDetail>(`/match/${encodeURIComponent(matchId)}`);
  },

  champions(opts: {
    format?: string;
    metric?: "top4" | "first" | "avgplace" | "pick" | "ban";
    region?: string;
  } = {}): Promise<ChampTierlistResponse> {
    return get<ChampTierlistResponse>(`/champions${qs(opts)}`);
  },

  /** Sinergia de duplas de campeão (winrate real de subteam). */
  championSynergy(opts: { format?: string; season?: number; limit?: number } = {}): Promise<ChampionSynergyResponse> {
    return get<ChampionSynergyResponse>(`/champions/synergy${qs(opts)}`);
  },

  /** Sinergia de subteams (trios por padrão) por winrate — rail do /campeoes. */
  championSynergyGroups(
    opts: { format?: string; season?: number; size?: number; limit?: number } = {},
  ): Promise<ChampionSynergyGroupResponse> {
    return get<ChampionSynergyGroupResponse>(`/champions/synergy/groups${qs(opts)}`);
  },

  /** Tierlist de sinergias em bandas S+..D — página /sinergias. */
  championSynergyTierlist(
    opts: { format?: string; season?: number; size?: number } = {},
  ): Promise<SynergyTierlistResponse> {
    return get<SynergyTierlistResponse>(`/champions/synergy/tierlist${qs(opts)}`);
  },

  /** Série diária (winrate/pick/top4) de um campeão — charts da página do campeão. */
  championTrend(
    championId: number,
    opts: { season?: number; days?: number } = {},
  ): Promise<ChampionTrendResponse> {
    return get<ChampionTrendResponse>(`/champions/${championId}/trend${qs(opts)}`);
  },

  /** Força por estágio de draft (prata/ouro/prismático) — chart de power
      spike do campeão. Não é round literal: Arena não tem timeline pública. */
  championRounds(
    championId: number,
    opts: { season?: number; format?: string } = {},
  ): Promise<ChampionRoundsResponse> {
    return get<ChampionRoundsResponse>(`/champions/${championId}/rounds${qs(opts)}`);
  },

  /** Melhores e piores parceiros (`duo`) ou oponentes (`versus`) do campeão.
      Endpoint em preparação: o agregado atual só entrega a ponta boa. */
  championMatchups(
    championId: number,
    opts: { kind?: MatchupKind; season?: number; format?: string; limit?: number } = {},
  ): Promise<ChampionMatchupsResponse> {
    return get<ChampionMatchupsResponse>(`/champions/${championId}/matchups${qs(opts)}`);
  },

  /** Variantes de build categorizadas por tier, com os augments que cada uma
      exige. Endpoint em preparação no backend. */
  championBuildVariants(
    championId: number,
    opts: { season?: number; format?: string } = {},
  ): Promise<ChampionBuildVariantsResponse> {
    return get<ChampionBuildVariantsResponse>(`/champions/${championId}/builds${qs(opts)}`);
  },

  /** Jogadores de referência (mains) de um campeão. */
  championMains(championId: number, opts: { season?: number; limit?: number } = {}): Promise<ChampionMainsResponse> {
    return get<ChampionMainsResponse>(`/champions/${championId}/mains${qs(opts)}`);
  },

  /** Top OTPs com compatibilidade durante o rollout do limite 100. */
  async championOtps(championId: number): Promise<ChampionOtpsResponse> {
    try {
      const response = await get<ChampionMainsResponse>(
        `/champions/${championId}/mains${qs({ limit: 100 })}`,
      );
      return { ...response, limit: 100, truncated: false };
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 422) throw error;
      const response = await get<ChampionMainsResponse>(
        `/champions/${championId}/mains${qs({ limit: 20 })}`,
      );
      return { ...response, limit: 20, truncated: true };
    }
  },

  /** Build de referência categorizada (augments por raridade, itens/botas, parceiros). */
  championBuild(championId: number): Promise<ChampionBuildResponse> {
    return get<ChampionBuildResponse>(`/champions/${championId}/build`);
  },

  /** Top global de augments/itens do patch (rail do /campeoes). */
  topBuild(): Promise<TopBuildResponse> {
    return get<TopBuildResponse>(`/champions/build/top`);
  },

  tournaments(): Promise<TournamentListItem[]> {
    return get<TournamentListItem[]>(`/tournaments`);
  },

  tournament(id: string): Promise<TournamentDetail> {
    return get<TournamentDetail>(`/tournament/${encodeURIComponent(id)}`);
  },

  /** Provisiona um campeonato (Admin). Retorna o TournamentDetail criado. */
  createTournament(body: TournamentCreate): Promise<TournamentDetail> {
    return request<TournamentDetail>("POST", `/admin/tournaments`, body);
  },

  adminOverview(): Promise<AdminOverview> {
    return get<AdminOverview>(`/admin/overview`);
  },

  lastUpdate(rank?: number): Promise<LastUpdate> {
    return get<LastUpdate>(`/meta/last-update${qs({ rank })}`);
  },

  /** Partidas ranqueadas processadas por dia (gráfico de atividade do rail). */
  activity(opts: { season?: number; days?: number } = {}): Promise<ActivityResponse> {
    return get<ActivityResponse>(`/meta/activity${qs(opts)}`);
  },

  /** Recordes reais da temporada (card rotativo do rail). */
  records(season?: number): Promise<RecordsResponse> {
    return get<RecordsResponse>(`/meta/records${qs({ season })}`);
  },

  /** Cria um link de checkout InfinitePay para doar à premiação da Season.
      Retorna a URL hospedada — o fluxo é redirect (iframe é bloqueado). */
  createDonation(amountCents: number): Promise<DonationResult> {
    return request<DonationResult>("POST", "/payments/donation", {
      amount_cents: amountCents,
    });
  },
};
