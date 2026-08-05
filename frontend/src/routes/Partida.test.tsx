import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import * as React from "react";

import type { MatchDetail, MatchPlayer } from "../lib/types";
import { createPartidaDossier, type PartidaDossier } from "./partidaDossierModel";
import { Partida } from "./Partida";

const { dossierMotion, loadDossier } = vi.hoisted(() => ({
  dossierMotion: vi.fn(),
  loadDossier: vi.fn(),
}));

vi.mock("./partidaDossierModel", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./partidaDossierModel")>();
  return {
    ...actual,
    loadPartidaDossier: loadDossier,
  };
});

vi.mock("./partidaDossierMotion", () => ({
  usePartidaDossierMotion: dossierMotion,
}));

const matchId = "632943d0-0954-58dc-ab66-13368d98b442";

function player(
  riotId: string,
  name: string,
  championName: string,
  crDelta: number,
): MatchPlayer {
  return {
    riotId,
    name,
    handle: "#BR1",
    avatar: { c1: "#111111", c2: "#222222" },
    champion: { c1: "#333333", c2: "#444444" },
    championName,
    crBefore: 2000,
    crAfter: 2000 + crDelta,
    crDelta,
    premade: false,
    // Raio-X do resultado (v1.4): o backend sempre envia pdlImpact real
    // (arena/rating/explain.py, via map_modifiers) — este fixture reflete
    // isso em vez de depender da reconstrução no cliente (removida).
    modifiers: [
      {
        kind: "colocacao",
        label: "Colocação",
        value: 0,
        pdlImpact: crDelta,
        icon: "leaderboard",
      },
    ],
  };
}

const detail: MatchDetail = {
  matchId,
  format: "3v3",
  queueLabel: "Arena 3v3",
  playedAt: "2026-07-27T18:00:00-03:00",
  durationSec: 900,
  patch: "26.14",
  processedAt: "2026-07-27T18:20:00-03:00",
  subteams: [
    {
      placement: 1,
      players: [
        player("Aliado#BR1", "Aurora", "Aurora", 30),
        player("Kayle#BR1", "Kayle", "Kayle", 20),
        player("Poppy#BR1", "Poppy", "Poppy", 10),
      ],
    },
    {
      placement: 2,
      players: [
        player("Shaco#BR1", "Shaco", "Shaco", -10),
        player("Twitch#BR1", "Twitch", "Twitch", -20),
        player("Ahri#BR1", "Ahri", "Ahri", -30),
      ],
    },
  ],
};

const dossier = { ...detail, ...createPartidaDossier(detail) };

vi.mock("../hooks/useApi", () => ({
  useApi: (load: () => Promise<PartidaDossier>) => {
    const loadRef = React.useRef(load);
    const [state, setState] = React.useState<{
      data: PartidaDossier | null;
      loading: boolean;
      error: Error | null;
    }>({ data: null, loading: true, error: null });

    React.useEffect(() => {
      let active = true;
      void loadRef.current().then((data) => {
        if (active) setState({ data, loading: false, error: null });
      });
      return () => {
        active = false;
      };
    }, []);

    return state;
  },
}));

vi.mock("../lib/motion", () => ({
  loadAmbientMotion: async () => null,
  prefersReducedMotion: () => true,
}));

