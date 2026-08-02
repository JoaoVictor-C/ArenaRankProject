import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { Home } from "./Home";

const iconColorsMock = vi.hoisted(() =>
  vi.fn((url?: string | null) =>
    url === "https://cdn.test/main.png"
      ? (["#173f56", "#65c8ef"] as [string, string])
      : null,
  ),
);

const mockApi = vi.hoisted(() => {
  const leaderboard = {
    data: {
      rows: [
        {
          rank: 1,
          name: "Ares",
          handle: "#BR1",
          profileIconUrl: null,
          avatar: { c1: "#d9b25f", c2: "#17130b" },
          tags: [{ icon: "military_tech", label: "TOP 1" }],
          cr: 5241,
          delta7d: 200,
          wins: 300,
          losses: 120,
          winrate: 71.4,
          championIconUrls: ["https://cdn.test/main.png"],
          championsStats: [],
        },
      ],
    },
    loading: false,
    error: null,
  };
  const champions = {
    data: {
      table: [
        {
          rank: 1,
          tier: "S",
          name: "Briar",
          role: "Lutador",
          champion: { c1: "#6f2434", c2: "#1d0b10" },
          championIconUrl: null,
          first: 26.4,
          pickRate: 8.2,
          avgPlace: 3.12,
        },
        {
          rank: 2,
          tier: "A",
          name: "Xin Zhao",
          role: "Lutador",
          champion: { c1: "#345f81", c2: "#101c27" },
          championIconUrl: null,
          first: 24.1,
          pickRate: 7.5,
          avgPlace: 3.3,
        },
      ],
    },
    loading: false,
    error: null,
  };
  const tournaments = {
    data: [
      {
        id: "arena-open",
        title: "Arena Open Brasil",
        tag: "INSCRIÇÕES ABERTAS",
        teams: 16,
        format: "3v3",
        bannerTone: "b3",
        amountLabel: "R$ 1.000",
        whenLabel: "10 de agosto",
      },
    ],
    loading: false,
    error: null,
  };

  return {
    index: 0,
    results: [leaderboard, champions, tournaments],
  };
});

vi.mock("../hooks/useApi", () => ({
  useApi: () => {
    const result = mockApi.results[mockApi.index % mockApi.results.length];
    mockApi.index += 1;
    return result;
  },
}));

vi.mock("../hooks/useIconColors", () => ({
  useIconColors: iconColorsMock,
}));

vi.mock("./homeMotion", () => ({
  useFeatureCardMotion: () => {},
  useHomeMotion: () => {},
}));

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";
const mediaQueryListeners = new Set<(event: MediaQueryListEvent) => void>();
const originalVisibilityState = Object.getOwnPropertyDescriptor(
  document,
  "visibilityState",
);
let reducedMotion = false;
let visibilityState: DocumentVisibilityState = "visible";
let intersectionCallback: IntersectionObserverCallback | null = null;
const intersectionObservers: IntersectionObserver[] = [];
let observedElement: Element | null = null;
const disconnectIntersectionObserver = vi.fn();

function installBrowserMotionMocks(options: { reduced?: boolean } = {}) {
  reducedMotion = options.reduced ?? false;
  intersectionCallback = null;
  intersectionObservers.length = 0;
  observedElement = null;

  const addMediaQueryListener = (
    type: string,
    listener: EventListenerOrEventListenerObject,
  ) => {
    if (type === "change" && typeof listener === "function") {
      mediaQueryListeners.add(listener as (event: MediaQueryListEvent) => void);
    }
  };
  const removeMediaQueryListener = (
    type: string,
    listener: EventListenerOrEventListenerObject,
  ) => {
    if (type === "change" && typeof listener === "function") {
      mediaQueryListeners.delete(listener as (event: MediaQueryListEvent) => void);
    }
  };
  const addLegacyMediaQueryListener: MediaQueryList["addListener"] = (listener) => {
    if (listener) mediaQueryListeners.add(listener);
  };
  const removeLegacyMediaQueryListener: MediaQueryList["removeListener"] = (
    listener,
  ) => {
    if (listener) mediaQueryListeners.delete(listener);
  };

  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string): MediaQueryList => ({
      matches: query === REDUCED_MOTION_QUERY && reducedMotion,
      media: query,
      onchange: null,
      addEventListener: addMediaQueryListener,
      removeEventListener: removeMediaQueryListener,
      addListener: addLegacyMediaQueryListener,
      removeListener: removeLegacyMediaQueryListener,
      dispatchEvent: () => true,
    })),
  );

  class MockIntersectionObserver implements IntersectionObserver {
    readonly root = null;
    readonly rootMargin: string;
    readonly thresholds: readonly number[];

    constructor(
      callback: IntersectionObserverCallback,
      options?: IntersectionObserverInit,
    ) {
      this.rootMargin = options?.rootMargin ?? "0px";
      this.thresholds = Array.isArray(options?.threshold)
        ? options.threshold
        : [options?.threshold ?? 0];
      intersectionCallback = callback;
      intersectionObservers.push(this);
    }

    observe(element: Element) {
      observedElement = element;
    }

    unobserve(element: Element) {
      if (observedElement === element) observedElement = null;
    }

    disconnect() {
      disconnectIntersectionObserver();
      observedElement = null;
    }

    takeRecords() {
      return [];
    }
  }

  vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);
}

