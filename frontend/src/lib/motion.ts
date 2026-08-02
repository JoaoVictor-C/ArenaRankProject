/* ============================================================
   motion.ts — o ÚNICO ponto de entrada de movimento do cluster de
   campeões (/winrate · /campeao · /augments · /sinergias).

   Régua (frontend/.impeccable/motion-brief.md): movimento aqui é
   explicação, não enfeite. Vocabulário fechado de durações/easings;
   fora dele, nada.

   Três garantias que o sistema precisa manter:
   1. Nada fica preso invisível. O estado inicial é aplicado por JS,
      nunca por CSS — se o script falhar, o conteúdo já está legível.
   2. `prefers-reduced-motion` desliga tudo e entrega o estado final.
   3. O bundle de rotas é sob demanda: home e leaderboard não pagam
      por Flip, DrawSVG ou SplitText. Nenhum componente importa `gsap` direto.
   ============================================================ */
import { useEffect, useRef, type RefObject } from "react";
import type { gsap as GsapType } from "gsap";

/* ── Vocabulário fechado ──────────────────────────────────────── */
export const MO = {
  micro: 0.12,
  ui: 0.22,
  enter: 0.42,
  data: 0.7,
  flip: 0.38,
} as const;

export const EASE = {
  micro: "power2.out",
  ui: "power2.out",
  enter: "power3.out",
  data: "power2.inOut",
  flip: "power2.inOut",
} as const;

/** Entrada: 16px. O mock usava 28px — em tela de Operate aquilo lê como salto. */
const ENTER_Y = 16;
/** Escalonar 40 cards vira espera; do 9º em diante todos entram juntos. */
const STAGGER = 0.06;
const STAGGER_MAX = 8;

/* ── Carga sob demanda ────────────────────────────────────────── */
type Bundle = {
  gsap: typeof GsapType;
  ScrollTrigger: typeof import("gsap/ScrollTrigger").ScrollTrigger;
  Flip: typeof import("gsap/Flip").Flip;
  DrawSVGPlugin: typeof import("gsap/DrawSVGPlugin").DrawSVGPlugin;
  SplitText: typeof import("gsap/SplitText").SplitText;
};

type SmootherBundle = {
  gsap: typeof GsapType;
  ScrollTrigger: typeof import("gsap/ScrollTrigger").ScrollTrigger;
  ScrollSmoother: typeof import("gsap/ScrollSmoother").ScrollSmoother;
};

type AmbientBundle = {
  gsap: typeof GsapType;
};

let bundle: Promise<Bundle> | null = null;
let smootherBundle: Promise<SmootherBundle> | null = null;
let ambientBundle: Promise<AmbientBundle> | null = null;

export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    !!window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * Aba em background pausa o requestAnimationFrame. Animar a ENTRADA ali é
 * pior que inútil: o estado inicial (opacity 0) é aplicado e nada avança —
 * quem abriu a página em outra aba encontraria conteúdo invisível.
 * Ninguém está olhando de qualquer forma; entrega o estado final.
 */
export function shouldSkipEntrance(): boolean {
  return typeof document !== "undefined" && document.visibilityState === "hidden";
}

/** Resolve para `null` quando o movimento está desligado — quem chama
    entrega o estado final sem animar. */
export async function loadMotion(): Promise<Bundle | null> {
  if (prefersReducedMotion()) return null;
  bundle ??= (async () => {
    const [
      { gsap },
      { ScrollTrigger },
      { Flip },
      { DrawSVGPlugin },
      { SplitText },
    ] = await Promise.all([
      import("gsap"),
      import("gsap/ScrollTrigger"),
      import("gsap/Flip"),
      import("gsap/DrawSVGPlugin"),
      import("gsap/SplitText"),
    ]);
    gsap.registerPlugin(ScrollTrigger, Flip, DrawSVGPlugin, SplitText);
    return { gsap, ScrollTrigger, Flip, DrawSVGPlugin, SplitText };
  })();
  return bundle;
}

