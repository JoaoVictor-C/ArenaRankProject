import type { gsap as GsapType } from "gsap";
import { prefersReducedMotion, shouldSkipEntrance } from "../lib/motion";

export type BrandSplashMotionBundle = {
  gsap: typeof GsapType;
  DrawSVGPlugin: typeof import("gsap/DrawSVGPlugin").DrawSVGPlugin;
  MotionPathPlugin: typeof import("gsap/MotionPathPlugin").MotionPathPlugin;
};

let brandSplashBundle: Promise<BrandSplashMotionBundle | null> | null = null;

/** Carrega apenas os plugins usados pelo loader e preserva o lockup estático
    quando movimento reduzido está ativo ou o chunk não puder ser carregado. */
export async function loadBrandSplashMotion(): Promise<BrandSplashMotionBundle | null> {
  if (prefersReducedMotion() || shouldSkipEntrance()) return null;

  brandSplashBundle ??= (async () => {
    const [{ gsap }, { DrawSVGPlugin }, { MotionPathPlugin }] =
      await Promise.all([
        import("gsap"),
        import("gsap/DrawSVGPlugin"),
        import("gsap/MotionPathPlugin"),
      ]);

    gsap.registerPlugin(DrawSVGPlugin, MotionPathPlugin);
    return { gsap, DrawSVGPlugin, MotionPathPlugin };
  })().catch(() => null);

  return brandSplashBundle;
}
