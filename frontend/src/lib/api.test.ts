import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, clearAdminKey, getAdminKey, setAdminKey } from "./api";

/** Resposta 200 mínima — evita depender do global Response do ambiente. */
function jsonOk(): Response {
  return { ok: true, status: 200, statusText: "OK", json: async () => ({}) } as unknown as Response;
}

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 422 ? "Unprocessable Entity" : "OK",
    json: async () => body,
  } as unknown as Response;
}

describe("api — chave de admin", () => {
  beforeEach(() => clearAdminKey());
  afterEach(() => clearAdminKey());

  it("set/get/clear faz round-trip e persiste em sessionStorage (com trim)", () => {
    setAdminKey("  k123  ");
    expect(getAdminKey()).toBe("k123");
    expect(sessionStorage.getItem("arenarank.adminKey")).toBe("k123");

    clearAdminKey();
    expect(getAdminKey()).toBeNull();
    expect(sessionStorage.getItem("arenarank.adminKey")).toBeNull();
  });

  it("envia X-Admin-Key só em rotas /admin e só com a chave definida", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonOk());
    vi.stubGlobal("fetch", fetchMock);

    // Sem chave: nem mesmo /admin recebe o header.
    await api.adminOverview();
    expect((fetchMock.mock.calls[0][1] as RequestInit).headers).not.toHaveProperty("X-Admin-Key");

    // Com chave: /admin recebe; rota pública não.
    setAdminKey("secret");
    await api.adminOverview();
    await api.leaderboard();
    expect((fetchMock.mock.calls[1][1] as RequestInit).headers).toHaveProperty(
      "X-Admin-Key",
      "secret",
    );
    expect((fetchMock.mock.calls[2][1] as RequestInit).headers).not.toHaveProperty("X-Admin-Key");
  });
});

describe("api — leaderboard OTP", () => {
  it("cai para 20 jogadores quando o backend ainda rejeita limit=100", async () => {
    const payload = { championId: 50, name: "Swain", players: [] };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(422, { detail: "limit must be <= 20" }))
      .mockResolvedValueOnce(jsonResponse(200, payload));
    vi.stubGlobal("fetch", fetchMock);

    const result = await api.championOtps(50);

    expect(fetchMock.mock.calls[0][0]).toContain("/champions/50/mains?limit=100");
    expect(fetchMock.mock.calls[1][0]).toContain("/champions/50/mains?limit=20");
    expect(result).toEqual({ ...payload, limit: 20, truncated: true });
  });
});
