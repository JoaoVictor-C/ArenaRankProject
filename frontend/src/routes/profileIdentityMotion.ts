import { useEffect, type RefObject } from "react";

import { nf } from "../lib/format";
import { loadMotion, prefersReducedMotion } from "../lib/motion";

/** Percurso dos marcadores do nick: da ponta do nome até o começo dele.
 *
 * A medida precisa vir do DOM porque o nick varia de largura por jogador, e o
 * percurso é do NOME — não da placa, que também abraça a tagline. As duas
 * medidas viram custom properties para o CSS posicionar o marcador; o percurso
 * alimenta o tween. Um `ResizeObserver` remede e reconstrói quando a largura
 * muda de verdade (fonte carregando, quebra de layout, zoom). */
export function useGsapNameMarkers(
  scope: RefObject<HTMLElement>,
  identity: string | undefined,
): void {
  useEffect(() => {
    const root = scope.current;
    const cube = root?.querySelector<HTMLElement>(".pfb-name-cube");
    const nick = cube?.querySelector<HTMLElement>("[data-profile-nick]");
    if (!cube || !nick) return;

    const measure = (): number => {
      const cubeBox = cube.getBoundingClientRect();
      const nickBox = nick.getBoundingClientRect();
      cube.style.setProperty("--pfb-nick-x", `${nickBox.left - cubeBox.left}px`);
      cube.style.setProperty("--pfb-nick-w", `${nickBox.width}px`);
      return nickBox.width;
    };

    let travel = measure();
    let cancelled = false;
    let context: { revert: () => void } | null = null;

    const build = (): void => {
      if (cancelled || prefersReducedMotion()) return;
      void loadMotion().then((motion) => {
        if (cancelled || !motion) return;
        context = motion.gsap.context(() => {
          cube
            .querySelectorAll<HTMLElement>(".pfb-name-cube__marker")
            .forEach((marker, index) => {
              motion.gsap.to(marker, {
                x: -travel,
                duration: index === 0 ? 1 : 1.35,
                repeat: -1,
                yoyo: true,
                ease: "power1.inOut",
                overwrite: "auto",
              });
            });
        }, cube);
      });
    };

    build();

    // Só reconstrói quando o percurso muda de forma perceptível — senão cada
    // pixel de reflow reiniciaria a animação do zero.
    const observer = new ResizeObserver(() => {
      const next = measure();
      if (Math.abs(next - travel) < 1) return;
      travel = next;
      context?.revert();
      context = null;
      build();
    });
    observer.observe(nick);

    return () => {
      cancelled = true;
      observer.disconnect();
      context?.revert();
    };
  }, [identity, scope]);
}

export function useGsapProfilePdl(
  scope: RefObject<HTMLElement>,
  value: number | null,
  identity: string | undefined,
): void {
  useEffect(() => {
    const root = scope.current;
    const target = root?.querySelector<HTMLElement>("[data-profile-pdl]");
    if (!root || !target || value === null) return;

    target.textContent = nf(value);
    if (prefersReducedMotion()) return;

    let cancelled = false;
    let context: { revert: () => void } | null = null;

    void loadMotion().then((motion) => {
      if (cancelled || !motion) return;

      context = motion.gsap.context(() => {
        const counter = { value: 0 };
        target.textContent = nf(counter.value);
        motion.gsap.to(counter, {
          value,
          duration: 2,
          ease: "power1.out",
          snap: { value: 1 },
          overwrite: "auto",
          onUpdate: () => {
            target.textContent = nf(Math.round(counter.value));
          },
          onComplete: () => {
            target.textContent = nf(value);
          },
        });
      }, root);
    });

    return () => {
      cancelled = true;
      context?.revert();
      target.textContent = nf(value);
    };
  }, [identity, scope, value]);
}
