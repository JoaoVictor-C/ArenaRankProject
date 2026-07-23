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
  TournamentListItem,
  TournamentDetail,
  TournamentCreate,
  AdminOverview,
  LastUpdate,
  SearchPlayer,
  ActivityResponse,
  RecordsResponse,
  PlayerMatchesResponse,
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
    patch?: string;
    region?: string;
  } = {}): Promise<ChampTierlistResponse> {
    return get<ChampTierlistResponse>(`/champions${qs(opts)}`);
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
};
