import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import type { SynergyTierlistResponse } from "../lib/types";
import { Sinergias } from "./Sinergias";

const data: SynergyTierlistResponse = {
  updatedAt: "2026-07-25T00:00:00Z",
  season: 3,
  format: "3v3",
  size: 3,
  sampleSize: 100,
  minGames: 15,
  tiers: [
    {
      key: "S",
      label: "Dominante",
      color: "#ff04dd",
      comps: [
        {
          champions: [
            { championId: 17, name: "Teemo", championIconUrl: null, colors: { c1: "#514421", c2: "#12110c" } },
            { championId: 27, name: "Singed", championIconUrl: null, colors: { c1: "#423263", c2: "#111111" } },
            { championId: 69, name: "Cassiopeia", championIconUrl: null, colors: { c1: "#744523", c2: "#18110f" } },
          ],
          games: 17,
          winRate: 94,
          firstRate: 52,
          avgPlace: 2.65,
        },
      ],
    },
  ],
  table: [],
};

vi.mock("../hooks/useApi", () => ({
  useApi: () => ({
    data,
    loading: false,
    error: null,
    retry: () => {},
    refreshing: true,
    updatedAt: Date.parse(data.updatedAt),
  }),
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

describe("Sinergias", () => {
  it("expõe o estado do seletor e nomeia a métrica em PT-BR", () => {
    const { container } = render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Sinergias />
      </MemoryRouter>,
    );

    expect(container.querySelector(".tl-page")?.hasAttribute("data-gsap-scope")).toBe(true);
    expect(screen.getByRole("button", { name: "Trio" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Dupla" }).getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByRole("columnheader", { name: "Rank" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Composição" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Tier" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Top 4" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Col. média" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Jogos" })).toBeTruthy();
    expect(screen.getByRole("row", { name: /Teemo.*Singed.*Cassiopeia/i })).toBeTruthy();
    expect(screen.getAllByTestId("synergy-champion-face")).toHaveLength(3);
    expect(screen.getByText("TOP 4")).toBeTruthy();
    expect(screen.queryByText("WIN")).toBeNull();
  });

  it("declara quando a troca mantém temporariamente a composição anterior", () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Sinergias />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Dupla" }));

    expect(screen.getByRole("status").textContent).toBe(
      "Atualizando para duplas…",
    );
    expect(
      screen.getByRole("table", { name: "Ranking de sinergias" }).getAttribute(
        "aria-busy",
      ),
    ).toBe("true");
  });
});
