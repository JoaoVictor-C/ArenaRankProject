export type CatalogRarity =
  | "unique"
  | "prismatic"
  | "gold"
  | "silver"
  | "unknown";

export type CatalogTier = "S+" | "S" | "A" | "B" | "C" | "D" | null;
export type MockedCatalogField = "tier" | "champions";

export interface CatalogChampion {
  championId: number;
  name: string;
}

export interface RiotAugmentCatalogEntry {
  id: number;
  name: string;
  iconUrl: string | null;
  rarity: Exclude<CatalogRarity, "unknown">;
  description: string;
  /** Derivados do rollup `champion_augment_stats`. Opcionais porque uma célula
   *  campeão×augment sem amostra suficiente não vira número inventado — o
   *  backend omite, e a tela mostra "em breve" em vez de mentir. */
  tier?: CatalogTier;
  champions?: CatalogChampion[];
}

export interface RiotAugmentCatalogResponse {
  updatedAt: string;
  patch: string;
  augments: RiotAugmentCatalogEntry[];
}

export interface AugmentCatalogEntry
  extends Omit<RiotAugmentCatalogEntry, "rarity" | "description"> {
  rarity: CatalogRarity;
  description: string | null;
  tier: CatalogTier;
  champions: CatalogChampion[];
}

export interface AugmentCatalogResponse
  extends Omit<RiotAugmentCatalogResponse, "augments"> {
  mockedFields: MockedCatalogField[];
  augments: AugmentCatalogEntry[];
}

const API_BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");
const CATALOG_PATH = "/api/v1/champions/augments/catalog";

export function normalizeCatalog(
  response: RiotAugmentCatalogResponse,
): AugmentCatalogResponse {
  // Passa adiante o que o backend servir. Antes isto zerava `tier` e
  // `champions` à força, porque a API não tinha de onde tirá-los; agora eles
  // vêm do rollup de augment por campeão. Ausente continua virando null/vazio —
  // é assim que a tela sabe mostrar "Tier em breve" em vez de um tier inventado.
  return {
    ...response,
    mockedFields: [],
    augments: response.augments.map((augment) => ({
      ...augment,
      description: augment.description || null,
      tier: augment.tier ?? null,
      champions: augment.champions ?? [],
    })),
  };
}

export async function fetchAugmentCatalog(): Promise<AugmentCatalogResponse> {
  if (import.meta.env.DEV) {
    const { isDevMockOn } = await import("../lib/devMock");
    if (isDevMockOn()) {
      const response = await fetch("/fixtures/augments-catalog.json");
      if (!response.ok) {
        throw new Error("Falha ao carregar o catálogo mockado.");
      }
      return response.json() as Promise<AugmentCatalogResponse>;
    }
  }

  const response = await fetch(`${API_BASE}${CATALOG_PATH}`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error("Falha ao carregar o catálogo de augments da Riot.");
  }
  return normalizeCatalog(
    (await response.json()) as RiotAugmentCatalogResponse,
  );
}
