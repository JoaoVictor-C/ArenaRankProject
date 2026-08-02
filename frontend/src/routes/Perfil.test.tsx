import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import type {
  MatchDetail,
  PlayerMatchesResponse,
  PlayerProfile,
} from "../lib/types";
import { Perfil } from "./Perfil";

const mockState = vi.hoisted(() => ({
  profile: null as PlayerProfile | null,
  playerMatches: vi.fn(),
  match: vi.fn(),
  telemetryMatch: vi.fn(),
  telemetrySummary: vi.fn(),
  entrance: vi.fn(),
  loops: vi.fn(),
}));

vi.mock("../hooks/useApi", () => ({
  useApi: () => ({
    data: mockState.profile,
    loading: false,
    error: null,
    retry: vi.fn(),
    refreshing: false,
    updatedAt: Date.parse("2026-07-27T03:00:00Z"),
  }),
}));

vi.mock("../lib/api", () => ({
  api: {
    player: vi.fn(),
    playerMatches: mockState.playerMatches,
    match: mockState.match,
  },
}));

vi.mock("../lib/motion", () => ({
  STATE_SPINNER_LOOP: {},
  useDrawCharts: () => {},
  useGsapEntrance: mockState.entrance,
  useGsapInteractions: () => {},
  useGsapLoop: mockState.loops,
  useGsapMatchDetail: () => {},
  loadAmbientMotion: async () => null,
  loadMotion: async () => null,
  prefersReducedMotion: () => true,
}));

vi.mock("./profileTelemetryLab", () => ({
  isTelemetryLabProfile: (riotId: string) => riotId === "ArenaLab#MOCK",
  loadProfileForRoute: vi.fn(),
  loadPlayerMatchesForRoute: (
    riotId: string,
    options: {
      offset?: number;
      limit?: number;
      result?: "first" | "top" | "bottom";
      champion?: number;
    },
  ) => mockState.playerMatches(riotId, options),
  loadTelemetryLabMatch: mockState.telemetryMatch,
  loadTelemetryLabSummary: mockState.telemetrySummary,
}));

const profile: PlayerProfile = {
  riotId: "Urs#0000",
  name: "Urs",
  handle: "#0000",
  region: "br",
  avatar: { c1: "#6c52bc", c2: "#17121f" },
  cr: 2070,
  rank: 1,
  tier: "top1",
  provisional: false,
  delta7d: 137,
  wins: 45,
  losses: 17,
  winrate: 72.6,
  top4: 96.8,
  avgPlace: 1.4,
  form: [{ place: 1 }, { place: 1 }, { place: 2 }],
  crHistory: [
    { ts: "2026-07-12T12:00:00-03:00", cr: 1933, lo: 1900, hi: 1960 },
    { ts: "2026-07-26T16:00:00-03:00", cr: 2070, lo: 2030, hi: 2100 },
  ],
  tags: [{ kind: "champrank", label: "Top 16 Fiora", icon: "" }],
  matches: [],
  champions: [
    {
      champion: { c1: "#b58d72", c2: "#44314c" },
      championId: 114,
      championIconUrl: undefined,
      championSplashUrl: null,
      name: "Fiora",
      games: 27,
      firstRate: 60,
      top4: 92,
      avgPlace: 1.7,
      crImpact: 661,
      spark: [1, 2, 3],
    },
  ],
  h2h: [],
  seasons: [],
  profileIconUrl: undefined,
};

