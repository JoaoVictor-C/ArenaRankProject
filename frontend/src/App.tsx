import { lazy } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Layout } from "./components/Layout";

// Cada página é carregada sob demanda (code-splitting): o bundle inicial fica só
// com o shell + o roteador, e cada rota chega em seu próprio chunk. O <Suspense>
// (fallback de carregamento) e o <ErrorBoundary> ficam no Layout, em volta do
// <Outlet/>, então o shell (header/footer) sobrevive a um erro/carregamento.
const Home = lazy(() => import("./routes/Home").then((m) => ({ default: m.Home })));
const Leaderboard = lazy(() =>
  import("./routes/Leaderboard").then((m) => ({ default: m.Leaderboard })),
);
const Campeonatos = lazy(() =>
  import("./routes/Campeonatos").then((m) => ({ default: m.Campeonatos })),
);
const Campeonatos2 = lazy(() =>
  import("./routes/Campeonatos2").then((m) => ({ default: m.Campeonatos2 })),
);
const Winrate = lazy(() => import("./routes/Winrate").then((m) => ({ default: m.Winrate })));
const Campeao = lazy(() => import("./routes/Campeao").then((m) => ({ default: m.Campeao })));
const Augments = lazy(() => import("./routes/Augments").then((m) => ({ default: m.Augments })));
const Sinergias = lazy(() => import("./routes/Sinergias").then((m) => ({ default: m.Sinergias })));
const ChampionOtps = lazy(() =>
  import("./routes/ChampionOtps").then((m) => ({ default: m.ChampionOtps })),
);
const Perfil = lazy(() => import("./routes/Perfil").then((m) => ({ default: m.Perfil })));
const Lens = import.meta.env.DEV
  ? lazy(() => import("./routes/Lens").then((m) => ({ default: m.Lens })))
  : null;
const Partida = lazy(() => import("./routes/Partida").then((m) => ({ default: m.Partida })));
const Sistema = lazy(() => import("./routes/Sistema").then((m) => ({ default: m.Sistema })));
const Duo = lazy(() => import("./routes/Duo").then((m) => ({ default: m.Duo })));

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Home />} />
          <Route path="/leaderboard" element={<Leaderboard />} />
          <Route path="/campeonatos" element={<Campeonatos />} />
          <Route path="/campeonatos/:id" element={<Campeonatos />} />
          <Route path="/campeonatos2" element={<Campeonatos2 />} />
          <Route path="/campeonatos2/:id" element={<Campeonatos2 />} />
          <Route path="/campeoes" element={<Winrate />} />
          <Route path="/campeao/:championId" element={<Campeao />} />
          <Route path="/campeao/:championId/otps" element={<ChampionOtps />} />
          <Route path="/augments" element={<Augments />} />
          <Route path="/sinergias" element={<Sinergias />} />
          {Lens && <Route path="/perfil/:riotId/lens" element={<Lens />} />}
          <Route path="/perfil/:riotId" element={<Perfil />} />
          {Lens && <Route path="/:riotId/lens" element={<Lens />} />}
          <Route path="/partida/:matchId" element={<Partida />} />
          <Route path="/duo" element={<Duo />} />
          <Route path="/sistema" element={<Sistema />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
