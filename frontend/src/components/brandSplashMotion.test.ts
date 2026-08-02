import { afterEach, describe, expect, it, vi } from "vitest";
import { loadBrandSplashMotion } from "./brandSplashMotion";

const motionMocks = vi.hoisted(() => ({
  DrawSVGPlugin: {},
  MotionPathPlugin: {},
  prefersReducedMotion: vi.fn(() => false),
  registerPlugin: vi.fn(),
  shouldSkipEntrance: vi.fn(() => false),
}));

vi.mock("../lib/motion", () => ({
  prefersReducedMotion: motionMocks.prefersReducedMotion,
  shouldSkipEntrance: motionMocks.shouldSkipEntrance,
}));

vi.mock("gsap", () => ({
  gsap: {
    registerPlugin: motionMocks.registerPlugin,
  },
}));

vi.mock("gsap/DrawSVGPlugin", () => ({
  DrawSVGPlugin: motionMocks.DrawSVGPlugin,
}));

vi.mock("gsap/MotionPathPlugin", () => ({
  MotionPathPlugin: motionMocks.MotionPathPlugin,
}));

afterEach(() => {
  motionMocks.prefersReducedMotion.mockReset();
  motionMocks.prefersReducedMotion.mockReturnValue(false);
  motionMocks.registerPlugin.mockClear();
  motionMocks.shouldSkipEntrance.mockReset();
  motionMocks.shouldSkipEntrance.mockReturnValue(false);
});

describe("loadBrandSplashMotion", () => {
  it("não carrega movimento quando a preferência reduz animações", async () => {
    motionMocks.prefersReducedMotion.mockReturnValue(true);

    await expect(loadBrandSplashMotion()).resolves.toBeNull();
    expect(motionMocks.registerPlugin).not.toHaveBeenCalled();
  });

  it("mantém o lockup estático quando a aba está oculta", async () => {
    motionMocks.shouldSkipEntrance.mockReturnValue(true);

    await expect(loadBrandSplashMotion()).resolves.toBeNull();
    expect(motionMocks.registerPlugin).not.toHaveBeenCalled();
  });

  it("registra DrawSVG e MotionPath no bundle sob demanda", async () => {
    const bundle = await loadBrandSplashMotion();

    expect(bundle?.gsap.registerPlugin).toBe(motionMocks.registerPlugin);
    expect(bundle?.DrawSVGPlugin).toBe(motionMocks.DrawSVGPlugin);
    expect(bundle?.MotionPathPlugin).toBe(motionMocks.MotionPathPlugin);
    expect(motionMocks.registerPlugin).toHaveBeenCalledWith(
      motionMocks.DrawSVGPlugin,
      motionMocks.MotionPathPlugin,
    );
  });
});