const matches: PlayerMatchesResponse = {
  total: 3,
  offset: 0,
  limit: 20,
  summary: {
    games: 3,
    firstRate: 66.7,
    top4: 100,
    avgPlace: 1.3,
    crSum: 42,
    placements: [2, 1, 0, 0, 0, 0],
  },
  championsFacet: [
    {
      championId: 114,
      name: "Fiora",
      champion: { c1: "#b58d72", c2: "#44314c" },
      championIconUrl: undefined,
      games: 2,
    },
  ],
  matches: [
    {
      matchId: "match-1",
      ts: "2026-07-26T16:00:00-03:00",
      champion: { c1: "#b58d72", c2: "#44314c" },
      championName: "Fiora",
      championIconUrl: undefined,
      place: 1,
      crDelta: 30,
      crBefore: 2040,
      crAfter: 2070,
      format: "3v3",
      teamCount: 6,
      durationSec: 1560,
      premade: false,
      modifiers: [],
    },
    {
      matchId: "match-2",
      ts: "2026-07-26T12:00:00-03:00",
      champion: { c1: "#6c7d8e", c2: "#182129" },
      championName: "Viego",
      championIconUrl: undefined,
      place: 2,
      crDelta: -8,
      crBefore: 2048,
      crAfter: 2040,
      format: "3v3",
      teamCount: 6,
      durationSec: 1430,
      premade: true,
      modifiers: [],
    },
    {
      matchId: "match-3",
      ts: "2026-07-25T22:00:00-03:00",
      champion: { c1: "#7f5b44", c2: "#181311" },
      championName: "Sett",
      championIconUrl: undefined,
      place: 1,
      crDelta: 20,
      crBefore: 2028,
      crAfter: 2048,
      format: "3v3",
      teamCount: 6,
      durationSec: 1500,
      premade: false,
      modifiers: [],
    },
  ],
};

const matchDetail: MatchDetail = {
  matchId: "match-1",
  format: "3v3",
  queueLabel: "Arena 3v3",
  playedAt: "2026-07-26T16:00:00-03:00",
  durationSec: 1560,
  patch: "26.14",
  processedAt: "2026-07-26T17:00:00-03:00",
  subteams: [
    {
      placement: 1,
      players: [
        {
          riotId: "Urs#0000",
          name: "Urs",
          handle: "#0000",
          avatar: { c1: "#6c52bc", c2: "#17121f" },
          champion: { c1: "#b58d72", c2: "#44314c" },
          championName: "Fiora",
          crBefore: 2040,
          crAfter: 2070,
          crDelta: 30,
          modifiers: [],
        },
        {
          riotId: "Dupla#BR1",
          name: "Dupla",
          handle: "#BR1",
          avatar: { c1: "#26646d", c2: "#10262b" },
          champion: { c1: "#9b7c4f", c2: "#322317" },
          championName: "Braum",
          crBefore: 1900,
          crAfter: 1922,
          crDelta: 22,
          modifiers: [],
        },
      ],
    },
    {
      placement: 2,
      players: [
        {
          riotId: "Rival Um#BR1",
          name: "Rival Um",
          handle: "#BR1",
          avatar: { c1: "#784448", c2: "#2a1214" },
          champion: { c1: "#9e5344", c2: "#321816" },
          championName: "Sett",
          crBefore: 2010,
          crAfter: 2002,
          crDelta: -8,
          modifiers: [],
        },
        {
          riotId: "Rival Dois#BR1",
          name: "Rival Dois",
          handle: "#BR1",
          avatar: { c1: "#4d507f", c2: "#171829" },
          champion: { c1: "#6665a2", c2: "#1e1d35" },
          championName: "Viego",
          crBefore: 1880,
          crAfter: 1872,
          crDelta: -8,
          modifiers: [],
        },
      ],
    },
  ],
};

function makeEnrichedMatchDetail(): MatchDetail {
  const enriched = structuredClone(matchDetail);
  Object.assign(enriched.subteams[0].players[0], {
    level: 18,
    rankLabel: "Gladiador · 2.070 PDL",
    kills: 18,
    deaths: 6,
    assists: 16,
    killParticipation: 74,
    damageToChampions: 76940,
    damagePerMinute: 3098,
    goldEarned: 18240,
    items: Array.from({ length: 7 }, (_, index) => ({
      id: index + 1,
      name: `Item completo ${index + 1}`,
      iconUrl: `/item-${index + 1}.png`,
    })),
    augments: Array.from({ length: 6 }, (_, index) => ({
      id: index + 101,
      name: `Augment completo ${index + 1}`,
      iconUrl: `/augment-${index + 1}.png`,
      rarity: index === 0 ? "prismatic" : "gold",
    })),
  });
  return enriched;
}

