import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import type { ApiState } from "../hooks/useApi";
import type { ChampTierlistResponse } from "../lib/types";
import { AreaChart, Campeao } from "./Campeao";

const tierlist: ChampTierlistResponse = {
  updatedAt: "2026-07-25T00:00:00Z",
  patch: "16.14",
  region: "br",
  format: "3v3",
  metric: "top4",
  sampleSize: 6_770,
  tiers: [],
  table: [
    {
      rank: 1,
      championId: 50,
      champion: { c1: "#521d27", c2: "#111111" },
      championIconUrl: null,
      name: "Swain",
      role: "Mago",
      games: 6_770,
      top4: 74.8,
      first: 25.1,
      avgPlace: 3.25,
      pickRate: 1,
      banRate: 0,
      tier: "S+",
      winrateDelta: -0.2,
      topPlayer: null,
    },
  ],
};

const loadingState: ApiState<never> = {
  data: null,
  loading: true,
  error: null,
  retry: () => {},
  refreshing: false,
  updatedAt: 0,
};

const fifteenDates = [
  "2026-07-11",
  "2026-07-12",
  "2026-07-13",
  "2026-07-14",
  "2026-07-15",
  "2026-07-16",
  "2026-07-17",
  "2026-07-18",
  "2026-07-19",
  "2026-07-20",
  "2026-07-21",
  "2026-07-22",
  "2026-07-23",
  "2026-07-24",
  "2026-07-25",
];

vi.mock("../hooks/useApi", () => ({
  useApi: (fetcher: () => unknown) =>
    fetcher.toString().includes("api.champions")
      ? {
          data: tierlist,
          loading: false,
          error: null,
          retry: () => {},
          refreshing: false,
          updatedAt: Date.parse(tierlist.updatedAt),
        }
      : loadingState,
}));

vi.mock("../lib/motion", () => ({
  STATE_SPINNER_LOOP: {},
  useReveal: () => {},
  useDrawCharts: () => {},
  useGsapEntrance: () => {},
  useGsapInteractions: () => {},
  useGsapLoop: () => {},
  useGsapSwap: () => {},
}));

afterEach(cleanup);

describe("Campeao", () => {
  it("mantém gráficos percentuais na escala absoluta de zero a cem", () => {
    const { container } = render(
      <AreaChart
        values={[20, 40, 60]}
        color="#ffcc00"
        format={(value) => `${value}%`}
        domain={[0, 100]}
      />,
    );

    const labels = Array.from(
      container.querySelectorAll("[data-chart-y-label]"),
      (label) => label.textContent,
    );
    const line = container.querySelector("[data-chart-line]");

    expect(labels).toEqual(["100%", "50%", "0%"]);
    expect(line?.getAttribute("d")).toMatch(/^M40(?:\.0)? 108\.8/);
  });

  it("renderiza a série diária como uma curva arredondada e espessa", () => {
    const { container } = render(
      <AreaChart
        values={[25.1, 24.8, 26.2, 25.7]}
        dates={[
          "2026-07-20",
          "2026-07-21",
          "2026-07-23",
          "2026-07-24",
        ]}
        color="#ffcc00"
        format={(value) => `${value}%`}
        drawDuration={2}
        daily
      />,
    );

    const svg = container.querySelector("svg");
    const line = container.querySelector("[data-chart-line]");

    expect(svg?.getAttribute("data-draw-duration")).toBe("2");
    expect(line?.getAttribute("d")?.match(/\bC/g)).toHaveLength(3);
    expect(line?.getAttribute("stroke-width")).toBe("3.25");
    expect(line?.getAttribute("stroke-linecap")).toBe("round");
    expect(line?.getAttribute("stroke-linejoin")).toBe("round");
    expect(container.querySelectorAll("[data-chart-mark]")).toHaveLength(4);
  });

  it("mantém os quinze dias mais recentes legíveis no gráfico compacto", () => {
    const { container } = render(
      <AreaChart
        values={fifteenDates.map((_, index) => 14 + (index % 7))}
        dates={fifteenDates}
        color="#ffcc00"
        format={(value) => `${value}%`}
        domain={[0, 100]}
        daily
      />,
    );

    const labels = Array.from(
      container.querySelectorAll("[data-chart-day-label]"),
      (label) => label.textContent,
    );
    const months = Array.from(
      container.querySelectorAll("[data-chart-month-label]"),
      (label) => label.textContent,
    );
    const line = container.querySelector("[data-chart-line]");
    const svg = container.querySelector("svg");

    expect(labels).toEqual([
      "11",
      "12",
      "13",
      "14",
      "15",
      "16",
      "17",
      "18",
      "19",
      "20",
      "21",
      "22",
      "23",
      "24",
      "25",
    ]);
    expect(months).toEqual(["JUL"]);
    expect(container.querySelectorAll("[data-chart-mark]")).toHaveLength(15);
    expect(line?.getAttribute("d")?.match(/\bC/g)).toHaveLength(14);
    expect(svg?.getAttribute("viewBox")).toBe("0 0 300 158");
    expect(svg?.style.minWidth).toBe("");
  });

  it("não apresenta requests pendentes como lacunas definitivas do backend", () => {
    const { container } = render(
      <MemoryRouter
        initialEntries={["/campeao/50"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/campeao/:championId" element={<Campeao />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("Carregando força por round…")).toBeTruthy();
    expect(screen.getByText("Carregando histórico diário…")).toBeTruthy();
    expect(screen.getByText("últimos 15 dias")).toBeTruthy();
    expect(screen.getByText("Carregando confrontos…")).toBeTruthy();
    expect(screen.getByText("Carregando variantes de build…")).toBeTruthy();
    expect(screen.queryByText(/ingestão de rounds está em preparação/i)).toBeNull();
    expect(screen.queryByText(/histórico diário ainda curto/i)).toBeNull();

    const heroMetrics = Array.from(container.querySelectorAll(".cmp-k-v"));
    expect(heroMetrics.map((metric) => metric.textContent)).toEqual(["74,8%", "25,1%", "3,25", "1,0%"]);
    expect(heroMetrics.every((metric) => !metric.hasAttribute("data-countup"))).toBe(true);
    expect(container.querySelector(".cmp-page")?.hasAttribute("data-gsap-scope")).toBe(true);
  });
});