/** Bundle mínimo para loops globais: carrega somente o núcleo do GSAP. */
export async function loadAmbientMotion(): Promise<AmbientBundle | null> {
  if (prefersReducedMotion()) return null;
  ambientBundle ??= import("gsap").then(({ gsap }) => ({ gsap }));
  return ambientBundle;
}

/** Bundle global e mínimo do scroll: não puxa Flip, DrawSVG nem SplitText. */
export async function loadSmoother(): Promise<SmootherBundle | null> {
  if (prefersReducedMotion()) return null;
  smootherBundle ??= (async () => {
    const [{ gsap }, { ScrollTrigger }, { ScrollSmoother }] =
      await Promise.all([
        import("gsap"),
        import("gsap/ScrollTrigger"),
        import("gsap/ScrollSmoother"),
      ]);
    gsap.registerPlugin(ScrollTrigger, ScrollSmoother);
    return { gsap, ScrollTrigger, ScrollSmoother };
  })();
  return smootherBundle;
}

/* ── Números pt-BR ────────────────────────────────────────────
   O contador precisa devolver o MESMO formato que o React escreveu
   (vírgula decimal, ponto de milhar, prefixo e sufixo preservados),
   senão o valor final "pisca" para outro formato ao terminar. */
type Num = { pre: string; post: string; value: number; decimals: number };

function parsePtBr(raw: string): Num | null {
  const m = raw.trim().match(/^([^\d-]*)(-?[\d.,]+)(.*)$/);
  if (!m) return null;
  const [, pre, numStr, post] = m;
  let decimals = 0;
  let value: number;
  if (numStr.includes(",")) {
    decimals = (numStr.split(",")[1] || "").length;
    value = parseFloat(numStr.replace(/\./g, "").replace(",", "."));
  } else {
    value = parseFloat(numStr.replace(/\./g, ""));
  }
  return Number.isFinite(value) ? { pre, post, value, decimals } : null;
}

function formatPtBr(n: number, { pre, post, decimals }: Num): string {
  const s = decimals > 0 ? n.toFixed(decimals).replace(".", ",") : String(Math.round(n));
  const parts = s.split(",");
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return pre + parts.join(",") + post;
}

export type ChartParts = {
  line: SVGPathElement | null;
  area: SVGPathElement | null;
  marks: SVGElement[];
};

/** O chart React explicita `fill="none"` na linha. Aceitar também paths sem
    `fill` mantém o helper compatível com SVGs desenhados por outras rotas. */
export function queryChartParts(svg: SVGSVGElement): ChartParts {
  const explicitMarks = Array.from(
    svg.querySelectorAll<SVGElement>("[data-chart-mark]"),
  );
  return {
    line: svg.querySelector<SVGPathElement>(
      "[data-chart-line], path[stroke][fill='none'], path[stroke]:not([fill])",
    ),
    area: svg.querySelector<SVGPathElement>(
      "[data-chart-area], path[fill^='url']",
    ),
    marks:
      explicitMarks.length > 0
        ? explicitMarks
        : Array.from(
            svg.querySelectorAll<SVGElement>(
              "circle, line[stroke-dasharray], text",
            ),
          ),
  };
}

/** O Flip só captura o que o jogador consegue acompanhar. Além de reduzir o
    custo nas listas longas, isso evita transforms absolutos fora da dobra. */
export function visibleTargets(root: HTMLElement, selector: string): HTMLElement[] {
  const viewportHeight = window.innerHeight || 800;
  return Array.from(root.querySelectorAll<HTMLElement>(selector)).filter((element) => {
    const rect = element.getBoundingClientRect();
    return rect.bottom > 0 && rect.top < viewportHeight;
  });
}

export type MotionVars = {
  opacity?: number;
  x?: number | string;
  y?: number | string;
  rotation?: number;
  scale?: number;
  scaleX?: number;
  clipPath?: string;
  filter?: string;
  transformOrigin?: string;
};

