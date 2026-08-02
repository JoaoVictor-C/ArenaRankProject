import { describe, it, expect } from "vitest";
import { persistOptions } from "./queryPersist";
import type { Query } from "@tanstack/react-query";

/** Query mínima com o que `defaultShouldDehydrateQuery` inspeciona. */
function fakeQuery(fetcherSource: string, status = "success"): Query {
  return {
    queryKey: [fetcherSource],
    state: { status, data: {}, fetchStatus: "idle" },
    meta: undefined,
  } as unknown as Query;
}

const shouldDehydrate = persistOptions.dehydrateOptions!.shouldDehydrateQuery!;

describe("persistOptions.shouldDehydrateQuery", () => {
  it("persiste dado público (leaderboard/perfil)", () => {
    expect(shouldDehydrate(fakeQuery("()=>T.player(a)"))).toBe(true);
    expect(shouldDehydrate(fakeQuery("()=>T.leaderboard({})"))).toBe(true);
  });

  it("NÃO persiste dado de admin no disco do navegador", () => {
    // Forma minificada real observada no bundle: `()=>T.adminOverview(`.
    expect(shouldDehydrate(fakeQuery("()=>T.adminOverview()"))).toBe(false);
  });

  it("não persiste query que falhou", () => {
    expect(shouldDehydrate(fakeQuery("()=>T.player(a)", "error"))).toBe(false);
  });

  it("descarta cache com mais de 6h em vez de pintar CR velho", () => {
    expect(persistOptions.maxAge).toBe(6 * 60 * 60 * 1000);
  });
});