const demoCombat = [
  {
    level: 18,
    kills: 14,
    deaths: 3,
    assists: 12,
    killParticipation: 82,
    damageToChampions: 76940,
    damagePerMinute: 1282,
    goldEarned: 15300,
  },
  {
    level: 17,
    kills: 13,
    deaths: 5,
    assists: 16,
    killParticipation: 72,
    damageToChampions: 58400,
    damagePerMinute: 987,
    goldEarned: 12300,
  },
  {
    level: 16,
    kills: 8,
    deaths: 6,
    assists: 19,
    killParticipation: 68,
    damageToChampions: 47060,
    damagePerMinute: 814,
    goldEarned: 11100,
  },
  {
    level: 16,
    kills: 7,
    deaths: 8,
    assists: 11,
    killParticipation: 61,
    damageToChampions: 51200,
    damagePerMinute: 902,
    goldEarned: 10900,
  },
  {
    level: 15,
    kills: 5,
    deaths: 9,
    assists: 13,
    killParticipation: 58,
    damageToChampions: 44300,
    damagePerMinute: 774,
    goldEarned: 9800,
  },
  {
    level: 15,
    kills: 4,
    deaths: 10,
    assists: 15,
    killParticipation: 55,
    damageToChampions: 39800,
    damagePerMinute: 721,
    goldEarned: 9400,
  },
] as const;

const demoTeams = detail.subteams.map((team, teamIndex) => ({
  ...team,
  players: team.players.map((basePlayer, playerIndex) => {
    const combat = demoCombat[(teamIndex * 3) + playerIndex];
    if (teamIndex !== 0 || playerIndex !== 1) {
      return { ...basePlayer, ...combat };
    }

    return {
      ...basePlayer,
      ...combat,
      name: "Keyans Eclipse",
      items: [
        {
          id: 1,
          name: "Espada do Eclipse",
          iconUrl: "https://example.test/item.png",
        },
      ],
      augments: [
        {
          id: 2,
          name: "Poder Prismático",
          iconUrl: "https://example.test/augment.png",
          rarity: "prismatic" as const,
        },
      ],
      modifiers: [
        {
          kind: "colocacao" as const,
          label: "1º lugar",
          value: 15,
          pdlImpact: 23,
          icon: "emoji_events",
        },
      ],
    };
  }),
}));

const demoDossier: PartidaDossier = {
  detail: {
    ...detail,
    subteams: demoTeams,
    mockedFields: ["items", "augments", "combat"],
  },
  teams: demoTeams,
  demo: true,
  telemetryAvailable: true,
};

const extraDemoTeams: PartidaDossier["teams"] = [3, 4, 5, 6].map(
  (placement) => ({
    placement,
    players: Array.from({ length: 3 }, (_, playerIndex) => ({
      ...player(
        `Equipe${placement}Jogador${playerIndex + 1}#BR1`,
        `Equipe ${placement} Jogador ${playerIndex + 1}`,
        `Campeão ${placement}.${playerIndex + 1}`,
        10 - placement - playerIndex,
      ),
      ...demoCombat[((placement - 1) * 3 + playerIndex) % demoCombat.length],
    })),
  }),
);

const sixTeamDemoTeams: PartidaDossier["teams"] = [
  ...demoTeams,
  ...extraDemoTeams,
];

const sixTeamDemoDossier: PartidaDossier = {
  ...demoDossier,
  detail: {
    ...demoDossier.detail,
    subteams: sixTeamDemoTeams,
  },
  teams: sixTeamDemoTeams,
};

const emptyLoadoutTeams = demoDossier.teams.map((team) => ({
  ...team,
  players: team.players.map((player) =>
    player.name === "Keyans Eclipse"
      ? { ...player, items: [], augments: [] }
      : player,
  ),
}));

const emptyLoadoutDossier: PartidaDossier = {
  ...demoDossier,
  detail: {
    ...demoDossier.detail,
    subteams: emptyLoadoutTeams,
  },
  teams: emptyLoadoutTeams,
};

const flaggedTeams = dossier.teams.map((team, teamIndex) => ({
  ...team,
  players: team.players.map((matchPlayer, playerIndex) => (
    teamIndex === 1 && playerIndex === 0
      ? {
          ...matchPlayer,
          integrity: [{ kind: "warn" as const, label: "Partida muito curta" }],
        }
      : matchPlayer
  )),
}));

const flaggedDossier: PartidaDossier = {
  ...dossier,
  detail: {
    ...dossier.detail,
    subteams: flaggedTeams,
  },
  teams: flaggedTeams,
};

