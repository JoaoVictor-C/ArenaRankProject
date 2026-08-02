import { describe, expect, it } from "vitest";

import type { MatchDetail } from "../lib/types";
import type { ProfileMatchFixture } from "./profileMatchDetail";
import {
  comparisonMaximum,
  createPartidaDossier,
  hasCombatTelemetry,
  isPartidaDemoEnabled,
  playerKda,
  teamMetricTotal,
} from "./partidaDossierModel";

const detail: MatchDetail = {
  matchId: "BR1-match-dossier",
  format: "3v3",
  queueLabel: "Arena 3v3",
  playedAt: "2026-07-27T01:00:00Z",
  durationSec: 1500,
  patch: "26.14",
  processedAt: "2026-07-27T02:00:00Z",
  subteams: [
    {
      placement: 1,
      players: [
        {
          riotId: "Aliado#BR1",
          name: "Aliado",
          handle: "#BR1",
          avatar: { c1: "#111", c2: "#222" },
          champion: { c1: "#333", c2: "#444" },
          championName: "Fiora",
          crBefore: 2000,
          crAfter: 2030,
          crDelta: 30,
          modifiers: [],
        },
      ],
    },
    {
      placement: 2,
      players: [
        {
          riotId: "Adversário#BR1",
          name: "Adversário",
          handle: "#BR1",
          avatar: { c1: "#555", c2: "#666" },
          champion: { c1: "#777", c2: "#888" },
          championName: "Sett",
          crBefore: 1980,
          crAfter: 1972,
          crDelta: -8,
          modifiers: [],
        },
      ],
    },
  ],
};

const fixture: ProfileMatchFixture = {
  label: "Fixture de teste",
  loadouts: [
    {
      items: Array.from({ length: 7 }, (_, index) => ({
        id: index + 1,
        name: `Item ${index + 1}`,
        iconUrl: `/item-${index + 1}.png`,
      })),
      augments: Array.from({ length: 6 }, (_, index) => ({
        id: index + 101,
        name: `Augment ${index + 1}`,
        iconUrl: `/augment-${index + 1}.png`,
        rarity: index === 0 ? "prismatic" : "gold",
      })),
    },
  ],
  players: [
    {
      level: 18,
      rankLabel: "Gladiador · 2.030 PDL",
      kills: 18,
      deaths: 6,
      assists: 16,
      killParticipation: 74,
      damageToChampions: 76940,
      damagePerMinute: 3098,
      goldEarned: 18240,
      loadout: 0,
    },
  ],
};

describe("partidaDossierModel", () => {
  it("só habilita a demonstração local explicitamente", () => {
    expect(isPartidaDemoEnabled("?demo=1", true)).toBe(true);
    expect(isPartidaDemoEnabled("?demo=0", true)).toBe(false);
    expect(isPartidaDemoEnabled("?demo=1", false)).toBe(false);
  });

  it("preserva campos ausentes na rota real", () => {
    const dossier = createPartidaDossier(detail);

    expect(dossier.demo).toBe(false);
    expect(dossier.telemetryAvailable).toBe(false);
    expect(dossier.teams[0].players[0].kills).toBeUndefined();
    expect(dossier.teams[0].players[0].items).toBeUndefined();
  });

  it("adiciona apenas telemetria e loadout no modo demonstrativo", () => {
    const dossier = createPartidaDossier(detail, fixture);
    const player = dossier.teams[0].players[0];

    expect(dossier.demo).toBe(true);
    expect(player.riotId).toBe("Aliado#BR1");
    expect(player.championName).toBe("Fiora");
    expect(player.kills).toBe(18);
    expect(player.items).toHaveLength(7);
    expect(player.augments).toHaveLength(6);
  });

  it("calcula totais e escalas sem converter ausência em zero", () => {
    const real = createPartidaDossier(detail);
    const demo = createPartidaDossier(detail, fixture);

    expect(teamMetricTotal(real.teams[0], "damageToChampions")).toBeNull();
    expect(comparisonMaximum(real.teams, "damageToChampions")).toBeNull();
    expect(teamMetricTotal(demo.teams[0], "damageToChampions")).toBe(76940);
    expect(playerKda(demo.teams[0].players[0])).toBeCloseTo(34 / 6);
  });

  it("trata métricas históricas nulas como ausência", () => {
    const demo = createPartidaDossier(detail, fixture);
    const validPlayer = demo.teams[0].players[0];
    const historicalNull = null;
    const nullablePlayer = {
      ...validPlayer,
      riotId: "Histórico#BR1",
      level: historicalNull,
      kills: historicalNull,
      deaths: historicalNull,
      assists: historicalNull,
      killParticipation: historicalNull,
      damageToChampions: historicalNull,
      damagePerMinute: historicalNull,
      goldEarned: historicalNull,
    };
    const mixedTeam = {
      ...demo.teams[0],
      players: [validPlayer, nullablePlayer],
    };
    const nullOnlyTeam = {
      ...demo.teams[0],
      players: [nullablePlayer],
    };

    expect(hasCombatTelemetry(nullablePlayer)).toBe(false);
    expect(playerKda(nullablePlayer)).toBeNull();
    expect(teamMetricTotal(mixedTeam, "damageToChampions")).toBeNull();
    expect(comparisonMaximum([mixedTeam], "damageToChampions")).toBe(76940);
    expect(comparisonMaximum([nullOnlyTeam], "damageToChampions")).toBeNull();
  });

  it("reconhece telemetria parcial sem fabricar AMA para K/D/A incompleto", () => {
    const demo = createPartidaDossier(detail, fixture);
    const partialPlayer = {
      ...demo.teams[0].players[0],
      kills: null,
      deaths: 4,
      assists: null,
      damageToChampions: 32100,
      goldEarned: 9800,
    };

    expect(hasCombatTelemetry(partialPlayer)).toBe(true);
    expect(playerKda(partialPlayer)).toBeNull();
  });
});
