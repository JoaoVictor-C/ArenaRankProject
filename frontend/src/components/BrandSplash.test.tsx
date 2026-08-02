import { StrictMode, useState } from "react";
import { useQuery, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BrandSplash } from "./BrandSplash";
import { StateBlock } from "./StateBlock";

vi.mock("../lib/motion", () => ({
  prefersReducedMotion: vi.fn(() => false),
}));

vi.mock("./brandSplashMotion", () => ({
  loadBrandSplashMotion: vi.fn(async () => null),
}));

type Payload = { rows: number[] };

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });

  return { promise, reject, resolve };
}

function QueryProbe({
  initialData,
  queryFn,
}: {
  initialData?: Payload;
  queryFn: () => Promise<Payload>;
}) {
  const query = useQuery({
    queryKey: ["brand-splash-probe"],
    queryFn,
    initialData,
    initialDataUpdatedAt: initialData ? 0 : undefined,
    retry: false,
    staleTime: 0,
  });

  return (
    <button type="button" onClick={() => void query.refetch()}>
      Atualizar dados
    </button>
  );
}

function renderSplash({
  initialData,
  queryFn,
  strict = false,
}: {
  initialData?: Payload;
  queryFn: () => Promise<Payload>;
  strict?: boolean;
}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { gcTime: 0, retry: false },
    },
  });

  const tree = (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={["/"]}
        future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
      >
        <QueryProbe initialData={initialData} queryFn={queryFn} />
        <BrandSplash />
      </MemoryRouter>
    </QueryClientProvider>
  );

  return render(strict ? <StrictMode>{tree}</StrictMode> : tree);
}

function NavigationProbe({
  requests,
}: {
  requests: Record<string, Promise<Payload>>;
}) {
  const { pathname } = useLocation();
  const navigate = useNavigate();

  useQuery({
    queryKey: ["brand-splash-navigation", pathname],
    queryFn: () => requests[pathname],
    retry: false,
    staleTime: 0,
  });

  return (
    <button type="button" onClick={() => navigate("/leaderboard")}>
      Abrir leaderboard
    </button>
  );
}

function renderNavigationSplash(requests: Record<string, Promise<Payload>>) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { gcTime: 60_000, retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={["/"]}
        future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
      >
        <NavigationProbe requests={requests} />
        <BrandSplash />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function renderObserverGapSplash(queryFn: () => Promise<Payload>) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { gcTime: 60_000, retry: false } },
  });

  const tree = (showProbe: boolean) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={["/"]}
        future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
      >
        {showProbe ? (
          <QueryProbe key="probe" queryFn={queryFn} />
        ) : (
          <span key="probe" />
        )}
        <BrandSplash key="splash" />
      </MemoryRouter>
    </QueryClientProvider>
  );

  const view = render(tree(true));
  return {
    ...view,
    rerenderProbe(showProbe: boolean) {
      view.rerender(tree(showProbe));
    },
  };
}

function SiteLoadingProbe() {
  const [loading, setLoading] = useState(true);

  return (
    <>
      <button type="button" onClick={() => setLoading(false)}>
        Finalizar carregamento
      </button>
      <main>{loading ? <StateBlock loading /> : <span>Página pronta</span>}</main>
    </>
  );
}

