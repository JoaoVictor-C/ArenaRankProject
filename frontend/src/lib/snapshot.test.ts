import { describe, it, expect } from "vitest";
import { seedFrom, type SnapshotFile } from "./snapshot";

const NOW = new Date("2026-07-24T12:00:00Z").getTime();
const HOUR = 60 * 60 * 1000;

function file(generatedAt: number, entries: Record<string, unknown>): SnapshotFile {
  return { generatedAt, entries };
}

describe("seedFrom", () => {
  it("semeia dado fresco com a idade REAL do build", () => {
    const built = NOW - 3 * HOUR;
    const seed = seedFrom<{ rows: number[] }>(file(built, { page1: { rows: [1] } }), "page1", NOW);
    expect(seed.initialData).toEqual({ rows: [1] });
    // Não é Date.now(): é isto que faz o badge dizer "há 3h" em vez de "agora".
    expect(seed.initialDataUpdatedAt).toBe(built);
  });

  it("não semeia quando o build não conseguiu buscar (placeholder null)", () => {
    expect(seedFrom(file(NOW, { page1: null }), "page1", NOW)).toEqual({});
  });

  it("não semeia chave ausente", () => {
    expect(seedFrom(file(NOW, {}), "inexistente", NOW)).toEqual({});
  });

  it("não semeia placeholder nunca gerado (generatedAt 0)", () => {
    expect(seedFrom(file(0, { page1: { rows: [] } }), "page1", NOW)).toEqual({});
  });

  it("descarta semente acima de 24h — ranking da semana passada mina o CR", () => {
    const stale = NOW - 25 * HOUR;
    expect(seedFrom(file(stale, { page1: { rows: [1] } }), "page1", NOW)).toEqual({});
  });

  it("aceita exatamente no limite de 24h", () => {
    const edge = NOW - 24 * HOUR;
    expect(seedFrom(file(edge, { page1: { rows: [1] } }), "page1", NOW).initialData).toBeTruthy();
  });
});
