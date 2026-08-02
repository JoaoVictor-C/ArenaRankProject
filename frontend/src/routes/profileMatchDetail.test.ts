import { describe, expect, it } from "vitest";

import type { MatchDetail } from "../lib/types";
import {
  adaptProfileMatchDetail,
  enrichProfileMatchDetail,
  type ProfileMatchFixture,
} from "./profileMatchDetail";

const detail: MatchDetail = {
  matchId: "BR1-match-lab",
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
          riotId: "Perfil#BR1",
          name: "Perfil",
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

describe("profileMatchDetail", () => {
  it("preserva a verdade da API quando não há mock", () => {
    const adapted = adaptProfileMatchDetail(detail);

    expect(adapted.mockedFields).toEqual([]);
    expect(adapted.subteams[1].players[0].riotId).toBe("Adversário#BR1");
    expect(adapted.subteams[0].players[0].augments).toBeUndefined();
  });

  it("adiciona somente loadout e combate sem alterar identidades reais", () => {
    const enriched = enrichProfileMatchDetail(
      detail,
      fixture,
      "Perfil#BR1",
    );
    const profile = enriched.subteams[0].players[0];
    const opponent = enriched.subteams[1].players[0];

    expect(enriched.mockedFields).toEqual(["items", "augments", "combat"]);
    expect(profile.riotId).toBe("Perfil#BR1");
    expect(opponent.riotId).toBe("Adversário#BR1");
    expect(profile.items).toHaveLength(7);
    expect(profile.augments).toHaveLength(6);
    expect(profile).toMatchObject({
      kills: 18,
      deaths: 6,
      assists: 16,
      damageToChampions: 76940,
      damagePerMinute: 3098,
    });
  });
});
