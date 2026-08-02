/* Shell do site: só header + conteúdo + footer participam do scroll;
   elementos fixed ficam fora do wrapper transformado. */
import { Suspense, useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Background } from "./Background";
import { BrandSplash } from "./BrandSplash";
import { Header } from "./Header";
import { Footer } from "./Footer";
import { SmoothScroll } from "./SmoothScroll";
import { TweaksPanel } from "./TweaksPanel";
import { ErrorBoundary } from "./ErrorBoundary";
import { StateBlock } from "./StateBlock";
import { initAnimEngine } from "../lib/animEngine";

export function Layout() {
  const { pathname } = useLocation();

  useEffect(() => {
    initAnimEngine();
  }, []);

  return (
    <>
      <Background />
      <BrandSplash />
      <SmoothScroll>
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
      </SmoothScroll>
      <TweaksPanel />
    </>
  );
}
