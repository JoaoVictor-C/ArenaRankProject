import { describe, expect, it } from "vitest";

import catalogFixture from "../../public/fixtures/augments-catalog.json";
import {
  normalizeCatalog,
  type RiotAugmentCatalogResponse,
} from "./augmentCatalog";

const source: RiotAugmentCatalogResponse = {
  updatedAt: "2026-07-25T00:00:00Z",
  patch: "16.14",
  augments: [
    {
      id: 41,
      name: "Golias",
      iconUrl: null,
      rarity: "prismatic",
      description: "Aumenta seu tamanho e sua Vida.",
    },
  ],
};

describe("normalizeCatalog", () => {
  it("preserva o catálogo Riot e declara apenas os campos processados ausentes", () => {
    const result = normalizeCatalog(source);

    expect(result.augments[0]).toMatchObject({
      id: 41,
      name: "Golias",
      rarity: "prismatic",
      description: "Aumenta seu tamanho e sua Vida.",
      tier: null,
      champions: [],
    });
    expect(result.mockedFields).toEqual([]);
  });

  it("mantém o fixture de desenvolvimento como catálogo completo, não como amostra", () => {
    const rarities = new Set(
      catalogFixture.augments.map((augment) => augment.rarity),
    );

    expect(catalogFixture.augments.length).toBeGreaterThan(200);
    expect(rarities).toEqual(
      new Set(["prismatic", "gold", "silver", "unique"]),
    );
    expect(catalogFixture.mockedFields).toEqual(["tier", "champions"]);
  });
});
