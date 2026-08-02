import { describe, expect, it } from "vitest";

import {
  createLensMock,
  radarPath,
  scoreTone,
  type LensAxisKey,
} from "./lensModel";

describe("lensModel", () => {
  it("adapta a identidade da rota sem alterar o contrato demonstrativo", () => {
    const lens = createLensMock("Clesio#BR1", 50);

    expect(lens.riotId).toBe("Clesio#BR1");
    expect(lens.player.name).toBe("Clesio");
    expect(lens.player.handle).toBe("#BR1");
    expect(lens.window.games).toBe(50);
    expect(lens.mocked).toBe(true);
  });

  it("entrega os cinco eixos na ordem visual e preserva ausências explícitas", () => {
    const lens = createLensMock("ArenaLab#MOCK", 50);

    expect(lens.axes.map((axis) => axis.key)).toEqual<LensAxisKey[]>([
      "adapt",
      "eco",
      "surv",
      "meta",
      "impact",
    ]);
    expect(lens.axes.flatMap((axis) => axis.metrics).some((metric) => !metric.available)).toBe(true);
    expect(
      lens.axes
        .flatMap((axis) => axis.metrics)
        .find((metric) => metric.key === "earlyRoundsForm"),
    ).toMatchObject({
      available: false,
      phase: "T2",
      reason: "requires_round_timeline",
    });
  });

  it("gera uma trajetória SVG fechada e estável", () => {
    const path = radarPath([74, 58, 63, 81, 77], 100, 100, 72);

    expect(path.startsWith("M ")).toBe(true);
    expect(path.endsWith(" Z")).toBe(true);
    expect(path.match(/ L /g)).toHaveLength(4);
  });

  it("mapeia notas para os tons semânticos do design system", () => {
    expect(scoreTone(28)).toBe("low");
    expect(scoreTone(50)).toBe("neutral");
    expect(scoreTone(72)).toBe("high");
    expect(scoreTone(91)).toBe("elite");
  });
});
