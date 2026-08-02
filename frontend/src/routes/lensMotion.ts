import { useEffect, type RefObject } from "react";
import type { gsap as GsapType } from "gsap";

import type { LensAxisKey } from "./lensModel";

const MO = { ui: 0.22, enter: 0.42, data: 0.7 } as const;
const EASE = { ui: "power2.out", enter: "power3.out", data: "power2.inOut" } as const;

let gsapBundle: Promise<typeof GsapType> | null = null;

function reduceMotion(): boolean {
  return Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
}

function skipEntrance(): boolean {
  return document.visibilityState === "hidden";
}

async function loadGsap(): Promise<typeof GsapType | null> {
  if (reduceMotion()) return null;
  gsapBundle ??= import("gsap").then(({ gsap }) => gsap);
  return gsapBundle;
}

export function useLensEntrance(scope: RefObject<HTMLElement>): void {
  useEffect(() => {
    const root = scope.current;
    if (!root || reduceMotion() || skipEntrance()) return;

    let cancelled = false;
    let context: { revert: () => void } | null = null;

    void loadGsap().then((gsap) => {
      if (cancelled || !gsap) return;
      context = gsap.context(() => {
        const timeline = gsap.timeline();
        timeline
          .fromTo(
            root.querySelectorAll(".lens-identity > *"),
            { opacity: 0, y: 14 },
            {
              opacity: 1,
              y: 0,
              duration: MO.enter,
              ease: EASE.enter,
              stagger: 0.05,
              clearProps: "opacity,transform",
            },
          )
          .fromTo(
            root.querySelectorAll(".lens-hero > *"),
            { opacity: 0, y: 20, clipPath: "inset(0 0 12% 0)" },
            {
              opacity: 1,
              y: 0,
              clipPath: "inset(0 0 0% 0)",
              duration: 0.62,
              ease: "power3.out",
              stagger: 0.07,
              clearProps: "opacity,transform,clipPath",
            },
            0.08,
          )
          .fromTo(
            root.querySelectorAll(".lens-trajectory, .lens-axis-stage"),
            { opacity: 0, y: 16 },
            {
              opacity: 1,
              y: 0,
              duration: MO.enter,
              ease: EASE.enter,
              stagger: 0.08,
              clearProps: "opacity,transform",
            },
            0.18,
          );

        gsap.fromTo(
          root.querySelectorAll(".lens-radar-player, .lens-radar-top"),
          { opacity: 0, scale: 0.72, transformOrigin: "50% 50%" },
          {
            opacity: 1,
            scale: 1,
            duration: MO.data,
            ease: EASE.data,
            stagger: 0.08,
            clearProps: "opacity,transform",
          },
        );

        const spark = root.querySelector<SVGPathElement>(".lens-trajectory-line");
        if (spark) {
          const length = spark.getTotalLength?.() ?? 0;
          if (length > 0) {
            gsap.fromTo(
              spark,
              { strokeDasharray: length, strokeDashoffset: length },
              {
                strokeDashoffset: 0,
                duration: MO.data,
                ease: EASE.data,
                clearProps: "strokeDasharray,strokeDashoffset",
              },
            );
          }
        }
      }, root);
    });

    return () => {
      cancelled = true;
      context?.revert();
    };
  }, [scope]);
}

export function useLensAxisMotion(
  scope: RefObject<HTMLElement>,
  axis: LensAxisKey,
): void {
  useEffect(() => {
    const root = scope.current;
    if (!root || reduceMotion() || skipEntrance()) return;

    let cancelled = false;
    let context: { revert: () => void } | null = null;

    void loadGsap().then((gsap) => {
      if (cancelled || !gsap) return;
      context = gsap.context(() => {
        gsap.fromTo(
          root.querySelector(".lens-axis-panel"),
          { opacity: 0, y: 10 },
          {
            opacity: 1,
            y: 0,
            duration: MO.ui,
            ease: EASE.ui,
            clearProps: "opacity,transform",
          },
        );
        gsap.fromTo(
          root.querySelectorAll(".lens-metric-fill"),
          { scaleX: 0, transformOrigin: "0% 50%" },
          {
            scaleX: 1,
            duration: MO.data,
            ease: EASE.data,
            stagger: 0.024,
            clearProps: "transform",
          },
        );
      }, root);
    });

    return () => {
      cancelled = true;
      context?.revert();
    };
  }, [axis, scope]);
}
