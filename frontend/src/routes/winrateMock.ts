import { api } from "../lib/api";
import type {
  ChampionBuildResponse,
  ChampionMainsResponse,
  ChampionSynergyGroupResponse,
  ChampTierlistResponse,
  TopBuildResponse,
} from "../lib/types";

interface WinrateFixture {
  tierlist: ChampTierlistResponse;
  mains: ChampionMainsResponse;
  build: ChampionBuildResponse;
  topBuild: TopBuildResponse;
  synergyGroups: ChampionSynergyGroupResponse;
}

const FIXTURE_PATH = "/fixtures/winrate.json";
let fixtureCache: Promise<WinrateFixture> | null = null;

export function isWinrateMockOn(): boolean {
  return (
    import.meta.env.DEV &&
    typeof window !== "undefined" &&
    window.location.pathname === "/winrate" &&
    new URLSearchParams(window.location.search).get("mock") === "1"
  );
}

function loadFixture(): Promise<WinrateFixture> {
  fixtureCache ??= fetch(FIXTURE_PATH).then((response) => {
    if (!response.ok) {
      throw new Error("Não foi possível carregar os dados fictícios de winrate.");
    }
    return response.json() as Promise<WinrateFixture>;
  });
  return fixtureCache;
}

function championIdentity(fixture: WinrateFixture, championId: number) {
  const row = fixture.tierlist.table.find((champion) => champion.championId === championId);
  return {
    championId,
    name: row?.name ?? fixture.build.name,
    championIconUrl: row?.championIconUrl ?? null,
  };
}

export const winrateApi = {
  async champions(
    options: {
      format?: string;
      metric?: "top4" | "first" | "avgplace" | "pick" | "ban";
      region?: string;
    } = {},
  ): Promise<ChampTierlistResponse> {
    if (!isWinrateMockOn()) return api.champions(options);
    return structuredClone((await loadFixture()).tierlist);
  },

  async championMains(
    championId: number,
    options: { season?: number; limit?: number } = {},
  ): Promise<ChampionMainsResponse> {
    if (!isWinrateMockOn()) return api.championMains(championId, options);
    const fixture = await loadFixture();
    return structuredClone({
      ...fixture.mains,
      ...championIdentity(fixture, championId),
      players: fixture.mains.players.slice(0, options.limit),
    });
  },

  async championBuild(championId: number): Promise<ChampionBuildResponse> {
    if (!isWinrateMockOn()) return api.championBuild(championId);
    const fixture = await loadFixture();
    return structuredClone({
      ...fixture.build,
      ...championIdentity(fixture, championId),
    });
  },

  async topBuild(): Promise<TopBuildResponse> {
    if (!isWinrateMockOn()) return api.topBuild();
    return structuredClone((await loadFixture()).topBuild);
  },

  async championSynergyGroups(
    options: { format?: string; season?: number; size?: number; limit?: number } = {},
  ): Promise<ChampionSynergyGroupResponse> {
    if (!isWinrateMockOn()) return api.championSynergyGroups(options);
    const fixture = await loadFixture();
    return structuredClone({
      ...fixture.synergyGroups,
      groups: fixture.synergyGroups.groups.slice(0, options.limit),
    });
  },
};