function renderProfile(path = "/perfil/Urs%230000") {
  return render(
    <MemoryRouter
      initialEntries={[path]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Routes>
        <Route path="/perfil/:riotId" element={<Perfil />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

beforeEach(() => {
  sessionStorage.clear();
  mockState.profile = profile;
  mockState.playerMatches.mockReset();
  mockState.playerMatches.mockResolvedValue(matches);
  mockState.match.mockReset();
  mockState.match.mockResolvedValue(matchDetail);
  mockState.telemetryMatch.mockReset();
  mockState.telemetryMatch.mockResolvedValue(null);
  mockState.telemetrySummary.mockReset();
  mockState.telemetrySummary.mockResolvedValue(null);
  mockState.entrance.mockClear();
  mockState.loops.mockClear();
  vi.stubGlobal(
    "ResizeObserver",
    class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

describe("Perfil", () => {
  it("conecta o perfil ao Lens e às âncoras compartilhadas", () => {
    renderProfile();

    expect(screen.getByRole("link", { name: /lens/i }).getAttribute("href"))
      .toBe("/perfil/Urs%230000/lens");
    expect(document.getElementById("partidas")).toBeTruthy();
    expect(document.getElementById("campeoes")).toBeTruthy();
  });

  it("estrutura o nick como uma placa cube-parent com dois marcadores", () => {
    renderProfile();

    const heading = screen.getByRole("heading", { level: 1 });
    const cube = heading.closest(".pfb-name-cube");

    expect(cube?.querySelector(".pfb-name-cube__plate")).toBe(heading);
    expect(cube?.querySelectorAll(".pfb-name-cube__marker")).toHaveLength(2);
    expect(mockState.entrance).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        steps: expect.arrayContaining([
          expect.objectContaining({
            selector: ".pfb-name-cube",
            from: { scaleX: 0, transformOrigin: "0% 50%" },
            duration: 1,
          }),
        ]),
      }),
    );
    // Os marcadores saíram da lista de loops declarativos: o percurso deles é
    // a largura MEDIDA do nick, que só existe em runtime. Um `to` fixo aqui
    // significaria de volta o percurso arbitrário de 20px, que não tem relação
    // com o tamanho do nome.
    const declaredSelectors = mockState.loops.mock.calls
      .flatMap((call: unknown[]) => (Array.isArray(call[1]) ? call[1] : []))
      .map((loop: unknown) => (loop as { selector?: unknown }).selector)
      .filter((selector: unknown): selector is string => typeof selector === "string");
    expect(
      declaredSelectors.filter((selector) => selector.includes("pfb-name-cube__marker")),
    ).toHaveLength(0);

    // E o nick precisa continuar marcado, senão a medição não acha o alvo.
    expect(cube?.querySelector("[data-profile-nick]")).not.toBeNull();
  });

  it("declara de forma persistente o perfil fictício canônico", () => {
    mockState.profile = {
      ...profile,
      riotId: "ArenaLab#MOCK",
      name: "ArenaLab",
      handle: "#MOCK",
    };

    renderProfile("/perfil/ArenaLab%23MOCK?mock=1");

    expect(screen.getByText("Perfil fictício · Dados mockados")).toBeTruthy();
  });

  it("prioriza desempenho recente e agrupa o histórico por dia", async () => {
    renderProfile();

    const performance = await screen.findByRole("region", {
      name: "Desempenho recente",
    });
    const history = screen.getByRole("region", {
      name: "Histórico de partidas",
    });

    expect(performance.compareDocumentPosition(history)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    expect(screen.getByText("26 JUL")).toBeTruthy();
    expect(screen.getByText("2 partidas")).toBeTruthy();
    expect(screen.getByText("+22 PDL")).toBeTruthy();
    expect(screen.queryByText(/\bKDA\b|\bCS\/m\b|pings/i)).toBeNull();
  });

  it("compartilha o endereço real do perfil e confirma o resultado", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    renderProfile();

    const share = await screen.findByRole("button", {
      name: "Compartilhar perfil",
    });
    fireEvent.click(share);

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Link copiado")).toBeTruthy();
  });

  it("carrega todos os times na primeira expansão e reutiliza o detalhe", async () => {
    renderProfile();

    const row = (await screen.findAllByRole("button", { expanded: false }))[0];
    fireEvent.click(row);

    await waitFor(() => expect(mockState.match).toHaveBeenCalledWith("match-1"));
    expect(await screen.findByText("Rival Um#BR1")).toBeTruthy();
    expect(screen.getByText("Rival Dois#BR1")).toBeTruthy();

    fireEvent.click(row);
    fireEvent.click(row);

    expect(mockState.match).toHaveBeenCalledTimes(1);
  });

  it("declara campos de loadout ainda não ingeridos no detalhe real", async () => {
    renderProfile();

    const row = (await screen.findAllByRole("button", { expanded: false }))[0];
    fireEvent.click(row);

    expect(
      (await screen.findAllByText("Augments aguardando ingestão")).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText("Estatísticas aguardando ingestão").length,
    ).toBeGreaterThan(0);
  });

  it("exibe o loadout e a telemetria completos quando os campos existem", async () => {
    mockState.match.mockResolvedValueOnce(makeEnrichedMatchDetail());
    renderProfile();

    const row = (await screen.findAllByRole("button", { expanded: false }))[0];
    fireEvent.click(row);

    expect(await screen.findByText("Gladiador · 2.070 PDL")).toBeTruthy();
    expect(screen.getAllByText("18/6/16").length).toBeGreaterThan(0);
    expect(screen.getAllByText("74% part.").length).toBeGreaterThan(0);
    expect(screen.getAllByText("3.098 dano/min").length).toBeGreaterThan(0);
    expect(screen.getAllByAltText("Item completo 1").length).toBeGreaterThan(0);
    expect(
      screen.getAllByAltText(/^Augment completo /).length,
    ).toBeGreaterThanOrEqual(6);
  });

  it("prioriza o detalhe fictício sem chamar a API de partida", async () => {
    mockState.profile = {
      ...profile,
      riotId: "ArenaLab#MOCK",
      name: "ArenaLab",
      handle: "#MOCK",
    };
    mockState.telemetryMatch.mockResolvedValueOnce({
      ...makeEnrichedMatchDetail(),
      mockedFields: ["items", "augments", "combat"],
    });

    renderProfile("/perfil/ArenaLab%23MOCK?mock=1");
    fireEvent.click((await screen.findAllByRole("button", { expanded: false }))[0]);

    expect(await screen.findByText("Gladiador · 2.070 PDL")).toBeTruthy();
    expect(mockState.match).not.toHaveBeenCalled();
  });

  it("explica somente os fatores ativos como impactos reais em PDL", async () => {
    mockState.playerMatches.mockResolvedValueOnce({
      ...matches,
      matches: [
        {
          ...matches.matches[0],
          premade: true,
          modifiers: [
            {
              kind: "colocacao",
              label: "Colocação",
              value: 25,
              pdlImpact: 7,
              icon: "leaderboard",
            },
            {
              kind: "grupo",
              label: "Penalidade de grupo",
              value: -15,
              pdlImpact: -4,
              icon: "group",
            },
          ],
        },
        ...matches.matches.slice(1),
      ],
    });
    renderProfile();

    fireEvent.click((await screen.findAllByRole("button", { expanded: false }))[0]);

    expect(
      await screen.findByRole("region", { name: "Fatores do PDL" }),
    ).toBeTruthy();
    expect(screen.getAllByText("+7 PDL")).toHaveLength(3);
    expect(screen.getAllByText("−4 PDL")).toHaveLength(2);
    expect(
      screen.getAllByText("Você ganhou 7 PDL por terminar em 1º."),
    ).toHaveLength(3);
    expect(screen.queryByText("Sinais de Arena")).toBeNull();
  });

  it("explica uma colocação negativa como PDL perdido", async () => {
    mockState.playerMatches.mockResolvedValueOnce({
      ...matches,
      matches: [
        {
          ...matches.matches[0],
          place: 6,
          crDelta: -12,
          modifiers: [
            {
              kind: "colocacao",
              label: "Colocação",
              value: 0,
              pdlImpact: -12,
              icon: "leaderboard",
            },
          ],
        },
        ...matches.matches.slice(1),
      ],
    });
    renderProfile();

    fireEvent.click((await screen.findAllByRole("button", { expanded: false }))[0]);

    expect(
      await screen.findByText("Você perdeu 12 PDL por terminar em 6º."),
    ).toBeTruthy();
  });
});