const historicalNull = null;
const nullTelemetryTeams = dossier.teams.map((team) => ({
  ...team,
  players: team.players.map((matchPlayer) => ({
    ...matchPlayer,
    level: historicalNull,
    kills: historicalNull,
    deaths: historicalNull,
    assists: historicalNull,
    killParticipation: historicalNull,
    damageToChampions: historicalNull,
    damagePerMinute: historicalNull,
    goldEarned: historicalNull,
  })),
}));

const nullTelemetryDossier: PartidaDossier = {
  ...dossier,
  detail: {
    ...dossier.detail,
    subteams: nullTelemetryTeams,
  },
  teams: nullTelemetryTeams,
};

const partiallyNullTeams = demoDossier.teams.map((team, teamIndex) => ({
  ...team,
  players: team.players.map((matchPlayer, playerIndex) => (
    teamIndex === 0 && playerIndex === 1
      ? { ...matchPlayer, damageToChampions: historicalNull }
      : matchPlayer
  )),
}));

const partiallyNullDossier: PartidaDossier = {
  ...demoDossier,
  detail: {
    ...demoDossier.detail,
    subteams: partiallyNullTeams,
  },
  teams: partiallyNullTeams,
};

const partialCombatTeams = demoDossier.teams.map((team, teamIndex) => ({
  ...team,
  players: team.players.map((matchPlayer, playerIndex) => (
    teamIndex === 0 && playerIndex === 0
      ? {
          ...matchPlayer,
          level: historicalNull,
          kills: historicalNull,
          deaths: 4,
          assists: historicalNull,
          killParticipation: historicalNull,
          damageToChampions: 12345,
          damagePerMinute: historicalNull,
          goldEarned: 6789,
        }
      : matchPlayer
  )),
}));

const partialCombatDossier: PartidaDossier = {
  ...demoDossier,
  detail: {
    ...demoDossier.detail,
    subteams: partialCombatTeams,
  },
  teams: partialCombatTeams,
};

afterEach(() => {
  cleanup();
  dossierMotion.mockReset();
  loadDossier.mockReset();
});

