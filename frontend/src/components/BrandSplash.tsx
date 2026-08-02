import { useEffect, useRef, useState } from "react";
import {
  useIsRestoring,
  useQueryClient,
  type Query,
} from "@tanstack/react-query";
import { useLocation } from "react-router-dom";
import { prefersReducedMotion } from "../lib/motion";
import { loadBrandSplashMotion } from "./brandSplashMotion";
import "./BrandSplash.css";

type SplashPhase = "checking" | "visible" | "exiting" | "hidden";

const ROUTE_MESSAGES: Array<[prefix: string, message: string]> = [
  ["/leaderboard", "Carregando tabela do Arena"],
  ["/campeonatos", "Carregando campeonatos do Arena"],
  ["/campeonatos2", "Carregando campeonatos do Arena"],
  ["/winrate", "Carregando estatísticas de campeões"],
  ["/campeao", "Carregando dados do campeão"],
  ["/augments", "Carregando catálogo de augments"],
  ["/sinergias", "Carregando sinergias do Arena"],
  ["/perfil", "Carregando perfil do jogador"],
  ["/partida", "Carregando detalhes da partida"],
  ["/duo", "Carregando busca de dupla"],
  ["/sistema", "Carregando sistema de ranking"],
  ["/admin", "Carregando painel administrativo"],
];

const WIRE_PATH =
  "M1280 171C1120 171 914 205 777 184C693 171 646 111 683 69C724 22 802 62 796 130C790 201 707 237 627 214C539 188 520 91 574 59C635 23 705 86 674 148C642 212 544 247 459 219C380 193 335 114 373 68C414 18 497 58 493 132C489 211 387 261 285 229C191 199 141 116 187 70C234 23 322 64 317 142C313 219 231 256 152 228C53 193 -21 181 -176 190C-10 194 136 207 262 187C321 178 352 163 390 160";

function messageForRoute(pathname: string): string {
  if (pathname === "/") return "Carregando a Arena";
  return (
    ROUTE_MESSAGES.find(([prefix]) => pathname.startsWith(prefix))?.[1] ??
    "Carregando página do ArenaRank"
  );
}

function queryBlocksRequest(query: Query): boolean {
  return (
    query.state.status === "pending" || query.state.fetchStatus !== "idle"
  );
}