function renderSiteLoadingSplash() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { gcTime: 0, retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={["/"]}
        future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
      >
        <SiteLoadingProbe />
        <BrandSplash />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("BrandSplash", () => {
  it("cobre o loading do site antes de a primeira query ser montada", async () => {
    renderSiteLoadingSplash();

    expect(
      await screen.findByRole("status", { name: "Carregando a Arena" }),
    ).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", { name: "Finalizar carregamento" }),
    );

    await waitFor(() => {
      expect(
        screen.queryByRole("status", { name: "Carregando a Arena" }),
      ).toBeNull();
    });
  });

  it("permanece visível enquanto a query ativa revalida dados semeados", async () => {
    const request = deferred<Payload>();
    renderSplash({
      initialData: { rows: [1] },
      queryFn: () => request.promise,
    });

    const splash = await screen.findByRole("status", {
      name: "Carregando a Arena",
    });

    expect(splash.querySelectorAll("[data-loader-orbit]")).toHaveLength(5);
    expect(splash.querySelector("[data-loader-runner]")).toBeTruthy();
    expect(splash.querySelector("[data-loader-mark]")).toBeTruthy();
    expect(splash.querySelectorAll("[data-loader-letter]")).toHaveLength(9);

    await act(async () => {
      request.resolve({ rows: [1, 2] });
    });

    await waitFor(() => {
      expect(screen.queryByRole("status")).toBeNull();
    });
  });

  it("inicia o fio fora da borda direita e prepara a ignição do medalhão", async () => {
    const request = deferred<Payload>();
    renderSplash({ queryFn: () => request.promise });

    const splash = await screen.findByRole("status", {
      name: "Carregando a Arena",
    });
    const orbit = splash.querySelector<SVGSVGElement>(
      ".brand-splash__orbit",
    );
    const wire = splash.querySelector<SVGPathElement>(
      ".brand-splash__orbit-path",
    );
    const viewBoxWidth = Number(orbit?.getAttribute("viewBox")?.split(" ")[2]);
    const startX = Number(wire?.getAttribute("d")?.match(/^M(-?\d+(?:\.\d+)?)/)?.[1]);

    expect(startX).toBeGreaterThan(viewBoxWidth);
    expect(splash.querySelector("[data-loader-light-path]")).toBeTruthy();
    expect(splash.querySelector("[data-loader-core-glow]")).toBeTruthy();
    expect(
      splash.querySelector("[data-loader-runner]")?.querySelector("img"),
    ).toBeNull();
  });

  it("mantém o halo apagado até o raio alcançar o medalhão", async () => {
    const request = deferred<Payload>();
    renderSplash({ queryFn: () => request.promise });

    const splash = await screen.findByRole("status", {
      name: "Carregando a Arena",
    });
    const coreGlow = splash.querySelector<HTMLElement>(
      "[data-loader-core-glow]",
    );

    expect(coreGlow?.style.opacity).toBe("0");
  });

  it("não conclui durante o remount de observers do StrictMode", async () => {
    const request = deferred<Payload>();
    renderSplash({ queryFn: () => request.promise, strict: true });

    expect(
      await screen.findByRole("status", { name: "Carregando a Arena" }),
    ).toBeTruthy();

    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.queryByRole("status")).toBeTruthy();

    await act(async () => {
      request.resolve({ rows: [1] });
    });
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
  });

  it("ignora uma lacuna transitória entre remoção e remount do observer", async () => {
    const request = deferred<Payload>();
    const view = renderObserverGapSplash(() => request.promise);

    expect(await screen.findByRole("status")).toBeTruthy();

    view.rerenderProbe(false);
    view.rerenderProbe(true);

    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.queryByRole("status")).toBeTruthy();

    await act(async () => {
      request.resolve({ rows: [1] });
    });
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
  });

  it("encerra o loader quando a primeira request falha", async () => {
    const request = deferred<Payload>();
    renderSplash({ queryFn: () => request.promise });

    expect(await screen.findByRole("status")).toBeTruthy();

    await act(async () => {
      request.reject(new Error("API indisponível"));
    });

    await waitFor(() => {
      expect(screen.queryByRole("status")).toBeNull();
    });
  });

  it("não reabre na mesma visita durante um refetch tardio", async () => {
    const firstRequest = deferred<Payload>();
    const secondRequest = deferred<Payload>();
    const queryFn = vi
      .fn<() => Promise<Payload>>()
      .mockReturnValueOnce(firstRequest.promise)
      .mockReturnValueOnce(secondRequest.promise);

    renderSplash({ queryFn });
    expect(await screen.findByRole("status")).toBeTruthy();

    await act(async () => {
      firstRequest.resolve({ rows: [1] });
    });
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "Atualizar dados" }));
    await waitFor(() => expect(queryFn).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("status")).toBeNull();

    await act(async () => {
      secondRequest.resolve({ rows: [2] });
    });
  });

  it("rearma o loader quando o pathname muda", async () => {
    const homeRequest = deferred<Payload>();
    const leaderboardRequest = deferred<Payload>();
    renderNavigationSplash({
      "/": homeRequest.promise,
      "/leaderboard": leaderboardRequest.promise,
    });

    expect(
      await screen.findByRole("status", { name: "Carregando a Arena" }),
    ).toBeTruthy();
    await act(async () => {
      homeRequest.resolve({ rows: [1] });
    });
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());

    fireEvent.click(
      screen.getByRole("button", { name: "Abrir leaderboard" }),
    );

    expect(
      await screen.findByRole("status", {
        name: "Carregando tabela do Arena",
      }),
    ).toBeTruthy();

    await act(async () => {
      leaderboardRequest.resolve({ rows: [2] });
    });
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
  });
});
