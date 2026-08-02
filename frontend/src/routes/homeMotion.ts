import { useEffect, useRef, type RefObject } from "react";

import { loadMotion } from "../lib/motion";

type Revertible = {
  revert(): void;
};

type SplitInstance = Revertible & {
  lines?: Element[];
  words?: Element[];
};

const DESKTOP_QUERY =
  "(min-width: 1081px) and (prefers-reduced-motion: no-preference)";
const FEATURE_AMBIENT_QUERY =
  "(min-width: 681px) and (prefers-reduced-motion: no-preference)";
const FEATURE_POINTER_QUERY =
  "(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)";

function readCounterValue(target: HTMLElement): number | null {
  const normalized = target.textContent
    ?.trim()
    .replace(/\./g, "")
    .replace(",", ".");
  if (!normalized) return null;
  const value = Number(normalized);
  return Number.isFinite(value) ? value : null;
}

export function useFeatureCardMotion(
  scope: RefObject<HTMLElement>,
  palette: readonly [string, string],
): void {
  const [deep, bright] = palette;
  const previousPalette = useRef<readonly [string, string]>(palette);

  useEffect(() => {
    const root = scope.current;
    if (!root) return;

    const fromPalette = previousPalette.current;
    previousPalette.current = [deep, bright];
    let cancelled = false;
    let context: Revertible | null = null;

    void loadMotion().then((motion) => {
      if (cancelled || !motion) return;

      context = motion.gsap.context(() => {
        motion.gsap.fromTo(
          root,
          {
            "--fc-deep": fromPalette[0],
            "--fc-bright": fromPalette[1],
          },
          {
            "--fc-deep": deep,
            "--fc-bright": bright,
            duration: 0.42,
            ease: "power2.inOut",
            overwrite: "auto",
          },
        );
      }, root);
    });

    return () => {
      cancelled = true;
      context?.revert();
    };
  }, [bright, deep, scope]);

  useEffect(() => {
    const root = scope.current;
    if (!root) return;

    let cancelled = false;
    let context: Revertible | null = null;
    let media: Revertible | null = null;

    void loadMotion().then((motion) => {
      if (cancelled || !motion) return;

      context = motion.gsap.context(() => {
        const shapes = Array.from(
          root.querySelectorAll<HTMLElement>("[data-feature-shape]"),
        );
        const field = root.querySelector<HTMLElement>(".fc-energy__field");
        const beam = root.querySelector<HTMLElement>("[data-feature-beam]");
        const frame = root.querySelector<HTMLElement>("[data-feature-frame]");
        const splash = root.querySelector<HTMLElement>(".fc-bg");
        const action = root.querySelector<HTMLElement>(".fc-btn");

        const intro = motion.gsap.timeline({
          defaults: { ease: "power3.out" },
        });
        intro.addLabel("energy", 0.08);
        if (shapes.length) {
          intro.fromTo(
            shapes,
            { autoAlpha: 0, scale: 0.78 },
            {
              autoAlpha: 1,
              scale: 1,
              duration: 0.7,
              stagger: 0.06,
              immediateRender: false,
              clearProps: "opacity,visibility,transform",
            },
            "energy",
          );
        }
        if (frame) {
          intro.fromTo(
            frame,
            { clipPath: "inset(0 100% 0 0)" },
            {
              clipPath: "inset(0 0% 0 0)",
              duration: 0.7,
              immediateRender: false,
              clearProps: "clipPath",
            },
            "energy",
          );
        }
        if (beam) {
          intro.fromTo(
            beam,
            { autoAlpha: 0, scaleX: 0.72 },
            {
              autoAlpha: 1,
              scaleX: 1,
              duration: 0.42,
              immediateRender: false,
              clearProps: "opacity,visibility,transform",
            },
            "energy+=0.18",
          );
        }
        if (action) {
          intro.fromTo(
            action,
            { autoAlpha: 0, y: 6 },
            {
              autoAlpha: 1,
              y: 0,
              duration: 0.22,
              immediateRender: false,
              clearProps: "opacity,visibility,transform",
            },
            "energy+=0.38",
          );
        }

        const featureMedia = motion.gsap.matchMedia();
        media = featureMedia;

        featureMedia.add(FEATURE_AMBIENT_QUERY, () => {
          const ambient = motion.gsap.timeline({
            defaults: { ease: "sine.inOut" },
            paused: true,
            repeat: -1,
            yoyo: true,
          });
          if (shapes[0]) {
            ambient.to(shapes[0], { x: 9, y: -4, scale: 1.04, duration: 9 }, 0);
          }
          if (shapes[1]) {
            ambient.to(shapes[1], { x: -7, y: 5, scale: 1.06, duration: 11 }, 0);
          }
          if (shapes[2]) {
            ambient.to(shapes[2], { x: 6, y: 4, scale: 0.96, duration: 8 }, 0);
          }
          if (beam) {
            ambient.to(beam, { opacity: 0.3, duration: 7 }, 0);
          }

          const bounds = root.getBoundingClientRect();
          let visible =
            bounds.bottom > 0 && bounds.top < (window.innerHeight || 800);
          const syncAmbient = () => {
            if (document.visibilityState === "hidden" || !visible) {
              ambient.pause();
              return;
            }
            ambient.play();
          };
          const visibilityTrigger = motion.ScrollTrigger.create({
            trigger: root,
            start: "top bottom",
            end: "bottom top",
            onEnter: () => {
              visible = true;
              syncAmbient();
            },
            onEnterBack: () => {
              visible = true;
              syncAmbient();
            },
            onLeave: () => {
              visible = false;
              syncAmbient();
            },
            onLeaveBack: () => {
              visible = false;
              syncAmbient();
            },
          });
          document.addEventListener("visibilitychange", syncAmbient);
          syncAmbient();

          return () => {
            document.removeEventListener("visibilitychange", syncAmbient);
            visibilityTrigger.kill();
            ambient.kill();
          };
        });

        featureMedia.add(FEATURE_POINTER_QUERY, () => {
          if (!field && !beam && !splash) return;

          const quickOptions = {
            duration: 0.42,
            ease: "power3.out",
            overwrite: "auto" as const,
          };
          const fieldX = field
            ? motion.gsap.quickTo(field, "x", quickOptions)
            : null;
          const fieldY = field
            ? motion.gsap.quickTo(field, "y", quickOptions)
            : null;
          const beamX = beam
            ? motion.gsap.quickTo(beam, "x", quickOptions)
            : null;
          const beamY = beam
            ? motion.gsap.quickTo(beam, "y", quickOptions)
            : null;
          const splashX = splash
            ? motion.gsap.quickTo(splash, "x", quickOptions)
            : null;
          let rect: DOMRect | null = null;

          const cacheRect = () => {
            rect = root.getBoundingClientRect();
          };
          const reset = () => {
            fieldX?.(0);
            fieldY?.(0);
            beamX?.(0);
            beamY?.(0);
            splashX?.(0);
            rect = null;
          };
          const move = (event: PointerEvent) => {
            rect ??= root.getBoundingClientRect();
            const normalizedX = Math.max(
              -1,
              Math.min(1, ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 2 - 1),
            );
            const normalizedY = Math.max(
              -1,
              Math.min(1, ((event.clientY - rect.top) / Math.max(rect.height, 1)) * 2 - 1),
            );
            fieldX?.(normalizedX * 10);
            fieldY?.(normalizedY * 6);
            beamX?.(normalizedX * 6);
            beamY?.(normalizedY * 3);
            splashX?.(normalizedX * 3);
          };

          root.addEventListener("pointerenter", cacheRect);
          root.addEventListener("pointermove", move, { passive: true });
          root.addEventListener("pointerleave", reset);

          return () => {
            root.removeEventListener("pointerenter", cacheRect);
            root.removeEventListener("pointermove", move);
            root.removeEventListener("pointerleave", reset);
          };
        });
      }, root);
    });

    return () => {
      cancelled = true;
      media?.revert();
      context?.revert();
    };
  }, [scope]);
}

