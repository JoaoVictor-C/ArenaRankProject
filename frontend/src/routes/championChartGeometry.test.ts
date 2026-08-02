import { describe, expect, it } from "vitest";

import {
  buildMonotoneGeometry,
  normalizeTimelineX,
  resolveChartDomain,
} from "./championChartGeometry";

describe("normalizeTimelineX", () => {
  it("preserva o intervalo maior deixado por um dia sem amostra", () => {
    const positions = normalizeTimelineX(
      [0, 86_400_000, 259_200_000],
      40,
      290,
    );

    expect(positions[0]).toBe(40);
    expect(positions[1]).toBeCloseTo(123.333, 3);
    expect(positions[2]).toBe(290);
  });
});

describe("buildMonotoneGeometry", () => {
  it("passa por cada âncora observada sem ultrapassar o intervalo local", () => {
    const geometry = buildMonotoneGeometry(
      [
        { x: 40, y: 90 },
        { x: 120, y: 24 },
        { x: 290, y: 68 },
      ],
      132,
    );

    expect(geometry.segments).toHaveLength(2);
    expect(geometry.line.match(/\bC/g)).toHaveLength(2);
    expect(geometry.area).toContain(
      geometry.line.slice(geometry.line.indexOf("C")),
    );

    geometry.segments.forEach(({ start, control1, control2, end }) => {
      const low = Math.min(start.y, end.y);
      const high = Math.max(start.y, end.y);
      expect(control1.y).toBeGreaterThanOrEqual(low);
      expect(control1.y).toBeLessThanOrEqual(high);
      expect(control2.y).toBeGreaterThanOrEqual(low);
      expect(control2.y).toBeLessThanOrEqual(high);
    });
  });
});

describe("resolveChartDomain", () => {
  it("ancora o domínio na média em vez de esticar min-máx", () => {
    // Série quase parada: min-máx puro daria span 0,4 e encheria o gráfico.
    const { min, max } = resolveChartDomain([52.1, 52.3, 51.9, 52.5]);
    expect(max - min).toBeGreaterThan(5);
    const mean = (52.1 + 52.3 + 51.9 + 52.5) / 4;
    expect((min + max) / 2).toBeCloseTo(mean, 5);
  });

  it("deixa a amplitude real mandar quando ela supera o piso", () => {
    const { min, max } = resolveChartDomain([10, 90]);
    expect(min).toBeLessThan(10);
    expect(max).toBeGreaterThan(90);
  });

  it("não devolve amplitude zero para série perfeitamente plana", () => {
    const { min, max } = resolveChartDomain([50, 50, 50]);
    expect(max).toBeGreaterThan(min);
  });

  it("respeita limites duros da unidade", () => {
    const { min, max } = resolveChartDomain([2, 3], { bounds: [0, 100] });
    expect(min).toBeGreaterThanOrEqual(0);
    expect(max).toBeLessThanOrEqual(100);
  });

  it("sobrevive a série vazia e a valores não finitos", () => {
    expect(resolveChartDomain([]).max).toBeGreaterThan(resolveChartDomain([]).min);
    const { min, max } = resolveChartDomain([Number.NaN, 40, Number.POSITIVE_INFINITY]);
    expect(Number.isFinite(min) && Number.isFinite(max)).toBe(true);
  });
});

describe("resolveChartDomain — contrato de uso", () => {
  it("devolve limites de EIXO, que não são valores da série", () => {
    // Regressão: o consumidor original fazia `vals.indexOf(maxV)` para achar o
    // pico. Isso funcionava enquanto maxV era Math.max(...vals). Com domínio
    // ancorado na média o teto deixa de ser um ponto real, indexOf devolve -1,
    // e o acesso ao ponto estoura. Quem precisa do pico deve calcular o pico.
    const values = [1200, 1240, 1190, 1260];
    const { min, max } = resolveChartDomain(values);
    expect(values).not.toContain(max);
    expect(values).not.toContain(min);
    expect(values.indexOf(max)).toBe(-1);
    // E o domínio precisa conter a série inteira, senão o traço sai do quadro.
    expect(min).toBeLessThanOrEqual(Math.min(...values));
    expect(max).toBeGreaterThanOrEqual(Math.max(...values));
  });
});
