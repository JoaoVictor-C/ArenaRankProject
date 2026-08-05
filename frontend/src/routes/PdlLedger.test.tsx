import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { PdlExplanation } from "../lib/types";
import { PdlLedger } from "./PdlLedger";

afterEach(cleanup);

function explanation(overrides: Partial<PdlExplanation> = {}): PdlExplanation {
  return {
    fidelity: "exato",
    crBefore: 2000,
    crAfter: 2015,
    totalPdl: 15,
    totalPdlExact: 15,
    placement: 1,
    teamCount: 6,
    entries: [
      {
        kind: "base",
        label: "Resultado do confronto",
        icon: "swords",
        pdl: 15,
        pdlExact: 15,
        runningTotal: 15,
        exact: true,
      },
    ],
    cap: {
      active: false,
      rule: "nenhum",
      factors: {},
      placementCurve: [],
    },
    reconciles: true,
    residualPdl: 0,
    unrecoverable: [],
    summary: "Resultado do confronto +15",
    lobby: [],
    ...overrides,
  };
}

describe("PdlLedger", () => {
  it("omite a seção de fatores quando nenhum fator do teto está presente", () => {
    render(<PdlLedger explanation={explanation()} />);
    expect(screen.queryByText("Por que o seu teto de ganho é este")).toBeNull();
  });

  it("mostra os fatores do teto com o sinal correto", () => {
    const exp = explanation({
      cap: {
        active: true,
        rule: "teto_ganho",
        factors: {
          mismatchBonusPct: 12.5,
          highCrReductionPct: -20,
          compositePct: -10,
        },
        placementCurve: [],
      },
    });
    render(<PdlLedger explanation={exp} />);
    expect(screen.getByText("Por que o seu teto de ganho é este")).not.toBeNull();
    expect(screen.getByText("+12.5%")).not.toBeNull();
    expect(screen.getByText("−20%")).not.toBeNull();
    expect(screen.getByText("−10%")).not.toBeNull();
  });

  it("ignora fatores essencialmente nulos (ruído de ponto flutuante)", () => {
    const exp = explanation({
      cap: {
        active: true,
        rule: "nenhum",
        factors: { mismatchBonusPct: 0.001, highCrReductionPct: 0, compositePct: null },
        placementCurve: [],
      },
    });
    render(<PdlLedger explanation={exp} />);
    expect(screen.queryByText("Por que o seu teto de ganho é este")).toBeNull();
  });

  it("renderiza a curva de colocação e destaca a colocação do jogador", () => {
    const exp = explanation({
      placement: 4,
      teamCount: 6,
      cap: {
        active: true,
        rule: "nenhum",
        factors: {},
        placementCurve: [
          { placement: 1, gainCap: 40, lossCap: -30, minGain: 15 },
          { placement: 4, gainCap: 26, lossCap: -30, minGain: 0 },
        ],
      },
    });
    render(<PdlLedger explanation={exp} />);
    expect(screen.getByText("Curva de colocação (6 equipes)")).not.toBeNull();
    const yourRow = screen.getByText("4º").closest(".pdl-ledger-curve-row");
    expect(yourRow?.className).toContain("is-you");
    const otherRow = screen.getByText("1º").closest(".pdl-ledger-curve-row");
    expect(otherRow?.className).not.toContain("is-you");
    expect(screen.getByText("piso +15")).not.toBeNull();
  });

  it("omite a curva quando vazia", () => {
    render(<PdlLedger explanation={explanation()} />);
    expect(screen.queryByText(/Curva de colocação/)).toBeNull();
  });

  it("renderiza o resultado de todas as equipes, com 'Você' no lugar do seu nome", () => {
    const exp = explanation({
      placement: 1,
      lobby: [
        { riotId: "You#BR1", name: "You", placement: 1, crDelta: 15, isYou: true },
        { riotId: "Rival#BR1", name: "Rival", placement: 4, crDelta: -30, isYou: false },
      ],
    });
    render(<PdlLedger explanation={exp} />);
    expect(screen.getByText("Resultado de todas as equipes")).not.toBeNull();
    expect(screen.getByText("Você")).not.toBeNull();
    expect(screen.getByText("Rival")).not.toBeNull();
    expect(screen.queryByText("You")).toBeNull();
  });

  it("omite o comparativo de equipes quando há 0 ou 1 participante", () => {
    render(<PdlLedger explanation={explanation({ lobby: [] })} />);
    expect(screen.queryByText("Resultado de todas as equipes")).toBeNull();

    const single = explanation({
      lobby: [{ riotId: "You#BR1", name: "You", placement: 1, crDelta: 15, isYou: true }],
    });
    render(<PdlLedger explanation={single} />);
    expect(screen.queryByText("Resultado de todas as equipes")).toBeNull();
  });

  it("ainda soma exatamente ao total exibido com todas as seções presentes", () => {
    const exp = explanation({
      placement: 1,
      totalPdl: 15,
      cap: {
        active: true,
        rule: "piso_ganho",
        factors: { mismatchBonusPct: 25, highCrReductionPct: -40, compositePct: -25 },
        placementCurve: [{ placement: 1, gainCap: 40, lossCap: -30, minGain: 15 }],
      },
      lobby: [
        { riotId: "You#BR1", name: "You", placement: 1, crDelta: 15, isYou: true },
        { riotId: "Rival#BR1", name: "Rival", placement: 4, crDelta: -30, isYou: false },
      ],
    });
    render(<PdlLedger explanation={exp} />);
    expect(screen.getByText("+15 PDL")).not.toBeNull();
  });
});
