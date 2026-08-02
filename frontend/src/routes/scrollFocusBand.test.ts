import { describe, expect, it } from "vitest";

import { focusAt } from "./scrollFocusBand";

describe("focusAt", () => {
  it("entrega foco cheio exatamente sobre o ponto de referência", () => {
    expect(focusAt(0, 320)).toBe(1);
  });

  it("zera ao alcançar o raio de influência, e não vira negativo depois", () => {
    expect(focusAt(320, 320)).toBe(0);
    expect(focusAt(9000, 320)).toBe(0);
  });

  it("é simétrico acima e abaixo do ponto", () => {
    expect(focusAt(-120, 320)).toBeCloseTo(focusAt(120, 320), 10);
  });

  it("achata as pontas: quase não muda perto do centro nem perto da borda", () => {
    expect(focusAt(16, 320) - focusAt(0, 320)).toBeGreaterThan(-0.02);
    expect(focusAt(304, 320)).toBeLessThan(0.02);
  });

  it("a nitidez afunda o meio sem tocar nos extremos", () => {
    // O ponto e a borda são invariantes — só o miolo desce.
    expect(focusAt(0, 320, 4)).toBe(1);
    expect(focusAt(320, 320, 4)).toBe(0);
    // Com sharpness 1 a curva é a smoothstep pura (0,5 na metade do raio).
    expect(focusAt(160, 320, 1)).toBeCloseTo(0.5, 6);
    // O default apaga bem mais o vizinho fora de foco.
    expect(focusAt(160, 320)).toBeLessThan(0.2);
    // E é monotônico na nitidez: mais expoente, menos cor fora do foco.
    expect(focusAt(160, 320, 4)).toBeLessThan(focusAt(160, 320, 2));
  });

  it("degrada para zero se o raio for inválido", () => {
    expect(focusAt(10, 0)).toBe(0);
    expect(focusAt(10, -5)).toBe(0);
  });
});