function renderMatch(search = "", loadedDossier?: PartidaDossier): void {
  loadDossier.mockImplementation((_id: string, demo: boolean) =>
    Promise.resolve(loadedDossier ?? (demo ? demoDossier : dossier)),
  );

  render(
    <MemoryRouter initialEntries={[`/partida/${matchId}${search}`]}>
      <Routes>
        <Route path="/partida/:matchId" element={<Partida />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Partida", () => {
  it("inicia no primeiro colocado e troca a equipe pelo mapa orbital", async () => {
    renderMatch();

    expect(
      await screen.findByRole("heading", { name: /Aurora · Kayle · Poppy/i }),
    ).not.toBeNull();

    fireEvent.click(
      screen.getByRole("button", { name: /Selecionar equipe 2/i }),
    );

    expect(
      screen.getByRole("heading", { name: /Shaco · Twitch · Ahri/i }),
    ).not.toBeNull();
    expect(
      screen
        .getByRole("button", { name: /Selecionar equipe 2/i })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    const scoreboardTeams = screen
      .getByRole("region", { name: "Placar completo da partida" })
      .querySelectorAll("[data-score-team]");
    expect(scoreboardTeams[1].getAttribute("data-selected-team")).toBe("true");
    expect(scoreboardTeams[1].classList.contains("is-selected-team")).toBe(true);
  });

  it("já entrega o primeiro jogador ao movimento na renderização inicial", async () => {
    renderMatch();

    await screen.findByRole("heading", { name: /Aurora · Kayle · Poppy/i });

    const readyStates = dossierMotion.mock.calls
      .map((call) => call[1])
      .filter((state) => state?.ready);
    expect(readyStates[0]).toMatchObject({
      teamKey: 0,
      playerKey: "Aliado#BR1",
      direction: 0,
    });
    expect(
      readyStates.some((state) => state.playerKey === ""),
    ).toBe(false);
  });

  it("não publica identificadores nem metadados internos", async () => {
    renderMatch();

    await screen.findByRole("heading", { name: /Aurora · Kayle · Poppy/i });
    expect(screen.queryByText(matchId)).toBeNull();
    expect(
      screen.queryByText(/processedAt|idempotência|worker|commit/i),
    ).toBeNull();
  });

  it("troca combate, loadout e fatores ao selecionar outro jogador", async () => {
    renderMatch("?demo=1");

    expect(await screen.findByText("+30 PDL")).not.toBeNull();
    const keyansControl = await screen.findByRole("button", {
      name: "Selecionar Keyans Eclipse, Kayle, para análise",
    });
    fireEvent.click(
      keyansControl,
    );

    const analysis = screen.getByRole("region", {
      name: /Análise de Keyans Eclipse/i,
    });
    expect(within(analysis).getByText("K/D/A 13/5/16")).not.toBeNull();
    expect(keyansControl.getAttribute("data-selected")).toBe("true");
    expect(keyansControl.getAttribute("aria-pressed")).toBe("true");
    expect(analysis.querySelector("[data-match-item]")?.textContent).toContain(
      "Espada do Eclipse",
    );
    expect(analysis.querySelector("[data-match-augment]")?.textContent).toContain(
      "Poder Prismático",
    );
    expect(within(analysis).getByText("+23 PDL")).not.toBeNull();
    expect(within(analysis).queryByText("+30 PDL")).toBeNull();
    expect(within(keyansControl).getByText("Kayle")).not.toBeNull();
    const selectedScoreRow = screen
      .getByRole("button", { name: "Selecionar Keyans Eclipse no placar" })
      .closest("tr");
    expect(selectedScoreRow?.getAttribute("data-selected-player")).toBe("true");
    expect(selectedScoreRow?.classList.contains("is-selected-player")).toBe(true);
  });

  it("distingue loadout registrado vazio de dados não registrados", async () => {
    renderMatch("?demo=1", emptyLoadoutDossier);

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Selecionar Keyans Eclipse, Kayle, para análise",
      }),
    );

    const analysis = screen.getByRole("region", {
      name: /Análise de Keyans Eclipse/i,
    });
    expect(within(analysis).getByText("Nenhum item final nesta partida")).not.toBeNull();
    expect(within(analysis).getByText("Nenhum augment nesta partida")).not.toBeNull();
    expect(within(analysis).queryByText("Build não registrada")).toBeNull();
    expect(within(analysis).queryByText("Augments não registrados")).toBeNull();
  });

  it("mostra ausência honesta sem inventar 0/0/0", async () => {
    renderMatch();

    await screen.findByText("Telemetria não registrada nesta partida");
    expect(screen.queryByText("0/0/0")).toBeNull();
  });

  it("mantém todos os jogadores acessíveis no placar completo", async () => {
    renderMatch("?demo=1", sixTeamDemoDossier);

    const scoreboard = await screen.findByRole("region", {
      name: "Placar completo da partida",
    });
    expect(within(scoreboard).getAllByTestId("score-player")).toHaveLength(18);
    expect(within(scoreboard).getAllByText("182,4 mil").length).toBeGreaterThan(0);

    fireEvent.click(
      within(scoreboard).getByRole("button", {
        name: "Selecionar Equipe 6 Jogador 3 no placar",
      }),
    );

    const finalPlayerRow = within(scoreboard)
      .getByRole("button", {
        name: "Selecionar Equipe 6 Jogador 3 no placar",
      })
      .closest("tr");
    const finalTeam = finalPlayerRow?.closest("tbody");
    expect(finalPlayerRow?.getAttribute("data-selected-player")).toBe("true");
    expect(finalPlayerRow?.classList.contains("is-selected-player")).toBe(true);
    expect(finalTeam?.getAttribute("data-selected-team")).toBe("true");
    expect(finalTeam?.classList.contains("is-selected-team")).toBe(true);
    expect(
      screen.getByRole("region", {
        name: "Análise de Equipe 6 Jogador 3",
      }),
    ).not.toBeNull();
  });

  it("expõe a composição completa sem overflow estrutural", async () => {
    renderMatch("?demo=1", sixTeamDemoDossier);

    const orbitalMap = await screen.findByTestId("orbital-map");
    const teamControls = within(orbitalMap).getAllByRole("button");

    expect(orbitalMap).not.toBeNull();
    expect(teamControls).toHaveLength(6);
    [
      "pd-orbit-node--1",
      "pd-orbit-node--2",
      "pd-orbit-node--3",
      "pd-orbit-node--4",
      "pd-orbit-node--5",
      "pd-orbit-node--6",
    ].forEach((modifier, index) => {
      expect(teamControls[index].classList.contains(modifier)).toBe(true);
    });
    expect(
      screen.getByRole("region", { name: /Laboratório da equipe/i }),
    ).not.toBeNull();
    expect(
      screen.getByRole("region", { name: /Análise de/i }),
    ).not.toBeNull();
    expect(
      screen.getByRole("region", { name: "Placar completo da partida" }),
    ).not.toBeNull();
    expect(
      screen.getByRole("region", { name: "Comparativos de combate" }),
    ).not.toBeNull();
  });

  it("usa o maior valor real como escala comparativa", async () => {
    renderMatch("?demo=1");

    const maximum = await screen.findByTestId("damage-Aliado#BR1");
    expect(maximum.getAttribute("style")).toContain("--rail-value: 100%");
  });

  it("remove os trilhos quando nenhuma telemetria existe", async () => {
    renderMatch();

    await screen.findByText("Comparativos indisponíveis para esta partida");
    expect(
      screen.queryByRole("region", { name: "Comparativos de combate" }),
    ).toBeNull();
    expect(document.querySelector("[data-comparison-rail]")).toBeNull();
  });

  it("resume somente a integridade pública", async () => {
    renderMatch();

    const integrity = await screen.findByRole("region", {
      name: "Integridade pública da partida",
    });
    expect(
      within(integrity).getByText(/Sem violações detectadas/i),
    ).not.toBeNull();
    expect(
      within(integrity).queryByText(/worker|idempotência|processamento/i),
    ).toBeNull();
  });

  it("expõe somente os sinais públicos de integridade dos jogadores", async () => {
    renderMatch("", flaggedDossier);

    const integrity = await screen.findByRole("region", {
      name: "Integridade pública da partida",
    });
    expect(within(integrity).getByText("Shaco")).not.toBeNull();
    expect(within(integrity).getByText("Partida muito curta")).not.toBeNull();
    expect(
      within(integrity).queryByText(/Sem violações detectadas/i),
    ).toBeNull();
  });

  it("seleciona equipe e jogador pelo botão do placar", async () => {
    renderMatch("?demo=1");

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Selecionar Twitch no placar",
      }),
    );

    expect(
      screen.getByRole("heading", { name: /Shaco · Twitch · Ahri/i }),
    ).not.toBeNull();
    expect(
      screen.getByRole("region", { name: "Análise de Twitch" }),
    ).not.toBeNull();
  });

  it("trata telemetria histórica toda nula como indisponível", async () => {
    renderMatch("", nullTelemetryDossier);

    await screen.findByText("Telemetria não registrada nesta partida");
    const scoreboard = screen.getByRole("region", {
      name: "Placar completo da partida",
    });
    const firstPlayer = within(scoreboard).getAllByTestId("score-player")[0];

    expect(within(firstPlayer).getAllByText("—").length).toBeGreaterThan(0);
    expect(
      screen.queryByRole("region", { name: "Comparativos de combate" }),
    ).toBeNull();
    expect(document.querySelector("[data-comparison-rail]")).toBeNull();
  });

  it("ignora valor nulo sem perder o máximo válido da comparação", async () => {
    renderMatch("?demo=1", partiallyNullDossier);

    const scoreboard = await screen.findByRole("region", {
      name: "Placar completo da partida",
    });
    const firstTeamTotal = scoreboard.querySelector(
      "[data-score-team] .partida-score-team-total",
    );
    const maximum = screen.getByTestId("damage-Aliado#BR1");

    expect(firstTeamTotal?.children.item(6)?.textContent).toBe("—");
    expect(screen.queryByTestId("damage-Kayle#BR1")).toBeNull();
    expect(maximum.getAttribute("style")).toContain("--rail-value: 100%");
  });

  it("mostra dano e ouro parciais sem fabricar K/D/A ou esconder telemetria", async () => {
    renderMatch("?demo=1", partialCombatDossier);

    const analysis = await screen.findByRole("region", {
      name: "Análise de Aurora",
    });
    expect(within(analysis).getByText("K/D/A —/4/—")).not.toBeNull();
    expect(within(analysis).getByText("AMA —")).not.toBeNull();
    expect(within(analysis).getByText("Dano 12,3 mil")).not.toBeNull();
    expect(within(analysis).getByText("Ouro 6,8 mil")).not.toBeNull();
    expect(
      within(analysis).queryByText("Telemetria não registrada nesta partida"),
    ).toBeNull();

    const firstScoreRow = screen.getAllByTestId("score-player")[0];
    expect(firstScoreRow.children.item(3)?.textContent).toBe("—");
  });

  it("mantém a divulgação demonstrativa explícita e ausente no modo real", async () => {
    renderMatch("?demo=1");

    const disclosure = await screen.findByRole("status", {
      name: "Aviso de dados demonstrativos",
    });
    expect(disclosure.getAttribute("data-demo-disclosure")).toBe("");
    expect(disclosure.textContent).toContain("Dados demonstrativos");

    cleanup();
    renderMatch();
    await screen.findByRole("heading", { name: /Aurora · Kayle · Poppy/i });
    expect(screen.queryByText("Dados demonstrativos")).toBeNull();
  });

  it("separa CR agregado, resultado e totais completos da equipe no núcleo orbital", async () => {
    renderMatch("?demo=1");

    const summary = await screen.findByTestId("orbital-summary");
    expect(within(summary).getByText("CR agregado 6.060")).not.toBeNull();
    expect(
      within(summary).getByText(
        (_, element) =>
          element?.tagName === "P" &&
          element.textContent === "Resultado da equipe +60 PDL",
      ),
    ).not.toBeNull();
    expect(within(summary).getByText("K/D/A 35/14/47")).not.toBeNull();
    expect(within(summary).getByText("Dano da equipe 182,4 mil")).not.toBeNull();
    expect(within(summary).getByText("Ouro da equipe 38,7 mil")).not.toBeNull();
  });

  it("omite somente o total de equipe que estiver incompleto", async () => {
    renderMatch("?demo=1", partiallyNullDossier);

    const summary = await screen.findByTestId("orbital-summary");
    expect(within(summary).queryByText(/Dano da equipe/)).toBeNull();
    expect(within(summary).getByText("K/D/A 35/14/47")).not.toBeNull();
    expect(within(summary).getByText("Ouro da equipe 38,7 mil")).not.toBeNull();
  });

  it("expõe data absoluta localizada ao lado do tempo relativo", async () => {
    renderMatch();

    await screen.findByRole("heading", { name: /Aurora · Kayle · Poppy/i });
    const time = document.querySelector(`time[datetime="${detail.playedAt}"]`);
    expect(time).not.toBeNull();
    expect(time?.textContent).toContain("27 de julho de 2026");
  });
});