export function BrandSplash() {
  const queryClient = useQueryClient();
  const isRestoring = useIsRestoring();
  const { pathname } = useLocation();
  const rootRef = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<SplashPhase>("checking");

  useEffect(() => {
    setPhase("checking");
    if (isRestoring) return;

    const cache = queryClient.getQueryCache();
    let cancelled = false;
    let decisionVersion = 0;
    let observedRequest = false;
    let visitCompleted = false;
    const trackedQueries = new Set<Query>();
    const siteIsLoading = () =>
      document.querySelector('main .state-block[aria-busy="true"]') !== null;

    const decideFromCache = () => {
      if (cancelled || visitCompleted) return;
      const currentDecision = ++decisionVersion;

      const activeQueries = cache.getAll().filter((query) => query.isActive());
      const blockingActiveQueries = activeQueries.filter(queryBlocksRequest);
      const blockingSiteState = siteIsLoading();

      // O Suspense pode montar o StateBlock antes de a rota criar sua query.
      // O portão cobre ambos sem exigir alterações no shell ou nas páginas.
      if (blockingActiveQueries.length > 0 || blockingSiteState) {
        blockingActiveQueries.forEach((query) => trackedQueries.add(query));
        observedRequest = true;
        setPhase("visible");
        return;
      }

      if (observedRequest) {
        // StrictMode remove e remonta observers no mesmo turno. Confirmar a
        // ociosidade na microtask seguinte evita encerrar durante essa lacuna,
        // sem acrescentar uma duração mínima perceptível ao loader.
        queueMicrotask(() => {
          if (
            cancelled ||
            visitCompleted ||
            currentDecision !== decisionVersion
          ) {
            return;
          }

          // A query observada continua sendo a fonte de verdade mesmo durante
          // o intervalo em que o StrictMode remove todos os seus observers.
          const stillBlocked = Array.from(trackedQueries).some(
            queryBlocksRequest,
          );
          if (stillBlocked || siteIsLoading()) {
            setPhase("visible");
            return;
          }

          visitCompleted = true;
          setPhase((current) =>
            current === "visible" ? "exiting" : "hidden",
          );
        });
        return;
      }

      // A rota lazy ainda pode não ter montado sua query. Queries inativas de
      // visitas anteriores não concluem a visita atual.
      if (activeQueries.length === 0) {
        return;
      }

      // A rota já tinha dados frescos e não abriu rede: não há espera a cobrir.
      visitCompleted = true;
      setPhase("hidden");
    };

    // A assinatura vem antes da leitura para fechar a janela entre observar
    // cache vazio e a rede resolver no turno seguinte.
    const unsubscribe = cache.subscribe(decideFromCache);
    const siteObserver = new MutationObserver(decideFromCache);
    siteObserver.observe(document.querySelector("#root") ?? document.body, {
      attributes: true,
      attributeFilter: ["aria-busy"],
      childList: true,
      subtree: true,
    });
    decideFromCache();
    return () => {
      cancelled = true;
      decisionVersion += 1;
      siteObserver.disconnect();
      unsubscribe();
    };
  }, [isRestoring, pathname, queryClient]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || phase === "checking" || phase === "hidden") return;

    if (phase === "exiting" && prefersReducedMotion()) {
      setPhase("hidden");
      return;
    }

    let cancelled = false;
    let context: { revert(): void } | null = null;

    void loadBrandSplashMotion().then((motion) => {
      if (cancelled) return;
      if (!motion) {
        if (phase === "exiting") setPhase("hidden");
        return;
      }

      context = motion.gsap.context(() => {
        const orbitPath = root.querySelector<SVGPathElement>(
          ".brand-splash__orbit-path",
        );
        const orbitTraces = Array.from(
          root.querySelectorAll<SVGPathElement>(
            ".brand-splash__orbit-trace",
          ),
        );
        const orbitRunner = root.querySelector<SVGPathElement>(
          ".brand-splash__orbit-runner",
        );
        const runner = root.querySelector<HTMLElement>(
          ".brand-splash__runner",
        );
        const emblem = root.querySelector<HTMLElement>(
          ".brand-splash__brand-emblem",
        );
        const mark = root.querySelector<HTMLImageElement>(
          ".brand-splash__brand-mark",
        );
        const coreGlow = root.querySelector<HTMLElement>(
          ".brand-splash__brand-core-glow",
        );
        const letters = Array.from(
          root.querySelectorAll<HTMLElement>(".brand-splash__letter"),
        );
        const status = root.querySelector<HTMLElement>(
          ".brand-splash__status",
        );
        const aura = root.querySelector<HTMLElement>(
          ".brand-splash__aura",
        );

        if (phase === "visible") {
          if (
            !orbitPath ||
            !orbitRunner ||
            !runner ||
            !emblem ||
            !mark ||
            !coreGlow ||
            !status
          ) {
            return;
          }

          const intro = motion.gsap.timeline({
            defaults: { ease: "power3.out" },
          });

          intro
            .addLabel("fio", 0.06)
            .fromTo(
              orbitPath,
              { drawSVG: "0% 0%" },
              {
                drawSVG: "0% 100%",
                duration: 1.34,
                ease: "power2.inOut",
              },
              "fio",
            )
            .fromTo(
              orbitTraces,
              { drawSVG: "0% 0%", autoAlpha: 0 },
              {
                drawSVG: "0% 100%",
                autoAlpha: 0.56,
                duration: 1.42,
                stagger: 0.045,
                ease: "power2.inOut",
              },
              "fio+=0.03",
            )
            .fromTo(
              runner,
              { autoAlpha: 0, scale: 0.38 },
              {
                autoAlpha: 1,
                scale: 1,
                duration: 1.3,
                ease: "power2.inOut",
                motionPath: {
                  path: orbitPath,
                  align: orbitPath,
                  alignOrigin: [0.5, 0.5],
                  autoRotate: true,
                  start: 0,
                  end: 1,
                },
              },
              "fio+=0.02",
            )
            .addLabel("ignicao", "fio+=1.28")
            .fromTo(
              emblem,
              { autoAlpha: 0.28, rotation: -3, scale: 0.94 },
              {
                autoAlpha: 0.62,
                rotation: -1,
                scale: 0.97,
                duration: 0.07,
                ease: "power1.out",
              },
              "ignicao",
            )
            .to(
              emblem,
              { autoAlpha: 0.42, duration: 0.06, ease: "power1.in" },
              "ignicao+=0.07",
            )
            .to(
              emblem,
              {
                autoAlpha: 1,
                rotation: 0,
                scale: 1.045,
                duration: 0.14,
                ease: "power4.out",
              },
              "ignicao+=0.13",
            )
            .fromTo(
              mark,
              { filter: "brightness(0.34) saturate(0.28)" },
              {
                filter: "brightness(0.68) saturate(0.72)",
                duration: 0.07,
                ease: "power1.out",
              },
              "ignicao",
            )
            .to(
              mark,
              {
                filter: "brightness(0.44) saturate(0.5)",
                duration: 0.06,
                ease: "power1.in",
              },
              "ignicao+=0.07",
            )
            .to(
              mark,
              {
                filter: "brightness(1.26) saturate(1.62)",
                duration: 0.14,
                ease: "power4.out",
              },
              "ignicao+=0.13",
            )
            .to(
              mark,
              {
                filter: "brightness(1) saturate(1)",
                duration: 0.34,
                ease: "power2.out",
                clearProps: "filter",
              },
              "ignicao+=0.27",
            )
            .fromTo(
              coreGlow,
              { autoAlpha: 0, scale: 0.65 },
              {
                autoAlpha: 0.34,
                scale: 0.92,
                duration: 0.07,
                ease: "power1.out",
              },
              "ignicao",
            )
            .to(
              coreGlow,
              {
                autoAlpha: 0.06,
                scale: 0.88,
                duration: 0.06,
                ease: "power1.in",
              },
              "ignicao+=0.07",
            )
            .to(
              coreGlow,
              {
                autoAlpha: 1,
                scale: 1.24,
                duration: 0.14,
                ease: "power4.out",
              },
              "ignicao+=0.13",
            )
            .to(
              coreGlow,
              {
                autoAlpha: 0.28,
                scale: 1.12,
                duration: 0.16,
                ease: "power1.out",
              },
              "ignicao+=0.27",
            )
            .to(
              coreGlow,
              {
                autoAlpha: 0,
                scale: 1.48,
                duration: 0.38,
                ease: "power2.out",
              },
              "ignicao+=0.43",
            )
            .to(
              runner,
              {
                autoAlpha: 0,
                scale: 2.1,
                duration: 0.2,
                ease: "power2.out",
              },
              "ignicao",
            )
            .to(
              emblem,
              { scale: 1, duration: 0.34, ease: "power2.out" },
              "ignicao+=0.27",
            )
            .from(
              letters,
              {
                autoAlpha: 0,
                yPercent: 115,
                stagger: 0.035,
                duration: 0.46,
              },
              "ignicao+=0.06",
            )
            .from(
              status,
              { autoAlpha: 0, y: 8, duration: 0.32 },
              "ignicao+=0.3",
            );

          if (aura) {
            intro.fromTo(
              aura,
              { autoAlpha: 0, scale: 0.72 },
              { autoAlpha: 1, scale: 1, duration: 0.72 },
              "fio-=0.06",
            );
          }

          motion.gsap.fromTo(
            orbitRunner,
            { drawSVG: "0% 8%" },
            {
              drawSVG: "92% 100%",
              duration: 1.55,
              delay: 1.48,
              ease: "none",
              repeat: -1,
            },
          );
          return;
        }

        // A troca de fase reverte a entrada antes desta timeline: uma resposta
        // rápida da API interrompe a coreografia sem impor duração mínima.
        const exit = motion.gsap.timeline();
        exit
          .to(
            letters,
            {
              autoAlpha: 0,
              yPercent: -70,
              duration: 0.18,
              ease: "power2.in",
              stagger: { amount: 0.1, from: "edges" },
            },
            0,
          )
          .to(
            [orbitPath, orbitRunner, ...orbitTraces].filter(Boolean),
            {
              drawSVG: "50% 50%",
              autoAlpha: 0,
              duration: 0.28,
              ease: "power2.in",
            },
            0,
          )
          .to(
            [emblem, runner].filter(Boolean),
            {
              autoAlpha: 0,
              scale: 0.76,
              rotation: 18,
              duration: 0.24,
              ease: "power2.in",
            },
            0,
          )
          .to(
            coreGlow,
            {
              autoAlpha: 0,
              scale: 1.35,
              duration: 0.2,
              ease: "power2.in",
            },
            0,
          )
          .to(
            root,
            {
              clipPath: "ellipse(150% 0% at 50% -35%)",
              duration: 0.42,
              ease: "power3.inOut",
              onComplete: () => {
                if (!cancelled) setPhase("hidden");
              },
            },
            0.04,
          );
      }, root);
    });

    return () => {
      cancelled = true;
      context?.revert();
    };
  }, [phase]);

  if (phase === "checking" || phase === "hidden") return null;

  return (
    <div
      ref={rootRef}
      className={`brand-splash curve-swipe brand-splash--${phase}`}
      role="status"
      aria-live="polite"
      aria-label={messageForRoute(pathname)}
    >
      <div className="brand-splash__aura" aria-hidden="true" />

      <div className="brand-splash__stage">
        <svg
          className="brand-splash__orbit"
          viewBox="0 0 780 320"
          fill="none"
          aria-hidden="true"
        >
          <defs>
            <linearGradient
              id="brand-splash-orbit-gradient"
              x1="1280"
              y1="171"
              x2="390"
              y2="160"
              gradientUnits="userSpaceOnUse"
            >
              <stop stopColor="#FFF3C2" />
              <stop offset="0.24" stopColor="#8BE0FF" />
              <stop offset="0.68" stopColor="#296DFF" />
              <stop offset="1" stopColor="#B9EAFF" />
            </linearGradient>
          </defs>

          <path
            className="brand-splash__orbit-trace brand-splash__orbit-trace--one"
            d={WIRE_PATH}
            data-loader-orbit
            vectorEffect="non-scaling-stroke"
          />
          <path
            className="brand-splash__orbit-trace brand-splash__orbit-trace--two"
            d={WIRE_PATH}
            data-loader-orbit
            vectorEffect="non-scaling-stroke"
          />
          <path
            className="brand-splash__orbit-trace brand-splash__orbit-trace--three"
            d={WIRE_PATH}
            data-loader-orbit
            vectorEffect="non-scaling-stroke"
          />
          <path
            className="brand-splash__orbit-path"
            d={WIRE_PATH}
            data-loader-orbit
            data-loader-light-path
            vectorEffect="non-scaling-stroke"
          />
          <path
            className="brand-splash__orbit-runner"
            d={WIRE_PATH}
            data-loader-orbit
            vectorEffect="non-scaling-stroke"
          />
        </svg>

        <span
          className="brand-splash__runner"
          data-loader-runner
          aria-hidden="true"
        >
          <span
            className="brand-splash__runner-core"
            data-loader-light-core
          />
        </span>

        <div className="brand-splash__lockup" aria-label="ArenaRank">
          <span className="brand-splash__word" aria-hidden="true">
            {"ARENA".split("").map((letter, index) => (
              <span
                className="brand-splash__letter"
                data-loader-letter
                key={`${letter}-${index}`}
              >
                {letter}
              </span>
            ))}
          </span>
          <span
            className="brand-splash__brand-emblem"
            data-loader-mark
            aria-hidden="true"
          >
            <img
              className="brand-splash__brand-mark"
              src="/assets/fig/medallion-poster.png"
              alt=""
            />
            <span
              className="brand-splash__brand-core-glow"
              data-loader-core-glow
              style={{ opacity: 0 }}
            />
          </span>
          <span className="brand-splash__word" aria-hidden="true">
            {"RANK".split("").map((letter, index) => (
              <span
                className="brand-splash__letter"
                data-loader-letter
                key={`${letter}-${index}`}
              >
                {letter}
              </span>
            ))}
          </span>
        </div>

        <div className="brand-splash__status" aria-hidden="true">
          <span className="brand-splash__status-line" />
          <span>{messageForRoute(pathname)}</span>
          <span className="brand-splash__status-line" />
        </div>
      </div>
    </div>
  );
}
