import { useEffect, type RefObject } from "react";

import { loadMotion } from "../lib/motion";

const DOCK_MEDIA_QUERY =
  "(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)";
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";
const DOCK_REACH = 280;
const DOCK_SCALE = 0.12;
const DOCK_LIFT = -18;
const SHELF_ADVANCE = 0.82;

export function dockInfluence(
  itemCenterX: number,
  pointerX: number,
  reach: number,
): number {
  if (reach <= 0) return 0;
  const distance = Math.abs(itemCenterX - pointerX);
  if (distance >= reach) return 0;
  const ratio = distance / reach;
  return Math.cos(ratio * Math.PI * 0.5);
}

const maxScrollLeft = (row: HTMLElement) =>
  Math.max(0, row.scrollWidth - row.clientWidth);

export function useAugmentsHorizontalGallery(
  scope: RefObject<HTMLElement>,
  key: unknown,
): void {
  useEffect(() => {
    const root = scope.current;
    const rows = Array.from(
      root?.querySelectorAll<HTMLElement>(
        "[data-augment-gallery-row]",
      ) ?? [],
    );
    if (!root || rows.length === 0) return;

    let cancelled = false;
    let dockCleanup: (() => void) | null = null;
    const cleanup: Array<() => void> = [];

    void loadMotion().then((motion) => {
      if (cancelled || !motion) return;
      const { gsap } = motion;
      const dockMedia = window.matchMedia(DOCK_MEDIA_QUERY);
      const reducedMotion = window.matchMedia(REDUCED_MOTION_QUERY);
      root.classList.add("has-augment-shelves");

      rows.forEach((row) => {
        const section = row.closest<HTMLElement>(
          ".augment-rarity-section",
        );
        const previous = section?.querySelector<HTMLButtonElement>(
          "[data-augment-scroll='prev']",
        );
        const next = section?.querySelector<HTMLButtonElement>(
          "[data-augment-scroll='next']",
        );
        if (!section || !previous || !next) return;

        const updateControls = () => {
          const maximum = maxScrollLeft(row);
          previous.disabled = row.scrollLeft <= 1;
          next.disabled = row.scrollLeft >= maximum - 1;
        };
        const move = (direction: -1 | 1) => {
          const maximum = maxScrollLeft(row);
          const target = Math.min(
            maximum,
            Math.max(
              0,
              row.scrollLeft + row.clientWidth * SHELF_ADVANCE * direction,
            ),
          );
          if (reducedMotion.matches) {
            row.scrollLeft = target;
            updateControls();
            return;
          }
          gsap.to(row, {
            scrollLeft: target,
            duration: 0.62,
            ease: "power3.out",
            overwrite: "auto",
            onUpdate: updateControls,
            onComplete: updateControls,
          });
        };
        const movePrevious = () => move(-1);
        const moveNext = () => move(1);

        previous.addEventListener("click", movePrevious);
        next.addEventListener("click", moveNext);
        row.addEventListener("scroll", updateControls, { passive: true });
        window.addEventListener("resize", updateControls);
        row.scrollLeft = 0;
        updateControls();

        cleanup.push(() => {
          previous.removeEventListener("click", movePrevious);
          next.removeEventListener("click", moveNext);
          row.removeEventListener("scroll", updateControls);
          window.removeEventListener("resize", updateControls);
        });
      });

      const setupDock = () => {
        dockCleanup?.();
        dockCleanup = null;
        if (!dockMedia.matches) return;

        const dockRows = rows
          .map((row) => ({
            row,
            cards: Array.from(
              row.querySelectorAll<HTMLElement>(
                "[data-augment-dock-item]",
              ),
            ),
          }))
          .filter(({ cards }) => cards.length > 0);
        const allCards = dockRows.flatMap(({ cards }) => cards);
        const context = gsap.context(() => {
          gsap.set(allCards, {
            transformOrigin: "50% 100%",
            willChange: "transform",
          });
        }, root);
        const rowCleanups: Array<() => void> = [];

        dockRows.forEach(({ row, cards }) => {
          const scaleXTo = cards.map((card) =>
            gsap.quickTo(card, "scaleX", {
              duration: 0.22,
              ease: "power3.out",
            }),
          );
          const scaleYTo = cards.map((card) =>
            gsap.quickTo(card, "scaleY", {
              duration: 0.22,
              ease: "power3.out",
            }),
          );
          const yTo = cards.map((card) =>
            gsap.quickTo(card, "y", {
              duration: 0.22,
              ease: "power3.out",
            }),
          );
          let frame = 0;
          let pointerX = 0;

          const resetDock = () => {
            cards.forEach((_, index) => {
              scaleXTo[index]?.(1);
              scaleYTo[index]?.(1);
              yTo[index]?.(0);
            });
          };
          const renderDock = () => {
            frame = 0;
            const rowLeft = row.getBoundingClientRect().left;
            const localPointer = pointerX - rowLeft + row.scrollLeft;
            cards.forEach((card, index) => {
              const center = card.offsetLeft + card.offsetWidth * 0.5;
              const influence = dockInfluence(
                center,
                localPointer,
                DOCK_REACH,
              );
              const scale = 1 + influence * DOCK_SCALE;
              scaleXTo[index]?.(scale);
              scaleYTo[index]?.(scale);
              yTo[index]?.(influence * DOCK_LIFT);
            });
          };
          const updateDock = (event: PointerEvent) => {
            pointerX = event.clientX;
            if (!frame) frame = window.requestAnimationFrame(renderDock);
          };
          const leaveDock = () => {
            if (frame) window.cancelAnimationFrame(frame);
            frame = 0;
            resetDock();
          };

          row.addEventListener("pointermove", updateDock);
          row.addEventListener("pointerleave", leaveDock);
          rowCleanups.push(() => {
            row.removeEventListener("pointermove", updateDock);
            row.removeEventListener("pointerleave", leaveDock);
            leaveDock();
          });
        });

        dockCleanup = () => {
          rowCleanups.forEach((dispose) => dispose());
          context.revert();
        };
      };

      const onDockMediaChange = () => setupDock();
      dockMedia.addEventListener("change", onDockMediaChange);
      cleanup.push(() =>
        dockMedia.removeEventListener("change", onDockMediaChange),
      );
      setupDock();

      if (cancelled) {
        dockCleanup?.();
        dockCleanup = null;
        cleanup.forEach((dispose) => dispose());
        root.classList.remove("has-augment-shelves");
      }
    });

    return () => {
      cancelled = true;
      dockCleanup?.();
      dockCleanup = null;
      cleanup.forEach((dispose) => dispose());
      root.classList.remove("has-augment-shelves");
    };
  }, [scope, key]);
}
