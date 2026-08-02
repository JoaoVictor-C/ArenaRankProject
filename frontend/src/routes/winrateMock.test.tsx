import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Winrate } from "./Winrate";

const apiMocks = vi.hoisted(() => ({
  champions: vi.fn(),
  championMains: vi.fn(),
  championBuild: vi.fn(),
  topBuild: vi.fn(),
  championSynergyGroups: vi.fn(),
}));

vi.mock("../lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: apiMocks,
}));

vi.mock("../lib/motion", () => ({
  STATE_SPINNER_LOOP: {},
  useFlipList: () => ({ capture: () => {} }),
  useGsapEntrance: () => {},
  useGsapInteractions: () => {},
  useGsapLoop: () => {},
  useGsapSwap: () => {},
}));

vi.mock("../hooks/useMediaQuery", () => ({
  useMediaQuery: () => false,
}));

const buildEntry = {
  id: 9001,
  name: "Augment Mockado",
  iconUrl: null,
  tier: "S" as const,
  games: 900,
  avgPlace: 2.95,
  top1: 31,
  top4: 68,
  pickRate: 18.5,
  rarity: "prismatic" as const,
};

const fixture = {
  tierlist: {
    updatedAt: "2026-07-30T12:00:00Z",
    patch: "MOCK",
    region: "br",
    format: "3v3",
    metric: "top4",
    sampleSize: 12_345,
    tiers: [],
    table: [
      {
        rank: 1,
        championId: 101,
        champion: { c1: "#9d4edd", c2: "#240046" },
        championIconUrl: null,
        name: "Campeão Mockado",
        role: "Mago",
        games: 1_234,
        top4: 67.8,
        first: 29.4,
        avgPlace: 2.91,
        pickRate: 8.2,
        banRate: 1.1,
        tier: "S+",
        winrateDelta: 2.4,
        topPlayer: null,
      },
    ],
  },
  mains: {
    championId: 101,
    name: "Campeão Mockado",
    championIconUrl: null,
    players: [
      {
        name: "Main Mockado",
        handle: "#MOCK",
        avatar: { c1: "#00b4d8", c2: "#03045e" },
        profileIconUrl: null,
        games: 88,
        winrate: 72,
        avgPlace: 2.4,
      },
    ],
  },
  build: {
    championId: 101,
    name: "Campeão Mockado",
    championIconUrl: null,
    patch: "MOCK",
    updatedAt: "2026-07-30T12:00:00Z",
    games: 1_234,
    avgPlace: 2.91,
    tier: "S+" as const,
    top1: 29.4,
    top4: 67.8,
    minGames: 20,
    augments: { prismatic: [buildEntry], gold: [], silver: [] },
    items: [],
    boots: [],
    teammates: [],
  },
  topBuild: {
    updatedAt: "2026-07-30T12:00:00Z",
    patch: "MOCK",
    games: 12_345,
    champions: 1,
    minGames: 20,
    augments: [buildEntry],
    items: [],
  },
  synergyGroups: {
    updatedAt: "2026-07-30T12:00:00Z",
    season: 1,
    format: "3v3",
    size: 3,
    sampleSize: 321,
    minGames: 20,
    groups: [
      {
        champions: ["Trio A", "Trio B", "Trio C"].map((name, index) => ({
          championId: 201 + index,
          name,
          championIconUrl: null,
          colors: { c1: "#48cae4", c2: "#023e8a" },
        })),
        games: 321,
        winRate: 74,
        firstRate: 36,
        avgPlace: 2.7,
      },
    ],
  },
};

beforeEach(() => {
  window.history.replaceState({}, "", "/winrate?mock=1");
  Object.values(apiMocks).forEach((mock) => {
    mock.mockReset();
    mock.mockRejectedValue(new Error("A API real não deve ser chamada no mock."));
  });
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(fixture), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
});

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
  vi.unstubAllGlobals();
});

describe("Winrate — dados mockados", () => {
  it("renderiza todos os painéis de /winrate?mock=1 sem consultar a API real", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={["/winrate?mock=1"]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <Winrate />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect((await screen.findAllByText("Campeão Mockado")).length).toBeGreaterThan(0);
    expect(screen.getByText(/Patch MOCK/)).toBeTruthy();
    expect(await screen.findByText("Main Mockado")).toBeTruthy();
    expect((await screen.findAllByText("Augment Mockado")).length).toBeGreaterThan(0);
    expect(await screen.findByText("Trio A · Trio B · Trio C")).toBeTruthy();
  });
});
