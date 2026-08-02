import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import type { AugmentCatalogResponse } from "./augmentCatalog";
import { Augments } from "./Augments";

function renderAugments() {
  return render(
    <MemoryRouter>
      <Augments />
    </MemoryRouter>,
  );
}

const data: AugmentCatalogResponse = {
  updatedAt: "2026-07-25T00:00:00Z",
  patch: "16.14",
  mockedFields: ["tier", "champions"],
  augments: [
    {
      id: 1,
      name: "Ataque Duplo",
      iconUrl: null,
      tier: "S",
      rarity: "prismatic",
      description: "Seus ataques acertam uma segunda vez.",
      champions: [{ championId: 11, name: "Mestre Yi" }],
    },
    {
      id: 2,
      name: "Golaço",
      iconUrl: null,
      tier: "A",
      rarity: "gold",
      description: "Concede uma habilidade de controle adicional.",
      champions: [],
    },
    {
      id: 3,
      name: "Pensamentos Mágicos",
      iconUrl: null,
      tier: "B",
      rarity: "silver",
      description: "Concede Poder de Habilidade.",
      champions: [],
    },
    {
      id: 4,
      name: "Escolha Única",
      iconUrl: null,
      tier: "C",
      rarity: "unique",
      description: "Muda uma regra da partida.",
      champions: [],
    },
  ],
};

const mockApi = vi.hoisted(() => ({
  data: null as AugmentCatalogResponse | null,
}));

vi.mock("../hooks/useApi", () => ({
  useApi: () => ({
    data: mockApi.data,
    loading: false,
    error: null,
    retry: () => {},
    refreshing: false,
    updatedAt: mockApi.data ? Date.parse(mockApi.data.updatedAt) : 0,
  }),
}));

vi.mock("../lib/motion", () => ({
  STATE_SPINNER_LOOP: {},
  loadMotion: async () => null,
  useReveal: () => {},
  useFlipList: () => ({ capture: () => {} }),
  useGsapEntrance: () => {},
  useGsapInteractions: () => {},
  useGsapLoop: () => {},
}));

afterEach(cleanup);
beforeEach(() => {
  mockApi.data = data;
});

describe("Augments", () => {
  it("organiza o catálogo por raridade e combina filtro com busca", () => {
    const { container } = renderAugments();

    expect(screen.queryByRole("region", { name: "Tier S" })).toBeNull();
    expect(
      screen.getByRole("region", { name: "Augments prismáticos" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("region", { name: "Augments de ouro" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("region", { name: "Augments de prata" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("region", { name: "Augments únicos" }),
    ).toBeTruthy();
    expect(
      container.querySelector("[data-gsap-scope]"),
    ).not.toBeNull();
    expect(
      screen.getByRole("region", {
        name: "Galeria horizontal de augments",
      }),
    ).toBeTruthy();
    expect(container.querySelector(".augment-gallery-track")).toBeNull();
    const raritySections = Array.from(
      container.querySelectorAll(".augment-rarity-section"),
    );
    expect(raritySections).toHaveLength(4);
    expect(
      raritySections.every(
        (section) =>
          section.querySelectorAll("[data-augment-gallery-row]").length ===
          1,
      ),
    ).toBe(true);
    expect(
      container.querySelectorAll("[data-augment-scroll]").length,
    ).toBe(8);
    const dockItems = Array.from(
      container.querySelectorAll("[data-augment-dock-item]"),
    );
    expect(dockItems).toHaveLength(3);
    expect(
      dockItems.every((item) => !item.classList.contains("augment-card")),
    ).toBe(true);
    expect(screen.queryByText(/winrate/i)).toBeNull();
    expect(screen.queryByText(/jogos/i)).toBeNull();
    expect(
      screen.getByText(
        /tier e recomendações de campeões são demonstrativos/i,
      ),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Ouro" }));
    expect(screen.getByText("Golaço")).toBeTruthy();
    expect(screen.queryByText("Ataque Duplo")).toBeNull();
    expect(screen.getByText("1 augment encontrado")).toBeTruthy();

    fireEvent.change(
      screen.getByRole("textbox", { name: "Buscar augment no catálogo" }),
      { target: { value: "ataque" } },
    );

    expect(
      screen.getByText("Nenhum augment combina com os filtros atuais."),
    ).toBeTruthy();
  });

  it("declara descrição e raridade ausentes sem inventar recomendações", () => {
    mockApi.data = {
      ...data,
      augments: [
        {
          ...data.augments[0],
          rarity: "unknown",
          description: null,
          tier: null,
          champions: [],
        },
      ],
    };

    const { container } = renderAugments();

    expect(screen.getByText("Descrição em breve")).toBeTruthy();
    expect(screen.getByText("Raridade não informada")).toBeTruthy();
    expect(
      container.querySelectorAll("[data-augment-dock-item]"),
    ).toHaveLength(0);
    expect(screen.getByText("Tier em breve")).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "Único" }) as HTMLButtonElement)
      .disabled,
    ).toBe(true);
  });

  it("aceita o payload persistido anterior enquanto o catálogo revalida", () => {
    const legacyData = { ...data } as Partial<AugmentCatalogResponse>;
    delete legacyData.mockedFields;
    mockApi.data = legacyData as AugmentCatalogResponse;

    renderAugments();

    expect(screen.getByText("Ataque Duplo")).toBeTruthy();
    expect(
      screen.getByText(/tier e recomendações aparecem quando/i),
    ).toBeTruthy();
  });
});