function updateIntersection(isIntersecting: boolean) {
  if (!intersectionCallback || intersectionObservers.length === 0 || !observedElement) {
    throw new Error("O Coliseu ainda não está sendo observado.");
  }

  const callback = intersectionCallback;
  const observer = intersectionObservers[intersectionObservers.length - 1];
  const target = observedElement;
  const rect = target.getBoundingClientRect();
  const entry = {
    boundingClientRect: rect,
    intersectionRatio: isIntersecting ? 1 : 0,
    intersectionRect: isIntersecting ? rect : new DOMRectReadOnly(),
    isIntersecting,
    rootBounds: null,
    target,
    time: 0,
  } as IntersectionObserverEntry;

  act(() => callback([entry], observer));
}

function updateReducedMotion(matches: boolean) {
  reducedMotion = matches;
  const event = { matches, media: REDUCED_MOTION_QUERY } as MediaQueryListEvent;
  act(() => mediaQueryListeners.forEach((listener) => listener(event)));
}

function updateVisibility(nextVisibility: DocumentVisibilityState) {
  visibilityState = nextVisibility;
  act(() => document.dispatchEvent(new Event("visibilitychange")));
}

function renderHome() {
  return render(
    <MemoryRouter
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Home />
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  mediaQueryListeners.clear();
  if (originalVisibilityState) {
    Object.defineProperty(document, "visibilityState", originalVisibilityState);
  } else {
    Reflect.deleteProperty(document, "visibilityState");
  }
});
beforeEach(() => {
  vi.clearAllMocks();
  mockApi.index = 0;
  visibilityState = "visible";
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => visibilityState,
  });
  installBrowserMotionMocks();
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
});

