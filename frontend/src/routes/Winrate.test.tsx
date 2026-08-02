import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import type { ApiState } from "../hooks/useApi";
import type {
  ChampionSynergyGroupResponse,
  ChampRow,
  ChampTierlistResponse,
} from "../lib/types";
import { Winrate } from "./Winrate";

const rows: ChampRow[] = Array.from({ length: 20 }, (_, index) => ({
  rank: index + 1,
  championId: index + 1,
  champion: { c1: "#333333", c2: "#111111" },
  championIconUrl: null,
  name: `Campeão ${index + 1}`,
  role: "Mago",
  games: 1_000 - index,
  top4: 80 - index,
  first: 30 - index / 2,
  avgPlace: 2.5 + index / 100,
  pickRate: 10 - index / 10,
  banRate: 0,
  tier: index < 3 ? "S" : "A",
  winrateDelta: 0,
  topPlayer: null,
}));

const tierlist: ChampTierlistResponse = {
  updatedAt: "2026-07-25T00:00:00Z",
  patch: "16.14",
  region: "br",
  format: "3v3",
  metric: "top4",
  sampleSize: 20_000,
  tiers: [],
  table: rows,
};

const synergyGroups: ChampionSynergyGroupResponse = {
  updatedAt: "2026-07-25T00:00:00Z",
  season: 1,
  format: "3v3",
  size: 3,
  sampleSize: 1_000,
  minGames: 100,
  groups: [
    {
      champions: [1, 2, 3].map((championId) => ({
        championId,
        name: `Campeão ${championId}`,
        championIconUrl: null,
        colors: { c1: "#333333", c2: "#111111" },
      })),
      games: 1_000,
      winRate: 61,
      firstRate: 28,
      avgPlace: 3.2,
    },
  ],
};

const idleState: ApiState<never> = {
  data: null,
  loading: true,
  error: null,
  retry: () => {},
  refreshing: false,
  updatedAt: 0,
};

vi.mock("../hooks/useApi", () => ({
  useApi: (fetcher: () => unknown) => {
    const source = fetcher.toString();
    if (source.includes("api.champions") || source.includes("winrateApi.champions")) {
      return {
          data: tierlist,
          loading: false,
          error: null,
          retry: () => {},
          refreshing: false,
          updatedAt: Date.parse(tierlist.updatedAt),
        };
    }
    if (
      source.includes("api.championSynergyGroups") ||
      source.includes("winrateApi.championSynergyGroups")
    ) {
      return {
        data: synergyGroups,
        loading: false,
        error: null,
        retry: () => {},
        refreshing: false,
        updatedAt: Date.parse(synergyGroups.updatedAt),
      };
    }
    return idleState;
  },
}));

vi.mock("../hooks/useMediaQuery", () => ({
  useMediaQuery: () => false,
}));

vi.mock("../lib/motion", () => ({
  STATE_SPINNER_LOOP: {},
  useFlipList: () => ({ capture: () => {} }),
  useGsapEntrance: () => {},
  useGsapInteractions: () => {},
  useGsapLoop: () => {},
  useGsapSwap: () => {},
}));

afterEach(cleanup);

function renderWinrate() {
  return render(
    <MemoryRouter
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Winrate />
    </MemoryRouter>,
  );
}

describe("Winrate", () => {
  it("oferece paginação anterior/próxima sem ciclo e informa a faixa visível", () => {
    const { container } = renderWinrate();

    const navigation = screen.getByRole("navigation", { name: "Paginação dos campeões" });
    const previous = screen.getByRole("button", { name: "Campeões anteriores" }) as HTMLButtonElement;
    const next = screen.getByRole("button", { name: "Próximos campeões" }) as HTMLButtonElement;

    expect(navigation).toBeTruthy();
    expect(container.querySelector(".wr-page")?.hasAttribute("data-gsap-scope")).toBe(true);
    expect(screen.getByText("1–8 de 20")).toBeTruthy();
    expect(previous.disabled).toBe(true);
    expect(next.disabled).toBe(false);

    fireEvent.click(next);
    expect(screen.getByText("9–16 de 20")).toBeTruthy();
    expect(previous.disabled).toBe(false);

    fireEvent.click(next);
    expect(screen.getByText("17–20 de 20")).toBeTruthy();
    expect(next.disabled).toBe(true);
  });

  it("mantém os cabeçalhos operacionais em PT-BR", () => {
    renderWinrate();

    expect(screen.getByRole("columnheader", { name: "Campeão" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Col. média" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Escolha" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Top sinergias" })).toBeTruthy();
    expect(screen.getAllByText("TOP 4").length).toBeGreaterThan(0);
    expect(screen.queryByRole("columnheader", { name: "Champion" })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Position" })).toBeNull();
    expect(screen.queryByText("WIN")).toBeNull();
  });
});