export function useHomeMotion(
  scope: RefObject<HTMLElement>,
  deps: unknown[],
): void {
  useEffect(() => {
    const root = scope.current;
    if (!root) return;

    let cancelled = false;
    let context: Revertible | null = null;
    let media: Revertible | null = null;
    let split: SplitInstance | null = null;
    let counterTarget: HTMLElement | null = null;
    let counterFinal = "";

    void loadMotion().then((motion) => {
      if (cancelled || !motion) return;

      context = motion.gsap.context(() => {
        const feature = root.querySelector<HTMLElement>("[data-home-feature]");
        const manifesto = root.querySelector<HTMLElement>(
          "[data-home-manifesto]",
        );
        const paths = Array.from(
          root.querySelectorAll<SVGPathElement>("[data-home-meta-path]"),
        );

        if (feature) {
          motion.gsap.fromTo(
            feature,
            {
              autoAlpha: 0,
              y: 28,
              clipPath: "inset(0 4% 14% 4%)",
            },
            {
              autoAlpha: 1,
              y: 0,
              clipPath: "inset(0 0% 0% 0%)",
              duration: 0.7,
              ease: "power3.out",
              clearProps: "opacity,visibility,transform,clipPath",
            },
          );

          counterTarget = feature.querySelector<HTMLElement>("[data-countup]");
          const counterValue = counterTarget
            ? readCounterValue(counterTarget)
            : null;
          if (counterTarget && counterValue !== null) {
            counterFinal = counterTarget.textContent ?? "";
            const counter = { value: Math.max(0, counterValue - 420) };
            const formatter = new Intl.NumberFormat("pt-BR", {
              maximumFractionDigits: 0,
            });
            motion.gsap.to(counter, {
              value: counterValue,
              duration: 0.7,
              ease: "power2.inOut",
              onUpdate: () => {
                if (counterTarget) {
                  counterTarget.textContent = formatter.format(
                    Math.round(counter.value),
                  );
                }
              },
              onComplete: () => {
                if (counterTarget) counterTarget.textContent = counterFinal;
              },
            });
          }
        }

        if (manifesto) {
          split = new motion.SplitText(manifesto, {
            type: "lines,words",
            mask: "lines",
            aria: "auto",
          }) as SplitInstance;
          const manifestoTimeline = motion.gsap.timeline({
            scrollTrigger: {
              trigger: manifesto,
              start: "top 82%",
              once: true,
            },
          });
          manifestoTimeline.from(split.lines ?? [], {
            yPercent: 108,
            opacity: 0,
            duration: 0.7,
            stagger: 0.06,
            ease: "power3.out",
          });
          manifestoTimeline.from(
            split.words ?? [],
            {
              color: "var(--text-dim)",
              duration: 0.22,
              stagger: 0.025,
              ease: "power2.out",
            },
            "-=0.28",
          );
        }

        if (paths.length) {
          motion.gsap.fromTo(
            paths,
            { drawSVG: "0%" },
            {
              drawSVG: "100%",
              duration: 0.7,
              stagger: 0.06,
              ease: "power2.inOut",
              scrollTrigger: {
                trigger: paths[0].closest(".home-meta"),
                start: "top 78%",
                once: true,
              },
            },
          );
        }

        const stage = root.querySelector<HTMLElement>("[data-home-portals]");
        const viewport = stage?.querySelector<HTMLElement>(
          ".home-portals__viewport",
        );
        const track = stage?.querySelector<HTMLElement>(
          "[data-home-portal-track]",
        );

        const portalMedia = motion.gsap.matchMedia();
        media = portalMedia;
        portalMedia.add(DESKTOP_QUERY, () => {
          if (!stage || !viewport || !track) return;

          const travel = () =>
            Math.max(0, track.scrollWidth - viewport.clientWidth);
          if (travel() <= 0) return;

          const tween = motion.gsap.to(track, {
            x: () => -travel(),
            ease: "none",
            scrollTrigger: {
              trigger: viewport,
              start: "center center",
              end: () =>
                `+=${Math.max(window.innerWidth, track.scrollWidth)}`,
              scrub: 0.65,
              pin: stage,
              anticipatePin: 1,
              invalidateOnRefresh: true,
            },
          });

          return () => tween.kill();
        });

        motion.ScrollTrigger.refresh();
      }, root);
    });

    return () => {
      cancelled = true;
      if (counterTarget && counterFinal) counterTarget.textContent = counterFinal;
      split?.revert();
      media?.revert();
      context?.revert();
    };
    // `deps` é a identidade dos dados que alteram as medidas da narrativa.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
