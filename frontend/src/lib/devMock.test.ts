import { afterEach, describe, expect, it, vi } from "vitest";

import championPageFixture from "../../public/fixtures/champion-page.json";
import type { ChampionTrendResponse } from "./types";
import { devMockResponse } from "./devMock";

const expectedDates = [
  "2026-07-11",
  "2026-07-12",
  "2026-07-13",
  "2026-07-14",
  "2026-07-15",
  "2026-07-16",
  "2026-07-17",
  "2026-07-18",
  "2026-07-19",
  "2026-07-20",
  "2026-07-21",
  "2026-07-22",
  "2026-07-23",
  "2026-07-24",
  "2026-07-25",
];

afterEach(() => {
  sessionStorage.clear();
  window.history.replaceState({}, "", "/");
  vi.unstubAllGlobals();
});

describe("devMockResponse — tendência diária", () => {
  it("serve as quinze observações mais recentes para o endpoint de trend", async () => {
    const fixture = championPageFixture as typeof championPageFixture & {
      trend?: ChampionTrendResponse;
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: async () => fixture,
      }),
    );
    window.history.replaceState({}, "", "/campeao/50?mock=1");

    const response = (await devMockResponse(
      "/champions/50/trend?days=15",
    )) as ChampionTrendResponse | null;

    expect(fixture.trend?.series.map((point) => point.date)).toEqual(
      expectedDates,
    );
    expect(response?.series.map((point) => point.date)).toEqual(expectedDates);
    expect(response?.championId).toBe(50);
    expect(response?.days).toBe(15);
  });
});
