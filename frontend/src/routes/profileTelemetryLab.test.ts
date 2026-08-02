import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../lib/api";
import {
  isTelemetryLabProfile,
  loadPlayerMatchesForRoute,
  loadProfileForRoute,
  loadTelemetryLabMatch,
  loadTelemetryLabSummary,
} from "./profileTelemetryLab";

const apiMocks = vi.hoisted(() => ({
  player: vi.fn(),
  playerMatches: vi.fn(),
}));

vi.mock("../lib/api", () => ({
  api: {
    player: apiMocks.player,
    playerMatches: apiMocks.playerMatches,
  },
}));

async function readFixture(): Promise<string> {
  return readFile(resolve(process.cwd(), "public/fixtures/profile-telemetry-lab.json"), "utf8");
}

beforeEach(async () => {
  window.history.replaceState({}, "", "/perfil/ArenaLab%23MOCK?mock=1");
  apiMocks.player.mockReset();
  apiMocks.playerMatches.mockReset();
  const fixture = await readFixture();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(fixture, {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("profileTelemetryLab", () => {
  it("serve o laboratório canônico sem chamar a API real", async () => {
    expect(isTelemetryLabProfile("ArenaLab#MOCK")).toBe(true);

    await expect(loadProfileForRoute("ArenaLab#MOCK")).resolves.toMatchObject({
      riotId: "ArenaLab#MOCK",
      cr: 2348,
    });
    await expect(
      loadPlayerMatchesForRoute("ArenaLab#MOCK", { limit: 20, offset: 0 }),
    ).resolves.toMatchObject({ total: 1 });

    expect(api.player).not.toHaveBeenCalled();
    expect(api.playerMatches).not.toHaveBeenCalled();
  });

  it("mantém seis times e telemetria completa para dezoito jogadores", async () => {
    const detail = await loadTelemetryLabMatch("telemetry-lab-3v3-001");
    const players = detail?.subteams.flatMap((team) => team.players) ?? [];

    expect(detail?.subteams).toHaveLength(6);
    expect(players).toHaveLength(18);
    players.forEach((player) => {
      expect(player.items).toHaveLength(7);
      expect(player.augments).toHaveLength(6);
      expect(player.damagePerMinute).toBeGreaterThan(0);
    });
  });

  it("mantém resumo e detalhe do jogador principal consistentes", async () => {
    const detail = await loadTelemetryLabMatch("telemetry-lab-3v3-001");
    const summary = await loadTelemetryLabSummary("telemetry-lab-3v3-001");
    const player = detail?.subteams[0].players[0];

    expect(player).toBeDefined();
    expect(summary).toMatchObject({
      kills: player?.kills,
      deaths: player?.deaths,
      assists: player?.assists,
      killParticipation: player?.killParticipation,
      damageToChampions: player?.damageToChampions,
      damagePerMinute: player?.damagePerMinute,
      goldEarned: player?.goldEarned,
      mocked: true,
    });
    expect(summary?.items).toEqual(player?.items);
    expect(summary?.augments).toEqual(player?.augments);
  });

  it("aplica filtros do histórico sem vazar a partida da fixture", async () => {
    const response = await loadPlayerMatchesForRoute("ArenaLab#MOCK", {
      limit: 20,
      offset: 0,
      result: "bottom",
    });

    expect(response.matches).toEqual([]);
    expect(response.total).toBe(0);
    expect(response.summary).toMatchObject({
      games: 0,
      firstRate: 0,
      top4: 0,
      avgPlace: 0,
      crSum: 0,
    });
  });

  it("mantém a API real para o Riot ID canônico sem mock=1", async () => {
    window.history.replaceState({}, "", "/perfil/ArenaLab%23MOCK");
    apiMocks.player.mockResolvedValue({ riotId: "ArenaLab#MOCK" });

    await loadProfileForRoute("ArenaLab#MOCK");

    expect(isTelemetryLabProfile("ArenaLab#MOCK")).toBe(false);
    expect(api.player).toHaveBeenCalledWith("ArenaLab#MOCK");
  });

  it("mantém qualquer outro Riot ID na API real", async () => {
    apiMocks.player.mockResolvedValue({ riotId: "Outro#BR1" });
    apiMocks.playerMatches.mockResolvedValue({ matches: [] });

    await loadProfileForRoute("Outro#BR1");
    await loadPlayerMatchesForRoute("Outro#BR1", { limit: 20, offset: 0 });

    expect(api.player).toHaveBeenCalledWith("Outro#BR1");
    expect(api.playerMatches).toHaveBeenCalledWith("Outro#BR1", {
      limit: 20,
      offset: 0,
    });
  });
});
