import { useEffect, useRef, type RefObject } from "react";

import {
  EASE,
  MO,
  loadMotion,
  prefersReducedMotion,
} from "../lib/motion";

export interface PartidaMotionState {
  teamKey: number;
  playerKey: string;
  direction: -1 | 0 | 1;
  ready: boolean;
}

export function usePartidaDossierMotion(
  scope: RefObject<HTMLElement>,
  state: PartidaMotionState,
): void {
  const initialSwapKey = useRef({
    playerKey: state.playerKey,
    teamKey: state.teamKey,
  });
  const hasSelectedAnotherTarget = useRef(false);
  const swapDirection = useRef(state.direction);
  swapDirection.current = state.direction;

  useEffect(() => {
    const root = scope.current;
    if (!root || !state.ready || prefersReducedMotion()) return;

    let cancelled = false;
    let context: { revert: () => void } | null = null;

    void loadMotion()
      .then((motion) => {
        if (cancelled || !motion) return;

        context = motion.gsap.context(() => {
          const timeline = motion.gsap.timeline();
          const heroCopy = root.querySelectorAll<HTMLElement>(
            "[data-hero-copy]",
          );
          const orbitNodes = root.querySelectorAll<HTMLElement>(
            "[data-orbit-node]",
          );
          const orbitCore = root.querySelectorAll<HTMLElement>(
            "[data-orbit-core]",
          );
          const sections = root.querySelectorAll<HTMLElement>(
            "[data-dossier-section]",
          );
          const comparisonSection = root.querySelector<HTMLElement>(
            "[data-comparison-section]",
          );
          const initialRailTargets = root.querySelectorAll<HTMLElement>(
            "[data-comparison-rail] .partida-comparison-mark",
          );

          timeline
            .fromTo(
              heroCopy,
              { opacity: 0, y: 16 },
              {
                opacity: 1,
                y: 0,
                duration: MO.enter,
                ease: EASE.enter,
                stagger: 0.06,
                overwrite: "auto",
                clearProps: "opacity,transform",
              },
            )
            .fromTo(
              orbitNodes,
              { opacity: 0, scale: 0.88 },
              {
                opacity: 1,
                scale: 1,
                duration: MO.enter,
                ease: EASE.enter,
                stagger: 0.05,
                overwrite: "auto",
                clearProps: "opacity,transform",
              },
              "-=0.2",
            )
            .fromTo(
              orbitCore,
              { opacity: 0, scale: 0.94 },
              {
                opacity: 1,
                scale: 1,
                duration: MO.enter,
                ease: EASE.enter,
                overwrite: "auto",
                clearProps: "opacity,transform",
              },
              "-=0.28",
            )
            .fromTo(
              sections,
              { opacity: 0, y: 12 },
              {
                opacity: 1,
                y: 0,
                duration: MO.enter,
                ease: EASE.enter,
                stagger: 0.055,
                overwrite: "auto",
                clearProps: "opacity,transform",
              },
              "-=0.18",
            );

          if (comparisonSection && initialRailTargets.length > 0) {
            motion.gsap.fromTo(
              initialRailTargets,
              { scaleX: 0 },
              {
                scaleX: 1,
                transformOrigin: "left center",
                duration: MO.enter,
                ease: EASE.enter,
                stagger: 0.025,
                overwrite: "auto",
                clearProps: "transform",
                scrollTrigger: {
                  trigger: comparisonSection,
                  start: "top 88%",
                  once: true,
                },
              },
            );
          }
        }, root);
      })
      .catch(() => {
        // O DOM já nasce no estado final; falhas no bundle não escondem conteúdo.
      });

    return () => {
      cancelled = true;
      context?.revert();
    };
  }, [scope, state.ready]);

  useEffect(() => {
    const root = scope.current;
    if (!root || !state.ready || prefersReducedMotion()) return;

    const isInitialHydration =
      !hasSelectedAnotherTarget.current &&
      initialSwapKey.current.playerKey === "" &&
      state.teamKey === initialSwapKey.current.teamKey &&
      state.playerKey !== "";
    if (isInitialHydration) {
      initialSwapKey.current = {
        playerKey: state.playerKey,
        teamKey: state.teamKey,
      };
      return;
    }

    const isInitialTarget =
      state.teamKey === initialSwapKey.current.teamKey &&
      state.playerKey === initialSwapKey.current.playerKey;
    if (!hasSelectedAnotherTarget.current && isInitialTarget) return;
    hasSelectedAnotherTarget.current = true;
    const direction = swapDirection.current;

    let cancelled = false;
    let context: { revert: () => void } | null = null;

    void loadMotion()
      .then((motion) => {
        if (cancelled || !motion) return;

        context = motion.gsap.context(() => {
          const swapTargets = root.querySelectorAll<HTMLElement>(
            "[data-team-swap], [data-team-player], [data-focused-player]",
          );
          const railTargets = root.querySelectorAll<HTMLElement>(
            "[data-comparison-rail] .partida-comparison-mark",
          );
          const selectedOrbitNode = root.querySelector<HTMLElement>(
            '[data-orbit-node][aria-pressed="true"]',
          );

          motion.gsap.fromTo(
            swapTargets,
            { opacity: 0, x: direction * 24 },
            {
              opacity: 1,
              x: 0,
              duration: MO.ui,
              ease: EASE.ui,
              stagger: 0.035,
              overwrite: "auto",
              clearProps: "opacity,transform",
            },
          );
          if (direction !== 0 && selectedOrbitNode) {
            motion.gsap.fromTo(
              selectedOrbitNode,
              { scale: 0.94, z: -16 },
              {
                scale: 1.06,
                z: 16,
                duration: MO.ui,
                ease: EASE.ui,
                overwrite: "auto",
                clearProps: "transform",
              },
            );
          }
          if (railTargets.length > 0) {
            motion.gsap.fromTo(
              railTargets,
              { scaleX: 0 },
              {
                scaleX: 1,
                transformOrigin: "left center",
                duration: MO.enter,
                ease: EASE.enter,
                stagger: 0.025,
                overwrite: "auto",
                clearProps: "transform",
              },
            );
          }
        }, root);
      })
      .catch(() => {
        // O conteúdo continua visível quando o movimento não pode iniciar.
      });

    return () => {
      cancelled = true;
      context?.revert();
    };
  }, [
    scope,
    state.playerKey,
    state.ready,
    state.teamKey,
  ]);
}