describe("Home", () => {
  it("mantém a mídia como primeiro filho direto e fora dos cards", () => {
    renderHome();

    const coliseu = screen.getByRole("region", { name: "Portais do Coliseu" });
    const media = coliseu.querySelector<HTMLElement>(
      "[data-home-portals-media]",
    );

    expect(media?.parentElement).toBe(coliseu);
    expect(coliseu.firstElementChild).toBe(media);
    expect(media?.closest(".home-portals__viewport")).toBeNull();
    expect(media?.closest(".home-portals__track")).toBeNull();
    expect(media?.closest(".home-portal")).toBeNull();
  });

  it("carrega e reproduz o WebM somente quando o Coliseu se aproxima", () => {
    renderHome();

    const coliseu = screen.getByRole("region", { name: "Portais do Coliseu" });
    const media = coliseu.querySelector<HTMLElement>(
      "[data-home-portals-media]",
    );
    const video = media?.querySelector<HTMLVideoElement>(
      "[data-home-portals-video]",
    );

    expect(media?.getAttribute("aria-hidden")).toBe("true");
    expect(video?.querySelector("source")).toBeNull();
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();

    updateIntersection(true);

    const source = video?.querySelector("source");
    expect(video?.autoplay).toBe(true);
    expect(video?.muted).toBe(true);
    expect(video?.loop).toBe(true);
    expect(video?.playsInline).toBe(true);
    expect(video?.preload).toBe("metadata");
    expect(source?.getAttribute("src")).toBe(
      "/assets/card-arena-coliseu.webm",
    );
    expect(source?.getAttribute("type")).toBe("video/webm");
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
  });

  it("não monta nem reproduz o source com redução de movimento", () => {
    installBrowserMotionMocks({ reduced: true });

    renderHome();

    expect(document.querySelector("[data-home-portals-video] source")).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Pausar animação do Coliseu" }),
    ).toBeNull();
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
  });

  it("remove a mídia e pausa quando a preferência muda para movimento reduzido", () => {
    renderHome();
    updateIntersection(true);
    vi.mocked(HTMLMediaElement.prototype.pause).mockClear();

    updateReducedMotion(true);

    expect(document.querySelector("[data-home-portals-video] source")).toBeNull();
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  });

  it.each(["matchMedia", "IntersectionObserver"] as const)(
    "mantém o fallback opaco quando %s não existe",
    (missingApi) => {
      vi.stubGlobal(missingApi, undefined);

      renderHome();

      expect(document.querySelector("[data-home-portals-video] source")).toBeNull();
      expect(
        screen.queryByRole("button", { name: "Pausar animação do Coliseu" }),
      ).toBeNull();
      expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
    },
  );

  it("pausa fora da área observada e volta a reproduzir ao reentrar", () => {
    renderHome();
    updateIntersection(true);
    const video = document.querySelector<HTMLVideoElement>(
      "[data-home-portals-video]",
    );
    vi.mocked(HTMLMediaElement.prototype.pause).mockClear();

    updateIntersection(false);

    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
    expect(video?.autoplay).toBe(false);
    expect(document.querySelector("[data-home-portals-video] source")).toBeNull();

    vi.mocked(HTMLMediaElement.prototype.play).mockClear();
    updateIntersection(true);
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
  });

  it("pausa com a página oculta e retoma quando ela volta a ficar visível", () => {
    renderHome();
    updateIntersection(true);
    const video = document.querySelector<HTMLVideoElement>(
      "[data-home-portals-video]",
    );
    vi.mocked(HTMLMediaElement.prototype.pause).mockClear();

    updateVisibility("hidden");

    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
    expect(video?.autoplay).toBe(false);
    expect(document.querySelector("[data-home-portals-video] source")).toBeTruthy();

    vi.mocked(HTMLMediaElement.prototype.play).mockClear();
    updateVisibility("visible");
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
    expect(video?.autoplay).toBe(true);
  });

  it("permite pausar e retomar a animação por um controle acessível", () => {
    renderHome();
    updateIntersection(true);
    const video = document.querySelector<HTMLVideoElement>(
      "[data-home-portals-video]",
    );
    vi.mocked(HTMLMediaElement.prototype.pause).mockClear();

    fireEvent.click(
      screen.getByRole("button", { name: "Pausar animação do Coliseu" }),
    );

    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
    expect(video?.autoplay).toBe(false);
    const resumeButton = screen.getByRole("button", {
      name: "Retomar animação do Coliseu",
    });

    vi.mocked(HTMLMediaElement.prototype.play).mockClear();
    fireEvent.click(resumeButton);
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
    expect(video?.autoplay).toBe(true);
    expect(
      screen.getByRole("button", { name: "Pausar animação do Coliseu" }),
    ).toBeTruthy();
  });

  it("preserva a abertura existente e conecta os portais públicos", () => {
    renderHome();

    expect(screen.getByLabelText("ARENA").textContent).toBe("ARENA");
    expect(screen.getByLabelText("RANK").textContent).toBe("RANK");
    expect(
      screen.getByPlaceholderText(
        "Busque por campeões, jogadores, augments, etc...",
      ),
    ).toBeTruthy();

    expect(
      screen.getByRole("region", { name: "Portais do Coliseu" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("region", { name: "Diagnóstico do meta" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("region", { name: "Campeonatos da comunidade" }),
    ).toBeTruthy();

    expect(
      screen
        .getByRole("link", { name: /entrar no leaderboard/i })
        .getAttribute("href"),
    ).toBe("/leaderboard");
    expect(
      screen
        .getByRole("link", { name: /abrir sinergias/i })
        .getAttribute("href"),
    ).toBe("/sinergias");
    expect(
      screen
        .getByRole("link", { name: /explorar augments/i })
        .getAttribute("href"),
    ).toBe("/augments");

    const profileEntries = screen.getAllByRole("link", {
      name: /consultar meu perfil/i,
    });
    expect(profileEntries).toHaveLength(2);
    profileEntries.forEach((profileEntry) => {
      expect(profileEntry.getAttribute("href")).toBe("/");
      fireEvent.click(profileEntry);
      expect(document.activeElement).toBe(
        screen.getByPlaceholderText(
          "Busque por campeões, jogadores, augments, etc...",
        ),
      );
    });

    expect(screen.queryByText(/winrate de augment/i)).toBeNull();
  });

  it("usa as cores do campeão principal para compor o card e o CTA", () => {
    renderHome();

    const featureCard = screen.getByTestId("home-feature-card");

    expect(
      featureCard.style.getPropertyValue("--fc-fallback-deep"),
    ).toBe("#173f56");
    expect(
      featureCard.style.getPropertyValue("--fc-fallback-bright"),
    ).toBe("#65c8ef");
    expect(featureCard.querySelectorAll("[data-feature-shape]")).toHaveLength(3);
    expect(featureCard.querySelector("[data-feature-beam]")).toBeTruthy();
    expect(featureCard.querySelector("[data-feature-frame]")).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: /ver tabela completa/i })
        .classList.contains("fc-btn"),
    ).toBe(true);
  });

  it("ancora a etiqueta TOP 1 fora do recorte do card", () => {
    renderHome();

    const featureCard = screen.getByTestId("home-feature-card");
    const topOneLabel = document.querySelector<HTMLElement>(
      ".fig-feature > .fc-top1",
    );

    expect(topOneLabel).toBeTruthy();
    expect(featureCard.contains(topOneLabel)).toBe(false);
  });

  it("mantém uma passagem útil quando não há campeonatos ativos", () => {
    mockApi.results[2] = {
      data: [],
      loading: false,
      error: null,
    };

    renderHome();

    expect(
      screen.getByText("Nenhum campeonato ativo no momento."),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: /acompanhar campeonatos/i })
        .getAttribute("href"),
    ).toBe("/campeonatos");
  });
});
