import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Modifier } from "../lib/types";
import {
  getRatingSignalMotionPlan,
  getRatingSignalSlots,
  getRatingSignalTrack,
  RATING_SIGNAL_POSES,
  wrapRatingSignalIndex,
} from "./profileRatingCarousel";
import {
  buildProfileRatingSignal,
  resolveProfileRatingModifiers,
} from "./profileRatingSignalModel";
import { ProfileRatingSignals } from "./profileRatingSignals";

const placementModifier = {
  kind: "colocacao",
  label: "Colocação",
  value: 25,
  pdlImpact: 7,
  icon: "leaderboard",
} as Modifier;

const streakModifier = {
  kind: "sequencia",
  label: "Amortecedor de derrotas",
  value: -50,
  pdlImpact: 6,
  icon: "shield_moon",
} as Modifier;

const groupModifier = {
  kind: "grupo",
  label: "Penalidade de grupo",
  value: -15,
  pdlImpact: -4,
  icon: "group",
} as Modifier;

const protectionModifier = {
  kind: "protecao",
  label: "Proteção de topo",
  value: -20,
  pdlImpact: -8,
  icon: "vertical_align_top",
} as Modifier;

beforeEach(() => {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("modelo circular dos fatores", () => {
  it("normaliza índices nos dois sentidos", () => {
    expect(wrapRatingSignalIndex(-1, 4)).toBe(3);
    expect(wrapRatingSignalIndex(4, 4)).toBe(0);
  });

  it("posiciona anterior, ativo e próximo ao redor do índice central", () => {
    expect(getRatingSignalSlots(0, 4)).toEqual([
      { position: "previous", cardIndex: 3 },
      { position: "active", cardIndex: 0 },
      { position: "next", cardIndex: 1 },
    ]);
  });

  it("gira X · Y · Z para Y · Z · X ao avançar", () => {
    expect(getRatingSignalSlots(1, 3)).toEqual([
      { position: "previous", cardIndex: 0 },
      { position: "active", cardIndex: 1 },
      { position: "next", cardIndex: 2 },
    ]);
    expect(getRatingSignalSlots(2, 3)).toEqual([
      { position: "previous", cardIndex: 1 },
      { position: "active", cardIndex: 2 },
      { position: "next", cardIndex: 0 },
    ]);
  });

  it("mantém um card já renderizado e oculto em cada lado", () => {
    expect(getRatingSignalTrack(1, 3)).toEqual([
      { position: "farPrevious", cardIndex: 2, virtualIndex: -1 },
      { position: "previous", cardIndex: 0, virtualIndex: 0 },
      { position: "active", cardIndex: 1, virtualIndex: 1 },
      { position: "next", cardIndex: 2, virtualIndex: 2 },
      { position: "farNext", cardIndex: 0, virtualIndex: 3 },
    ]);
  });

  it("move o buffer já renderizado para dentro antes de trocar o trilho", () => {
    expect(getRatingSignalMotionPlan(1)).toEqual({
      exiting: { position: "farPrevious", pose: "exitPrevious" },
      movers: [
        { position: "previous", pose: "farPrevious" },
        { position: "active", pose: "previous" },
        { position: "next", pose: "active" },
        { position: "farNext", pose: "next" },
      ],
    });
    expect(getRatingSignalMotionPlan(-1)).toEqual({
      exiting: { position: "farNext", pose: "exitNext" },
      movers: [
        { position: "next", pose: "farNext" },
        { position: "active", pose: "next" },
        { position: "previous", pose: "active" },
        { position: "farPrevious", pose: "previous" },
      ],
    });
  });

  it("mantém a posição em propriedades próprias sem acumular xPercent", () => {
    expect(RATING_SIGNAL_POSES.previous).toMatchObject({
      "--signal-x": "-116%",
      "--signal-scale": 0.78,
      "--signal-rotation": "-4deg",
    });
    expect(RATING_SIGNAL_POSES.active).toMatchObject({
      "--signal-x": "-50%",
      "--signal-scale": 1,
      "--signal-rotation": "0deg",
    });
    expect(RATING_SIGNAL_POSES.previous).not.toHaveProperty("xPercent");
  });

  it("repete o outro fator nas duas laterais quando existem dois", () => {
    expect(getRatingSignalSlots(0, 2)).toEqual([
      { position: "previous", cardIndex: 1 },
      { position: "active", cardIndex: 0 },
      { position: "next", cardIndex: 1 },
    ]);
  });

  it("mantém somente o centro quando existe um fator", () => {
    expect(getRatingSignalSlots(0, 1)).toEqual([
      { position: "active", cardIndex: 0 },
    ]);
  });
});

describe("buildProfileRatingSignal", () => {
  it("usa o impacto real em PDL para explicar uma colocação positiva", () => {
    expect(
      buildProfileRatingSignal(placementModifier, {
        placement: 1,
        premade: false,
        crDelta: 30,
      }),
    ).toMatchObject({
      title: "Colocação",
      formattedImpact: "+7 PDL",
      description: "Você ganhou 7 PDL por terminar em 1º.",
    });
  });

  it("informa diretamente o PDL perdido pela colocação", () => {
    expect(
      buildProfileRatingSignal(
        { ...placementModifier, pdlImpact: -12 },
        {
          placement: 6,
          premade: false,
          crDelta: -12,
        },
      ),
    ).toMatchObject({
      title: "Colocação",
      formattedImpact: "−12 PDL",
      description: "Você perdeu 12 PDL por terminar em 6º.",
    });
  });

  it("explica o amortecedor como PDL que o jogador deixou de perder", () => {
    expect(
      buildProfileRatingSignal(streakModifier, {
        placement: 6,
        premade: false,
        crDelta: -14,
      }),
    ).toMatchObject({
      title: "Sequência de derrotas",
      formattedImpact: "+6 PDL",
      description:
        "Você deixou de perder 6 PDL graças ao amortecedor da sua sequência de derrotas.",
    });
  });

  it("explica a proteção recebida contra uma partida de habilidade superior", () => {
    expect(
      buildProfileRatingSignal(
        { ...protectionModifier, pdlImpact: 20 },
        {
          placement: 6,
          premade: false,
          crDelta: -10,
        },
      ),
    ).toMatchObject({
      title: "Proteção do topo",
      formattedImpact: "+20 PDL",
      description:
        "Você deixou de perder 20 PDL por cair em uma partida com nível de habilidade superior ao esperado para seu elo atual.",
    });
  });

  it("explica a perda agravada por uma partida de habilidade inferior", () => {
    expect(
      buildProfileRatingSignal(
        { ...protectionModifier, pdlImpact: -30 },
        {
          placement: 6,
          premade: false,
          crDelta: -42,
        },
      ),
    ).toMatchObject({
      title: "Proteção do topo",
      formattedImpact: "−30 PDL",
      description:
        "Você perdeu 30 PDL a mais por perder em uma partida com nível de habilidade inferior ao esperado para seu elo atual.",
    });
  });

  it("suprime proteções positivas que arredondam para zero PDL", () => {
    expect(
      buildProfileRatingSignal(
        { ...protectionModifier, pdlImpact: 0.49 },
        {
          placement: 6,
          premade: false,
          crDelta: -10,
        },
      ),
    ).toBeNull();
  });

  it("suprime ajustes negativos de grupo que arredondam para zero PDL", () => {
    expect(
      buildProfileRatingSignal(
        { ...groupModifier, pdlImpact: -0.49 },
        {
          placement: 1,
          premade: true,
          crDelta: 10,
        },
      ),
    ).toBeNull();
  });

  it("usa o mesmo impacto inteiro no formato e na explicação", () => {
    expect(
      buildProfileRatingSignal(
        { ...protectionModifier, pdlImpact: -0.6 },
        {
          placement: 1,
          premade: false,
          crDelta: 10,
        },
      ),
    ).toMatchObject({
      impact: -1,
      formattedImpact: "−1 PDL",
      description:
        "Você deixou de ganhar 1 PDL por vencer uma partida com nível de habilidade inferior ao esperado para seu elo atual.",
    });
  });

  it("retorna os modificadores inalterados quando todos têm pdlImpact (Raio-X v1.4)", () => {
    const modifiers = [placementModifier, streakModifier, groupModifier];
    expect(resolveProfileRatingModifiers(modifiers)).toEqual(modifiers);
  });

  it("descarta — sem tentar adivinhar — um modificador sem pdlImpact finito", () => {
    // O backend (arena/rating/explain.py, via map_modifiers) sempre envia um
    // pdlImpact real hoje; este é só o filtro defensivo para o caso (não
    // deveria acontecer) de um fator chegar sem ele — nunca mais reconstruído
    // via inversão da cadeia multiplicativa (ver o histórico desta função).
    const semImpacto = { ...placementModifier, pdlImpact: undefined };
    expect(resolveProfileRatingModifiers([semImpacto, streakModifier])).toEqual([
      streakModifier,
    ]);
  });

  it("retorna lista vazia quando nenhum modificador tem pdlImpact", () => {
    const semImpacto = { ...placementModifier, pdlImpact: undefined };
    expect(resolveProfileRatingModifiers([semImpacto])).toEqual([]);
  });
});

describe("ProfileRatingSignals", () => {
  function getActiveSlot(): HTMLElement {
    return screen
      .getByRole("region", { name: "Fatores do PDL" })
      .querySelector('[data-slot="active"]') as HTMLElement;
  }

  it("mantém o fator ativo no centro e esconde as laterais da árvore acessível", () => {
    render(
      <ProfileRatingSignals
        modifiers={[placementModifier, streakModifier, groupModifier]}
        placement={1}
        premade
        crDelta={30}
        matchId="m1"
        riotId="Jogador#BR1"
      />,
    );

    const region = screen.getByRole("region", { name: "Fatores do PDL" });
    expect(region.querySelectorAll(".rating-signal-card")).toHaveLength(5);
    expect(screen.queryByText("Proteção do topo")).toBeNull();
    expect(getActiveSlot().textContent).toContain("Colocação");
    expect(getActiveSlot().getAttribute("aria-hidden")).toBeNull();
    expect(
      region.querySelector('[data-slot="previous"]')?.getAttribute("aria-hidden"),
    ).toBe("true");
    expect(
      region.querySelector('[data-slot="next"]')?.getAttribute("aria-hidden"),
    ).toBe("true");
    expect(
      region.querySelector('[data-slot="farPrevious"]')?.getAttribute(
        "aria-hidden",
      ),
    ).toBe("true");
    expect(
      region.querySelector('[data-slot="farNext"]')?.getAttribute("aria-hidden"),
    ).toBe("true");
  });

  it("repete em loop ao navegar para trás e para frente", () => {
    render(
      <ProfileRatingSignals
        modifiers={[
          placementModifier,
          streakModifier,
          protectionModifier,
          groupModifier,
        ]}
        placement={1}
        premade
        crDelta={30}
        matchId="m1"
        riotId="Jogador#BR1"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Fator anterior" }));
    expect(getActiveSlot().textContent).toContain("Penalidade em dupla");
    expect(screen.getByText("4 / 4")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Próximo fator" }));
    expect(getActiveSlot().textContent).toContain("Colocação");
    expect(screen.getByText("1 / 4")).toBeTruthy();
  });

  it("reutiliza o buffer oculto da direita como próximo card visível", () => {
    render(
      <ProfileRatingSignals
        modifiers={[placementModifier, streakModifier, protectionModifier]}
        placement={1}
        premade={false}
        crDelta={30}
        matchId="m1"
        riotId="Jogador#BR1"
      />,
    );

    const region = screen.getByRole("region", { name: "Fatores do PDL" });
    const bufferedNext = region.querySelector('[data-slot="farNext"]');

    fireEvent.click(screen.getByRole("button", { name: "Próximo fator" }));

    expect(region.querySelector('[data-slot="next"]')).toBe(bufferedNext);
  });

  it("usa o mesmo loop com teclado e gesto horizontal", () => {
    render(
      <ProfileRatingSignals
        modifiers={[placementModifier, streakModifier, protectionModifier]}
        placement={1}
        premade={false}
        crDelta={30}
        matchId="m1"
        riotId="Jogador#BR1"
      />,
    );

    const stage = screen
      .getByRole("region", { name: "Fatores do PDL" })
      .querySelector(".rating-signals-stage") as HTMLElement;

    fireEvent.keyDown(stage, { key: "ArrowRight" });
    expect(getActiveSlot().textContent).toContain("Sequência de derrotas");

    const pointerDown = new Event("pointerdown", { bubbles: true });
    Object.defineProperties(pointerDown, {
      clientX: { value: 200 },
      pointerId: { value: 1 },
      isPrimary: { value: true },
    });
    const pointerUp = new Event("pointerup", { bubbles: true });
    Object.defineProperties(pointerUp, {
      clientX: { value: 100 },
      pointerId: { value: 1 },
      isPrimary: { value: true },
    });
    fireEvent(stage, pointerDown);
    fireEvent(stage, pointerUp);
    expect(getActiveSlot().textContent).toContain("Proteção do topo");
  });

  it("repete o outro fator nas duas laterais sem duplicá-lo logicamente", () => {
    render(
      <ProfileRatingSignals
        modifiers={[placementModifier, streakModifier]}
        placement={1}
        premade={false}
        crDelta={30}
        matchId="m1"
        riotId="Jogador#BR1"
      />,
    );

    const region = screen.getByRole("region", { name: "Fatores do PDL" });
    expect(region.querySelector('[data-slot="previous"]')?.textContent).toContain(
      "Sequência de derrotas",
    );
    expect(region.querySelector('[data-slot="next"]')?.textContent).toContain(
      "Sequência de derrotas",
    );
    expect(screen.getByText("1 / 2")).toBeTruthy();
    expect(region.querySelectorAll(".rating-signal-card")).toHaveLength(5);

    fireEvent.click(screen.getByRole("button", { name: "Próximo fator" }));
    expect(region.querySelector('[data-slot="previous"]')?.textContent).toContain(
      "Colocação",
    );
    expect(getActiveSlot().textContent).toContain("Sequência de derrotas");
    expect(region.querySelector('[data-slot="next"]')?.textContent).toContain(
      "Colocação",
    );
    expect(screen.getByText("2 / 2")).toBeTruthy();
  });

  it("não exibe controles quando existe somente um fator", () => {
    render(
      <ProfileRatingSignals
        modifiers={[placementModifier]}
        placement={1}
        premade={false}
        crDelta={30}
        matchId="m1"
        riotId="Jogador#BR1"
      />,
    );

    expect(screen.queryByRole("button", { name: "Próximo fator" })).toBeNull();
    expect(
      screen.getByText("+7 PDL").parentElement?.getAttribute("data-tag"),
    ).toBe("+7 PDL");
    expect(
      screen
        .getByRole("region", { name: "Fatores do PDL" })
        .querySelectorAll(".rating-signal-card"),
    ).toHaveLength(1);
  });

  it("anuncia o fator central depois da navegação", () => {
    render(
      <ProfileRatingSignals
        modifiers={[placementModifier, streakModifier]}
        placement={1}
        premade={false}
        crDelta={30}
        matchId="m1"
        riotId="Jogador#BR1"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Próximo fator" }));

    expect(
      screen
        .getByRole("region", { name: "Fatores do PDL" })
        .querySelector('[aria-live="polite"]')?.textContent,
    ).toContain("Sequência de derrotas: +6 PDL");
  });

  it("não renderiza nada quando o único modificador não tem pdlImpact (Raio-X v1.4)", () => {
    // Antes da v1.4 este caso reconstruía o impacto a partir de `value`; hoje
    // o backend sempre envia pdlImpact real, então um fator sem ele é
    // descartado (resolveProfileRatingModifiers) em vez de ter seu PDL
    // adivinhado — sem fatores restantes, o componente não renderiza nada.
    const { container } = render(
      <ProfileRatingSignals
        modifiers={[
          {
            kind: "colocacao",
            label: "Colocação",
            value: 25,
            icon: "leaderboard",
          },
        ]}
        placement={1}
        premade={false}
        crDelta={30}
        matchId="m1"
        riotId="Jogador#BR1"
      />,
    );

    expect(screen.queryByRole("region", { name: "Fatores do PDL" })).toBeNull();
    expect(container.firstChild).toBeNull();
  });
});
