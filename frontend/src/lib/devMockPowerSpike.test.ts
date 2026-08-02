import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChampionRoundsResponse } from "./types";
import { devMockResponse } from "./devMock";

const powerSpike: ChampionRoundsResponse = {
  championId: 50,
  name: "Campeão",
  championIconUrl: null,
  season: 3,
  format: "3v3",
  sampleSize: 53_457,
  minGames: 50,
  peakRound: 6,
  rounds: Array.from({ length: 13 }, (_, index) => ({
    round: index + 1,
    label: index === 12 ? "R13+" : `R${index + 1}`,
    winRate: 45 + index,
    games: 6_000 - index * 300,
  })),
};

afterEach(() => {
  sessionStorage.clear();
  window.history.replaceState({}, "", "/");
  vi.unstubAllGlobals();
});

describe("devMockResponse — Power Spike", () => {
  it("usa o fixture dedicado e o replica para qualquer campeão", async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request) => ({
      json: async () =>
        String(input).includes("champion-power-spike.json")
          ? powerSpike
          : {
              rounds: powerSpike,
              matchups: {},
              builds: {},
              buildPatch: {},
            },
    }));
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState({}, "", "/campeao/50?mock=1");

    const swain = (await devMockResponse(
      "/champions/50/rounds?season=3&format=3v3",
    )) as ChampionRoundsResponse;
    const ahri = (await devMockResponse(
      "/champions/103/rounds?season=3&format=3v3",
    )) as ChampionRoundsResponse;

    expect(fetchMock).toHaveBeenCalledWith(
      "/fixtures/champion-power-spike.json",
    );
    expect(swain.championId).toBe(50);
    expect(ahri.championId).toBe(103);
    expect(swain.rounds.map((round) => round.label)).toEqual([
      "R1",
      "R2",
      "R3",
      "R4",
      "R5",
      "R6",
      "R7",
      "R8",
      "R9",
      "R10",
      "R11",
      "R12",
      "R13+",
    ]);
    expect(ahri.rounds).toEqual(swain.rounds);
  });
});
