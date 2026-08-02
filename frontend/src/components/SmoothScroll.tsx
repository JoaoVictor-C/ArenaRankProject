import {
  useEffect,
  useLayoutEffect,
  useRef,
  type ReactNode,
} from "react";
import { useLocation } from "react-router-dom";
import { loadSmoother } from "../lib/motion";

type SmootherInstance = {
  kill(): void;
  scrollTo(target: number, smooth?: boolean): void;
};

export function SmoothScroll({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const smootherRef = useRef<SmootherInstance | null>(null);
  const refreshRef = useRef<(() => void) | null>(null);

  useLayoutEffect(() => {
    let cancelled = false;
    let media: ReturnType<
      NonNullable<Awaited<ReturnType<typeof loadSmoother>>>["gsap"]["matchMedia"]
    > | null = null;

    void loadSmoother().then((motion) => {
      if (cancelled || !motion) return;

      refreshRef.current = () => motion.ScrollTrigger.refresh();
      media = motion.gsap.matchMedia();
      // Acima do maior limiar de layout estreito do app (o bottom sheet de /winrate
      // vive em `max-width: 1080px`). O #smooth-content é transformado, e transform
      // faz `position: fixed` descendente se comportar como `absolute` — cruzar os
      // dois limiares deixaria o sheet rolando junto com a página.
      media.add("(min-width: 1081px)", () => {
        const smoother = motion.ScrollSmoother.create({
          wrapper: "#smooth-wrapper",
          content: "#smooth-content",
          smooth: 0.8,
          smoothTouch: false,
        });
        smootherRef.current = smoother;

        // O Smoother precisa existir antes de recalcular os triggers das rotas.
        motion.ScrollTrigger.refresh();

        return () => {
          smoother.kill();
          if (smootherRef.current === smoother) smootherRef.current = null;
        };
      });
    });

    return () => {
      cancelled = true;
      media?.revert();
      refreshRef.current = null;
    };
  }, []);

  useEffect(() => {
    const smoother = smootherRef.current;
    if (smoother) smoother.scrollTo(0, false);
    else window.scrollTo(0, 0);

    // O Outlet já cometeu a nova rota; no frame seguinte suas medições e
    // ScrollTriggers entram no mesmo sistema de coordenadas do Smoother.
    const frame = window.requestAnimationFrame(() => refreshRef.current?.());
    return () => window.cancelAnimationFrame(frame);
  }, [pathname]);

  return (
    <div id="smooth-wrapper">
      <div id="smooth-content">
        {/* Scrollers internos de tabelas ficam nativos de propósito: resposta
            direta em dados densos vale mais que uma segunda camada de inércia. */}
        {children}
      </div>
    </div>
  );
}