export type EntranceStep = {
  selector: string;
  from: MotionVars;
  to?: MotionVars;
  duration?: number;
  ease?: string;
  stagger?: number;
  position?: number | string;
  clearProps?: string;
};

export type InteractionMotion = {
  trigger: string;
  target?: string;
  to: MotionVars;
  rest?: MotionVars;
};

export type LoopMotion = {
  selector: string;
  to: MotionVars;
  duration: number;
  repeat: number;
  yoyo?: boolean;
  ease?: string;
};

export type LoopOptions = {
  /** Usa somente o núcleo do GSAP, sem plugins de rota. */
  minimal?: boolean;
  /** Mantém os alvos estáticos sem iniciar nem carregar movimento. */
  disabled?: boolean;
};

/** Loading feedback shared by every GSAP-owned route. */
export const STATE_SPINNER_LOOP: LoopMotion = {
  selector: ".state-spinner",
  to: { rotation: 360 },
  duration: 0.8,
  repeat: -1,
  ease: "none",
};

function finalVars(from: MotionVars, to: MotionVars = {}): MotionVars {
  return {
    ...("opacity" in from ? { opacity: 1 } : {}),
    ...("x" in from ? { x: 0 } : {}),
    ...("y" in from ? { y: 0 } : {}),
    ...("scale" in from ? { scale: 1 } : {}),
    ...("scaleX" in from ? { scaleX: 1 } : {}),
    ...("clipPath" in from ? { clipPath: "inset(0% 0% 0% 0%)" } : {}),
    ...("filter" in from ? { filter: "none" } : {}),
    ...to,
  };
}

function restVars(to: MotionVars): MotionVars {
  return {
    ...("opacity" in to ? { opacity: 1 } : {}),
    ...("x" in to ? { x: 0 } : {}),
    ...("y" in to ? { y: 0 } : {}),
    ...("scale" in to ? { scale: 1 } : {}),
    ...("scaleX" in to ? { scaleX: 1 } : {}),
    ...("clipPath" in to ? { clipPath: "inset(0% 0% 0% 0%)" } : {}),
    ...("filter" in to ? { filter: "none" } : {}),
  };
}

export interface EntranceOptions {
  steps: EntranceStep[];
  deps?: unknown[];
}

/** Timeline autoral por rota. Os seletores vivem na página; GSAP e as
    garantias de visibilidade/cleanup permanecem centralizados aqui. */
