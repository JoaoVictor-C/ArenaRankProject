import { useEffect, type RefObject } from "react";

import { prefersReducedMotion } from "../lib/motion";

/** Progresso 0..1 de um elemento em relação a um ponto de referência.
 *
 * Curva suave (smoothstep) em vez de linear: a linear troca de inclinação de
 * forma seca ao cruzar o ponto, o que lê como um "clique" visual.
 *
 * `sharpness` é o expoente aplicado depois. Ele preserva os dois extremos —
 * cheio no ponto, zero na borda — e afunda tudo no meio: com 1 a linha vizinha
 * ainda aparece quase acesa, com 2,6 ela já apagou. É o controle de "quanto o
 * fora-de-foco desaparece", sem mexer no pico. */
export function focusAt(distance: number, falloff: number, sharpness = 2.6): number {
  if (falloff <= 0) return 0;
  const t = Math.min(1, Math.max(0, 1 - Math.abs(distance) / falloff));
  const smooth = t * t * (3 - 2 * t);
  return sharpness === 1 ? smooth : Math.pow(smooth, sharpness);
}

type FocusBandOptions = {
  /** Distância, em px, onde a influência do ponto chega a zero. */
  falloff?: number;
  /** Custom property escrita em cada elemento. */
  property?: string;
  /** Valor fixo quando o usuário pede menos movimento. */
  restingValue?: number;
};

/** Banda de foco ancorada num ponto invisível no centro da viewport.
 *
 * Um único ponto de referência governa a lista inteira: cada elemento recebe
 * sua proximidade como custom property e o CSS decide o que fazer com ela. É
 * deliberadamente UM sistema, e não uma animação por linha — cem efeitos
 * independentes numa lista de leitura brigam com a varredura.
 *
 * O laço só visita o que o IntersectionObserver reporta visível, e só escreve
 * quando o valor muda de verdade, então uma lista de cem partidas custa o mesmo
 * que uma de dez. */
export function useScrollFocusBand(
  scope: RefObject<HTMLElement>,
  selector: string,
  options: FocusBandOptions = {},
): void {
  const { falloff = 320, property = "--focus", restingValue = 0.34 } = options;

  useEffect(() => {
    const root = scope.current;
    if (!root || typeof IntersectionObserver === "undefined") return;

    const visible = new Set<HTMLElement>();
    const written = new WeakMap<HTMLElement, number>();

    const write = (element: HTMLElement, value: number): void => {
      const rounded = Math.round(value * 100) / 100;
      if (written.get(element) === rounded) return;
      written.set(element, rounded);
      element.style.setProperty(property, String(rounded));
    };

    if (prefersReducedMotion()) {
      root
        .querySelectorAll<HTMLElement>(selector)
        .forEach((element) => write(element, restingValue));
      return;
    }

    let frame = 0;
    const paint = (): void => {
      frame = 0;
      const anchor = window.innerHeight / 2;
      visible.forEach((element) => {
        const box = element.getBoundingClientRect();
        write(element, focusAt(box.top + box.height / 2 - anchor, falloff));
      });
    };
    const schedule = (): void => {
      if (frame) return;
      frame = requestAnimationFrame(paint);
    };

    const intersection = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const element = entry.target as HTMLElement;
          if (entry.isIntersecting) visible.add(element);
          else {
            visible.delete(element);
            write(element, 0);
          }
        });
        schedule();
      },
      // Margem generosa: a linha já começa a responder antes de entrar, então
      // ela não "acende" de repente na borda da tela.
      { rootMargin: "40% 0px" },
    );

    const sync = (): void => {
      root.querySelectorAll<HTMLElement>(selector).forEach((element) => {
        intersection.observe(element);
      });
    };
    sync();

    // A lista cresce com "Carregar mais" — as linhas novas precisam entrar no
    // observador, senão nascem sem foco e ficam apagadas para sempre.
    const mutation = new MutationObserver(sync);
    mutation.observe(root, { childList: true, subtree: true });

    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    schedule();

    return () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      mutation.disconnect();
      intersection.disconnect();
    };
  }, [falloff, property, restingValue, scope, selector]);
}
