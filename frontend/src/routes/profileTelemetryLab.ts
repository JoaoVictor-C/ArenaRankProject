import { api } from "../lib/api";
import type {
  MatchesSummary,
  PlayerMatchRich,
  PlayerMatchesResponse,
  PlayerProfile,
} from "../lib/types";
import type {
  ProfileMatchDetail,
  ProfileMatchPlayer,
  ProfileMatchSummary,
} from "./profileMatchDetail";

export const TELEMETRY_LAB_RIOT_ID = "ArenaLab#MOCK";
export const TELEMETRY_LAB_MATCH_ID = "telemetry-lab-3v3-001";

export interface PlayerMatchQuery {
  offset?: number;
  limit?: number;
  result?: "first" | "top" | "bottom";
  champion?: number;
}

export interface ProfileTelemetryLabFixture {
  profile: PlayerProfile;
  playerMatches: PlayerMatchesResponse;
  matchDetail: ProfileMatchDetail;
}

const FIXTURE_PATH = "/fixtures/profile-telemetry-lab.json";
let fixtureCache: Promise<ProfileTelemetryLabFixture> | null = null;

function isMockQueryEnabled(): boolean {
  return (
    import.meta.env.DEV &&
    typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).get("mock") === "1"
  );
}

function loadFixture(): Promise<ProfileTelemetryLabFixture> {
  fixtureCache ??= fetch(FIXTURE_PATH).then((response) => {
    if (!response.ok) {
      throw new Error("Não foi possível carregar o perfil fictício de telemetria.");
    }
    return response.json() as Promise<ProfileTelemetryLabFixture>;
  });
  return fixtureCache;
}

function emptySummary(teamCount: number): MatchesSummary {
  return {
    games: 0,
    firstRate: 0,
    top4: 0,
    avgPlace: 0,
    crSum: 0,
    placements: Array.from({ length: teamCount }, () => 0),
  };
}

function summarizeMatches(matches: PlayerMatchRich[], teamCount: number): MatchesSummary {
  if (!matches.length) return emptySummary(teamCount);
  const placements = Array.from({ length: teamCount }, () => 0);
  let firsts = 0;
  let topHalf = 0;
  let placementSum = 0;
  let crSum = 0;

  matches.forEach((match) => {
    placements[match.place - 1] = (placements[match.place - 1] ?? 0) + 1;
    if (match.place === 1) firsts += 1;
    if (match.place <= Math.ceil(match.teamCount / 2)) topHalf += 1;
    placementSum += match.place;
    crSum += match.crDelta;
  });

  return {
    games: matches.length,
    firstRate: (firsts / matches.length) * 100,
    top4: (topHalf / matches.length) * 100,
    avgPlace: placementSum / matches.length,
    crSum,
    placements,
  };
}

function matchPassesQuery(
  match: PlayerMatchRich,
  query: PlayerMatchQuery,
  fixture: ProfileTelemetryLabFixture,
): boolean {
  if (query.result === "first" && match.place !== 1) return false;
  if (query.result === "top" && match.place > Math.ceil(match.teamCount / 2)) {
    return false;
  }
  if (query.result === "bottom" && match.place <= Math.ceil(match.teamCount / 2)) {
    return false;
  }
  if (
    query.champion !== undefined &&
    fixture.playerMatches.championsFacet[0]?.championId !== query.champion
  ) {
    return false;
  }
  return true;
}

export function isTelemetryLabProfile(riotId: string): boolean {
  return isMockQueryEnabled() && riotId === TELEMETRY_LAB_RIOT_ID;
}

export function isTelemetryLabMatch(matchId: string): boolean {
  return isMockQueryEnabled() && matchId === TELEMETRY_LAB_MATCH_ID;
}

export async function loadProfileForRoute(riotId: string): Promise<PlayerProfile> {
  if (!isTelemetryLabProfile(riotId)) return api.player(riotId);
  return structuredClone((await loadFixture()).profile);
}

export async function loadPlayerMatchesForRoute(
  riotId: string,
  query: PlayerMatchQuery = {},
): Promise<PlayerMatchesResponse> {
  if (!isTelemetryLabProfile(riotId)) return api.playerMatches(riotId, query);

  const fixture = await loadFixture();
  const allMatches = fixture.playerMatches.matches.filter((match) =>
    matchPassesQuery(match, query, fixture),
  );
  const offset = Math.max(0, query.offset ?? 0);
  const limit = Math.max(0, query.limit ?? fixture.playerMatches.limit);
  const matches = allMatches.slice(offset, offset + limit);
  const teamCount = fixture.playerMatches.matches[0]?.teamCount ?? 6;

  return structuredClone({
    ...fixture.playerMatches,
    total: allMatches.length,
    offset,
    limit,
    summary: summarizeMatches(allMatches, teamCount),
    matches,
  });
}

export async function loadTelemetryLabMatch(
  matchId: string,
): Promise<ProfileMatchDetail | null> {
  if (!isTelemetryLabMatch(matchId)) return null;
  const fixture = await loadFixture();
  if (fixture.matchDetail.matchId !== matchId) return null;
  return structuredClone(fixture.matchDetail);
}

function profilePlayer(detail: ProfileMatchDetail): ProfileMatchPlayer | null {
  return (
    detail.subteams
      .flatMap((team) => team.players)
      .find((player) => player.riotId === TELEMETRY_LAB_RIOT_ID) ?? null
  );
}

export async function loadTelemetryLabSummary(
  matchId: string,
): Promise<ProfileMatchSummary | null> {
  const detail = await loadTelemetryLabMatch(matchId);
  if (!detail) return null;
  const player = profilePlayer(detail);
  if (!player) return null;

  return structuredClone({
    level: player.level,
    rankLabel: player.rankLabel,
    kills: player.kills,
    deaths: player.deaths,
    assists: player.assists,
    killParticipation: player.killParticipation,
    damageToChampions: player.damageToChampions,
    damagePerMinute: player.damagePerMinute,
    goldEarned: player.goldEarned,
    items: player.items,
    augments: player.augments,
    mocked: true,
  });
}
