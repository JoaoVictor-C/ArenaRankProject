import { describe, expect, it } from "vitest";

import {
  deltaClass,
  fmtCountdown,
  fmtPrize,
  nf,
  pct,
  signed,
  splitRiotId,
  tierLabel,
  timeAgo,
  winrateBand,
} from "./format";

const MINUS = "−"; // o "−" real usado por signed() (não o hífen ASCII)

describe("format helpers", () => {
  it("nf agrupa milhares no padrão pt-BR", () => {
    expect(nf(4295)).toBe("4.295");
    expect(nf(200)).toBe("200");
    expect(nf(1234567)).toBe("1.234.567");
  });

  it("signed usa sinal explícito e o minus real", () => {
    expect(signed(200)).toBe("+200");
    expect(signed(-64)).toBe(MINUS + "64");
    expect(signed(-64).startsWith(MINUS)).toBe(true);
    expect(signed(0)).toBe("0");
  });

  it("pct arredonda para inteiro", () => {
    expect(pct(74.6)).toBe("75%");
    expect(pct(0)).toBe("0%");
  });

  it("deltaClass mapeia o sinal", () => {
    expect(deltaClass(5)).toBe("up");
    expect(deltaClass(-5)).toBe("down");
    expect(deltaClass(0)).toBe("flat");
  });

  it("winrateBand respeita os marcos", () => {
    expect(winrateBand(85)).toBe("gold");
    expect(winrateBand(80)).toBe("blue");
    expect(winrateBand(75)).toBe("green");
    expect(winrateBand(74.9)).toBe("low");
  });

  it("tierLabel rotula tiers conhecidos e devolve vazio no resto", () => {
    expect(tierLabel("top1")).toBe("Top 1");
    expect(tierLabel("top500")).toBe("Top 500");
    expect(tierLabel("xyz" as never)).toBe("");
  });

  it("fmtCountdown formata s / min / h", () => {
    expect(fmtCountdown(45)).toBe("45 s");
    expect(fmtCountdown(90)).toBe("1 min 30 s");
    expect(fmtCountdown(120)).toBe("2 min");
    expect(fmtCountdown(3600)).toBe("1 h");
    expect(fmtCountdown(3660)).toBe("1 h 1 min");
  });

  it("fmtPrize escolhe a moeda (BRL vs RP)", () => {
    expect(fmtPrize(126, "BRL")).toBe("R$ 126");
    expect(fmtPrize(126, "RP")).toBe("126 RP");
    expect(fmtPrize(126)).toBe("126 RP");
  });

  it("timeAgo é relativo e determinístico com nowMs fixo", () => {
    const now = Date.parse("2026-06-21T12:00:00Z");
    expect(timeAgo("2026-06-21T11:59:30Z", now)).toBe("há 30 s");
    expect(timeAgo("2026-06-21T11:49:00Z", now)).toBe("há 11 min");
    expect(timeAgo("2026-06-21T10:00:00Z", now)).toBe("há 2 h");
    expect(timeAgo("2026-06-19T12:00:00Z", now)).toBe("há 2 d");
  });

  it("splitRiotId separa no último #", () => {
    expect(splitRiotId("Frederic Boulos#BR1")).toEqual({
      name: "Frederic Boulos",
      handle: "#BR1",
    });
    expect(splitRiotId("SemTag")).toEqual({ name: "SemTag", handle: "" });
    expect(splitRiotId("a#b#c")).toEqual({ name: "a#b", handle: "#c" });
  });
});