export function useGsapEntrance(
  scope: RefObject<HTMLElement>,
  { steps, deps = [] }: EntranceOptions,
): void {
  useEffect(() => {
    const root = scope.current;
    if (!root) return;

    let ctx: { revert: () => void } | null = null;
    let cancelled = false;
    void loadMotion().then((motion) => {
      if (cancelled || !motion || shouldSkipEntrance()) return;
      ctx = motion.gsap.context(() => {
        const timeline = motion.gsap.timeline();
        steps.forEach((step) => {
          const targets = Array.from(root.querySelectorAll<HTMLElement>(step.selector));
          if (!targets.length) return;
          timeline.fromTo(
            targets,
            step.from,
            {
              ...finalVars(step.from, step.to),
              duration: step.duration ?? MO.enter,
              ease: step.ease ?? EASE.enter,
              stagger: step.stagger ?? 0,
              clearProps: step.clearProps ?? "opacity,transform,clipPath,filter",
            },
            step.position,
          );
        });
      }, root);
    });

    return () => {
      cancelled = true;
      ctx?.revert();
    };
    // `steps` é configuração declarativa da renderização atual; quem chama
    // escolhe explicitamente quando rearmar a timeline por `deps`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

/** Entrada breve do conteúdo substituído por aba, seleção ou dataset. A
    primeira renderização pertence à timeline de página e não repete aqui. */
export function useGsapSwap(
  scope: RefObject<HTMLElement>,
  selector: string,
  key: unknown,
  { from = { opacity: 0, y: 8 }, duration = MO.ui }: { from?: MotionVars; duration?: number } = {},
): void {
  const initial = useRef(true);

  useEffect(() => {
    if (initial.current) {
      initial.current = false;
      return;
    }
    const root = scope.current;
    const target = root?.querySelector<HTMLElement>(selector);
    if (!root || !target) return;

    let ctx: { revert: () => void } | null = null;
    let cancelled = false;
    void loadMotion().then((motion) => {
      if (cancelled || !motion || shouldSkipEntrance()) return;
      ctx = motion.gsap.context(() => {
        motion.gsap.fromTo(target, from, {
          ...finalVars(from),
          duration,
          ease: EASE.ui,
          overwrite: "auto",
          clearProps: "opacity,transform,clipPath,filter",
        });
      }, root);
    });

    return () => {
      cancelled = true;
      ctx?.revert();
    };
    // `from` costuma ser um literal declarativo da rota; a troca só pode
    // rearmar quando a identidade do conteúdo muda.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
}

/** Loops visuais continuam pertencendo ao GSAP e pausam fora da aba. */
export function useGsapLoop(
  scope: RefObject<HTMLElement>,
  loops: LoopMotion[],
  deps: unknown[] = [],
  options: LoopOptions = {},
): void {
  useEffect(() => {
    const root = scope.current;
    if (!root || options.disabled) return;

    let ctx: { revert: () => void } | null = null;
    let cancelled = false;
    let onVisibility: (() => void) | null = null;
    let observer: MutationObserver | null = null;
    const tweens: Array<{
      pause: () => unknown;
      resume: () => unknown;
      kill?: () => unknown;
    }> = [];
    const animatedTargets = new Set<HTMLElement>();

    const loadLoopMotion = options.minimal ? loadAmbientMotion : loadMotion;
    void loadLoopMotion().then((motion) => {
      if (cancelled || !motion || shouldSkipEntrance()) return;
      const startNewTargets = () => {
        loops.forEach((loop) => {
          const targets = Array.from(root.querySelectorAll<HTMLElement>(loop.selector)).filter(
            (target) => !animatedTargets.has(target),
          );
          if (!targets.length) return;
          targets.forEach((target) => animatedTargets.add(target));
          tweens.push(
            motion.gsap.to(targets, {
              ...loop.to,
              duration: loop.duration,
              repeat: loop.repeat,
              yoyo: loop.yoyo ?? false,
              ease: loop.ease ?? EASE.data,
            }),
          );
        });
      };
      ctx = motion.gsap.context(() => {
        startNewTargets();
      }, root);
      observer = new MutationObserver(startNewTargets);
      observer.observe(root, { childList: true, subtree: true });
      onVisibility = () => {
        tweens.forEach((tween) => {
          if (document.visibilityState === "hidden") tween.pause();
          else tween.resume();
        });
      };
      document.addEventListener("visibilitychange", onVisibility);
    });

    return () => {
      cancelled = true;
      if (onVisibility) document.removeEventListener("visibilitychange", onVisibility);
      observer?.disconnect();
      tweens.forEach((tween) => tween.kill?.());
      ctx?.revert();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

/** Microinterações delegadas: linhas e cards injetados depois do fetch não
    precisam registrar um effect por item, e teclado recebe o mesmo motion. */
export function useGsapInteractions(
  scope: RefObject<HTMLElement>,
  interactions: InteractionMotion[],
): void {
  useEffect(() => {
    const root = scope.current;
    if (!root) return;

    let ctx: { revert: () => void } | null = null;
    let cancelled = false;
    const removers: Array<() => void> = [];

    void loadMotion().then((motion) => {
      if (cancelled || !motion) return;
      if (prefersReducedMotion()) return;

      const resolve = (event: Event, config: InteractionMotion) => {
        const source = event.target;
        if (!(source instanceof Element)) return null;
        const trigger = source.closest<HTMLElement>(config.trigger);
        if (!trigger || !root.contains(trigger)) return null;
        const target = config.target
          ? trigger.querySelector<HTMLElement>(config.target)
          : trigger;
        return target ? { trigger, target } : null;
      };

      const bind = (type: string, listener: EventListener) => {
        root.addEventListener(type, listener);
        removers.push(() => root.removeEventListener(type, listener));
      };

      ctx = motion.gsap.context(() => {
        interactions.forEach((config) => {
          const enter: EventListener = (event) => {
            const found = resolve(event, config);
            if (!found) return;
            const related = "relatedTarget" in event ? event.relatedTarget : null;
            if (related instanceof Node && found.trigger.contains(related)) return;
            motion.gsap.to(found.target, {
              ...config.to,
              duration: MO.micro,
              ease: EASE.micro,
              overwrite: "auto",
            });
          };
          const leave: EventListener = (event) => {
            const found = resolve(event, config);
            if (!found) return;
            const related = "relatedTarget" in event ? event.relatedTarget : null;
            if (related instanceof Node && found.trigger.contains(related)) return;
            motion.gsap.to(found.target, {
              ...restVars(config.to),
              ...config.rest,
              duration: MO.micro,
              ease: EASE.micro,
              overwrite: "auto",
              clearProps: "transform,opacity,clipPath,filter",
            });
          };

          bind("pointerover", enter);
          bind("pointerout", leave);
          bind("focusin", enter);
          bind("focusout", leave);
        });
      }, root);
    });

    return () => {
      cancelled = true;
      removers.forEach((remove) => remove());
      ctx?.revert();
    };
  }, [scope, interactions]);
}

/* ── 1. Entrada de blocos + contadores ────────────────────────── */
export interface RevealOptions {
  /** Seletor dos blocos que entram. */
  blocks: string;
  /** Re-arma quando estes valores mudam (ex.: os dados chegaram). */
  deps?: unknown[];
}

/**
 * Revela os blocos do escopo com stagger e conta os números marcados
 * com `data-countup`. O que já está no primeiro viewport entra na hora
 * (numa SPA o conteúdo chega DEPOIS do mount; esperar scroll deixaria a
 * dobra visível parada); o resto espera o ScrollTrigger.
 */
export function useReveal(scope: RefObject<HTMLElement>, { blocks, deps = [] }: RevealOptions): void {
  useEffect(() => {
    const root = scope.current;
    if (!root) return;

    const els = Array.from(root.querySelectorAll<HTMLElement>(blocks)).filter(
      // Só o bloco mais externo anima: aninhar reveals dobra o movimento.
      (el) => !el.parentElement?.closest(blocks),
    );
    const counters = Array.from(root.querySelectorAll<HTMLElement>("[data-countup]"));

    let ctx: { revert: () => void } | null = null;
    let cancelled = false;

    void loadMotion().then((m) => {
      if (cancelled) return;
      if (!m || shouldSkipEntrance()) {
        // reduced-motion ou aba oculta: estado final, sem animar.
        counters.forEach((el) => el.removeAttribute("data-countup"));
        return;
      }
      const { gsap } = m;
      ctx = gsap.context(() => {
        const vh = window.innerHeight || 800;
        const above: HTMLElement[] = [];
        const below: HTMLElement[] = [];
        els.forEach((el) => (el.getBoundingClientRect().top < vh * 0.95 ? above : below).push(el));

        const enter = (targets: HTMLElement[], stagger: boolean) =>
          gsap.fromTo(
            targets,
            { opacity: 0, y: ENTER_Y },
            {
              opacity: 1,
              y: 0,
              duration: MO.enter,
              ease: EASE.enter,
              stagger: stagger ? { each: STAGGER, amount: STAGGER * STAGGER_MAX } : 0,
              clearProps: "opacity,transform",
            },
          );

        if (above.length) enter(above, true);
        below.forEach((el) => {
          gsap.set(el, { opacity: 0, y: ENTER_Y });
          gsap.to(el, {
            opacity: 1,
            y: 0,
            duration: MO.enter,
            ease: EASE.enter,
            clearProps: "opacity,transform",
            scrollTrigger: { trigger: el, start: "top 88%", once: true },
          });
        });

        counters.forEach((el) => {
          const parsed = parsePtBr(el.textContent || "");
          if (!parsed) return;
          const obj = { n: 0 };
          gsap.to(obj, {
            n: parsed.value,
            duration: MO.data,
            ease: EASE.data,
            onUpdate: () => {
              el.textContent = formatPtBr(obj.n, parsed);
            },
            onComplete: () => {
              el.textContent = formatPtBr(parsed.value, parsed);
            },
          });
        });
      }, root);
    });

    return () => {
      cancelled = true;
      ctx?.revert();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

/* ── 2. Curvas que se desenham ────────────────────────────────── */
/**
 * Desenha as linhas dos SVGs do escopo com DrawSVG e revela a área a partir
 * de 45% da duração. Marcadores entram quando a curva termina para manter
 * o dado legível durante o traçado.
 */
export function useDrawCharts(scope: RefObject<HTMLElement>, deps: unknown[] = []): void {
  useEffect(() => {
    const root = scope.current;
    if (!root) return;
    let ctx: { revert: () => void } | null = null;
    let cancelled = false;

    void loadMotion().then((m) => {
      if (cancelled || !m || shouldSkipEntrance()) return;
      const { gsap } = m;
      ctx = gsap.context(() => {
        root.querySelectorAll<SVGSVGElement>("svg").forEach((svg) => {
          const { line, area, marks } = queryChartParts(svg);
          if (!line) return;

          const requestedDuration = Number.parseFloat(
            svg.dataset.drawDuration ?? "",
          );
          const duration =
            Number.isFinite(requestedDuration) && requestedDuration > 0
              ? requestedDuration
              : 1;
          const tl = gsap.timeline({
            scrollTrigger: { trigger: svg, start: "top 92%", once: true },
          });
          tl.fromTo(
            line,
            { drawSVG: "0%" },
            {
              drawSVG: "100%",
              duration,
              ease: EASE.data,
              clearProps: "strokeDasharray,strokeDashoffset",
            },
            0,
          );
          if (area) {
            tl.fromTo(
              area,
              { opacity: 0 },
              { opacity: 1, duration: MO.ui },
              duration * 0.45,
            );
          }
          if (marks.length) {
            tl.fromTo(
              marks,
              { opacity: 0 },
              { opacity: 1, duration: MO.ui, stagger: 0.03 },
              duration,
            );
          }
        });
      }, root);
    });

    return () => {
      cancelled = true;
      ctx?.revert();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

/* ── 3. Flip: reordenar/filtrar sem perder o fio ──────────────── */
/**
 * Anima a lista da ordem antiga para a nova quando `key` muda: cada item
 * viaja da posição em que estava. É o que permite seguir uma linha com os
 * olhos ao ordenar a tabela, em vez de a lista piscar.
 *
 * Uso: chame `capture()` ANTES da mudança de estado; o efeito anima depois
 * que o React repintou.
 */
export function useFlipList(
  scope: RefObject<HTMLElement>,
  items: string,
  key: unknown,
): { capture: () => void } {
  const stateRef = useRef<unknown>(null);
  const bundleRef = useRef<Bundle | null>(null);

  useEffect(() => {
    void loadMotion().then((m) => {
      bundleRef.current = m;
    });
  }, []);

  const capture = () => {
    const m = bundleRef.current;
    const root = scope.current;
    if (!m || !root) return;
    stateRef.current = m.Flip.getState(visibleTargets(root, items));
  };

  useEffect(() => {
    const m = bundleRef.current;
    const state = stateRef.current;
    if (!m || !state) return;
    stateRef.current = null;
    // Mesma razão da entrada: sem rAF, o Flip deixaria os itens transformados.
    if (shouldSkipEntrance()) return;
    m.Flip.from(state as Parameters<typeof m.Flip.from>[0], {
      duration: MO.flip,
      ease: EASE.flip,
      absolute: true,
      onEnter: (el) => m.gsap.fromTo(el, { opacity: 0, scale: 0.96 }, { opacity: 1, scale: 1, duration: MO.ui }),
      onLeave: (el) => m.gsap.to(el, { opacity: 0, scale: 0.96, duration: MO.micro }),
    });
  }, [key]);

  return { capture };
}

/* ── 5. Match Lab: expansão + SplitText ─────────────────────── */
/**
 * A linha de partida permanece legível sem GSAP; este hook só assume a
 * continuidade visual. A abertura mede o conteúdo real e a revelação interna
 * respeita a ordem de leitura: título → times → jogadores → loadouts.
 */
export function useGsapMatchDetail(
  scope: RefObject<HTMLElement>,
  open: boolean,
  ready: boolean,
): void {
  const wasOpen = useRef(false);

  useEffect(() => {
    const root = scope.current;
    const panel = root?.querySelector<HTMLElement>(".hist-detail");
    const inner = panel?.querySelector<HTMLElement>(".hist-detail-inner");
    if (!root || !panel || !inner) return;

    const openedBefore = wasOpen.current;
    wasOpen.current = open;
    if (!open && !openedBefore) return;

    let cancelled = false;
    let ctx: ReturnType<Bundle["gsap"]["context"]> | null = null;

    void loadMotion().then((motion) => {
      if (cancelled) return;
      if (!motion) {
        panel.removeAttribute("style");
        return;
      }

      ctx = motion.gsap.context(() => {
        if (open) {
          motion.gsap.fromTo(
            panel,
            { height: 0, opacity: 0.7, visibility: "visible" },
            {
              height: "auto",
              opacity: 1,
              duration: MO.enter,
              ease: "expo.out",
              clearProps: "height,opacity,visibility",
            },
          );
          return;
        }

        motion.gsap.fromTo(
          panel,
          {
            height: Math.max(panel.scrollHeight, inner.scrollHeight),
            opacity: 1,
            visibility: "visible",
          },
          {
            height: 0,
            opacity: 0.65,
            duration: MO.ui,
            ease: EASE.ui,
            clearProps: "height,opacity,visibility",
          },
        );
      }, root);
    });

    return () => {
      cancelled = true;
      ctx?.revert();
    };
  }, [open, scope]);

  useEffect(() => {
    if (!open || !ready) return;
    const root = scope.current;
    if (!root) return;

    let cancelled = false;
    let ctx: ReturnType<Bundle["gsap"]["context"]> | null = null;
    let split: { revert(): void; words?: Element[] } | null = null;

    void loadMotion().then((motion) => {
      if (cancelled || !motion) return;

      ctx = motion.gsap.context(() => {
        const title = root.querySelector<HTMLElement>("[data-match-title]");
        if (title) {
          split = new motion.SplitText(title, {
            type: "words",
            mask: "words",
          });
        }

        const timeline = motion.gsap.timeline({
          defaults: { ease: "expo.out" },
        });
        if (split?.words?.length) {
          timeline.from(split.words, {
            yPercent: 112,
            opacity: 0,
            duration: MO.enter,
            stagger: 0.035,
          });
        }
        timeline.from(
          visibleTargets(root, "[data-match-team]"),
          {
            clipPath: "inset(0 0 100% 0)",
            opacity: 0,
            duration: MO.enter,
            stagger: 0.055,
          },
          split?.words?.length ? "-=0.2" : 0,
        );
        timeline.from(
          visibleTargets(root, "[data-match-player]"),
          {
            y: 12,
            opacity: 0,
            duration: MO.ui,
            stagger: 0.025,
          },
          "-=0.24",
        );
        timeline.from(
          visibleTargets(
            root,
            "[data-match-item], [data-match-augment]",
          ),
          {
            scale: 0.82,
            opacity: 0,
            duration: MO.ui,
            stagger: 0.012,
          },
          "-=0.18",
        );
      }, root);
    });

    return () => {
      cancelled = true;
      split?.revert();
      ctx?.revert();
    };
  }, [open, ready, scope]);
}
