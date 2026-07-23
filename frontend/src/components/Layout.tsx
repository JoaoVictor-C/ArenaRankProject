/* Shell do site: fundo + header + conteúdo (Outlet) + footer + ajustes.
   Inicia o motor de animação uma vez e reseta o scroll a cada rota. */
import { Suspense, useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Background } from "./Background";
import { Header } from "./Header";
import { Footer } from "./Footer";
import { TweaksPanel } from "./TweaksPanel";
import { ErrorBoundary } from "./ErrorBoundary";
import { StateBlock } from "./StateBlock";
import { initAnimEngine } from "../lib/animEngine";

export function Layout() {
  const { pathname } = useLocation();

  useEffect(() => {
    initAnimEngine();
  }, []);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  return (
    <>
      <Background />
      <Header />
      <main>
        {/* key={pathname}: navegar reseta o boundary, então um erro numa página
            não trava a navegação. O shell (header/footer) sobrevive ao erro. */}
        <ErrorBoundary key={pathname}>
          <Suspense fallback={<StateBlock loading />}>
            <Outlet />
          </Suspense>
        </ErrorBoundary>
      </main>
      <Footer />
      <TweaksPanel />
    </>
  );
}
