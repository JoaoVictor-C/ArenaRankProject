import { useRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";

import { useFeatureCardMotion, useHomeMotion } from "./homeMotion";

const motionMock = vi.hoisted(() => {
  const createTimeline = () => {
    const timeline = {
      addLabel: vi.fn(),
      from: vi.fn(),
      fromTo: vi.fn(),
      kill: vi.fn(),
      pause: vi.fn(),
      play: vi.fn(),
      to: vi.fn(),
    };
    timeline.addLabel.mockReturnValue(timeline);
    timeline.from.mockReturnValue(timeline);
    timeline.fromTo.mockImplementation((targets, fromVars, toVars) => {
      const elements = Array.isArray(targets) ? targets : [targets];
      if (toVars?.immediateRender !== false) {
        elements.forEach((target) => {
          if (!(target instanceof HTMLElement)) return;
          if (fromVars?.scale !== undefined) {
            target.style.transform = `scale(${fromVars.scale})`;
          } else if (fromVars?.y !== undefined) {
            target.style.transform = `translateY(${fromVars.y}px)`;
          }
          if (fromVars?.clipPath) target.style.clipPath = fromVars.clipPath;
          if (fromVars?.autoAlpha !== undefined) {
            target.style.opacity = String(fromVars.autoAlpha);
            target.style.visibility = fromVars.autoAlpha === 0 ? "hidden" : "visible";
          }
        });
      }
      return timeline;
    });
    timeline.to.mockReturnValue(timeline);
    return timeline;
  };

  const timelines: Array<{
    options: Record<string, unknown> | undefined;
    timeline: ReturnType<typeof createTimeline>;
  }> = [];
  const timelineFactory = vi.fn((options?: Record<string, unknown>) => {
    const timeline = createTimeline();
    timelines.push({ options, timeline });
    return timeline;
  });

  const mediaCleanups: Array<() => void> = [];
  const media = {
    add: vi.fn(
      (
        _query: string,
        callback: () => void | (() => void),
      ) => {
        const capturedStyles = Array.from(
          document.querySelectorAll<HTMLElement>(
            "[data-feature-shape], [data-feature-beam], [data-feature-frame], .fc-btn",
          ),
        ).map((element) => ({
          element,
          style: element.getAttribute("style"),
        }));
        const cleanupCallback = callback();
        mediaCleanups.push(() => {
          cleanupCallback?.();
          capturedStyles.forEach(({ element, style }) => {
            if (style === null) element.removeAttribute("style");
            else element.setAttribute("style", style);
          });
        });
      },
    ),
    revert: vi.fn(() => {
      mediaCleanups.splice(0).forEach((cleanupCallback) => cleanupCallback());
    }),
  };

  const split = {
    construct: vi.fn(),
    revert: vi.fn(),
  };

  const contextRevert = vi.fn();
  const context = vi.fn((callback: () => void) => {
    callback();
    return { revert: contextRevert };
  });
  const quickSetter = vi.fn();
  const triggerKill = vi.fn();

  return {
    context,
    contextRevert,
    fromTo: vi.fn(),
    media,
    mediaCleanups,
    motionEnabled: true,
    quickSetter,
    quickTo: vi.fn(() => quickSetter),
    refresh: vi.fn(),
    set: vi.fn(),
    split,
    timelineFactory,
    timelines,
    to: vi.fn(() => ({ kill: vi.fn() })),
    triggerCreate: vi.fn((options: Record<string, unknown>) => {
      void options;
      return { kill: triggerKill };
    }),
    triggerKill,
  };
});

vi.mock("../lib/motion", () => ({
  loadMotion: async () =>
    motionMock.motionEnabled
      ? {
          gsap: {
            context: motionMock.context,
            fromTo: motionMock.fromTo,
            matchMedia: () => motionMock.media,
            quickTo: motionMock.quickTo,
            set: motionMock.set,
            timeline: motionMock.timelineFactory,
            to: motionMock.to,
          },
          ScrollTrigger: {
            create: motionMock.triggerCreate,
            refresh: motionMock.refresh,
          },
          SplitText: class SplitText {
            lines: Element[];
            words: Element[];

            constructor(target: Element, vars: Record<string, unknown>) {
              motionMock.split.construct(target, vars);
              this.lines = [target];
              this.words = [target];
            }

            revert() {
              motionMock.split.revert();
            }
          },
        }
      : null,
}));

function FeatureHarness() {
  const scope = useRef<HTMLDivElement>(null);
  useFeatureCardMotion(scope, ["#173f56", "#65c8ef"]);

  return (
    <div ref={scope} data-feature-card>
      <div className="fc-bg" />
      <div data-feature-energy>
        <span className="fc-energy__field">
          <i data-feature-shape />
          <i data-feature-shape />
          <i data-feature-shape />
        </span>
        <i data-feature-beam />
        <i data-feature-frame />
      </div>
      <a className="fc-btn" href="/leaderboard">VER TABELA COMPLETA</a>
    </div>
  );
}

function Harness() {
  const scope = useRef<HTMLElement>(null);
  useHomeMotion(scope, []);

  return (
    <main ref={scope}>
      <section data-home-feature />
      <h2 data-home-manifesto>O Arena agora tem um placar.</h2>
      <section className="home-portals" data-home-portals>
        <div className="home-portals__viewport">
          <div data-home-portal-track>
            <article data-home-portal />
          </div>
        </div>
      </section>
      <section className="home-meta">
        <svg>
          <path data-home-meta-path />
        </svg>
      </section>
    </main>
  );
}

beforeEach(() => {
  motionMock.motionEnabled = true;
  motionMock.mediaCleanups.length = 0;
  motionMock.timelines.length = 0;
  Object.defineProperty(HTMLElement.prototype, "getBoundingClientRect", {
    configurable: true,
    value() {
      return {
        bottom: 100,
        height: 100,
        left: 0,
        right: 200,
        top: 0,
        width: 200,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      };
    },
  });
  Object.defineProperty(HTMLElement.prototype, "scrollWidth", {
    configurable: true,
    get() {
      return this.hasAttribute("data-home-portal-track") ? 1800 : 900;
    },
  });
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get() {
      return this.classList.contains("home-portals__viewport") ? 900 : 800;
    },
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("useHomeMotion", () => {
  it("orquestra manifesto, desenho do meta e travessia horizontal", async () => {
    const view = render(<Harness />);

    await waitFor(() => expect(motionMock.context).toHaveBeenCalled());

    expect(motionMock.media.add).toHaveBeenCalledWith(
      "(min-width: 1081px) and (prefers-reduced-motion: no-preference)",
      expect.any(Function),
    );
    expect(motionMock.split.construct).toHaveBeenCalledWith(
      view.container.querySelector("[data-home-manifesto]"),
      expect.objectContaining({ type: "lines,words", mask: "lines" }),
    );
    expect(motionMock.fromTo).toHaveBeenCalledWith(
      [view.container.querySelector("[data-home-meta-path]")],
      { drawSVG: "0%" },
      expect.objectContaining({ drawSVG: "100%" }),
    );
    const stage = view.container.querySelector("[data-home-portals]");
    const viewport = view.container.querySelector(".home-portals__viewport");
    const track = view.container.querySelector("[data-home-portal-track]");

    expect(motionMock.to).toHaveBeenCalledWith(
      track,
      expect.objectContaining({
        ease: "none",
        scrollTrigger: expect.objectContaining({
          trigger: viewport,
          start: "center center",
          pin: stage,
          scrub: 0.65,
          invalidateOnRefresh: true,
        }),
      }),
    );
  });

  it("reverte SplitText, media queries e contexto ao desmontar", async () => {
    const view = render(<Harness />);

    await waitFor(() => expect(motionMock.split.construct).toHaveBeenCalled());
    view.unmount();

    expect(motionMock.split.revert).toHaveBeenCalled();
    expect(motionMock.media.revert).toHaveBeenCalled();
    expect(motionMock.contextRevert).toHaveBeenCalled();
  });
});

describe("useFeatureCardMotion", () => {
  it("coreografa a troca de paleta e a entrada das camadas", async () => {
    const view = render(<FeatureHarness />);
    const card = view.container.querySelector<HTMLElement>("[data-feature-card]");
    const shapes = Array.from(
      view.container.querySelectorAll<HTMLElement>("[data-feature-shape]"),
    );

    await waitFor(() => expect(motionMock.context).toHaveBeenCalledTimes(2));

    expect(motionMock.fromTo).toHaveBeenCalledWith(
      card,
      {
        "--fc-deep": "#173f56",
        "--fc-bright": "#65c8ef",
      },
      expect.objectContaining({
        "--fc-deep": "#173f56",
        "--fc-bright": "#65c8ef",
        duration: 0.42,
      }),
    );

    const intro = motionMock.timelines.find(
      ({ options }) =>
        (options?.defaults as { ease?: string } | undefined)?.ease ===
        "power3.out",
    );
    expect(intro).toBeTruthy();
    expect(intro?.timeline.fromTo).toHaveBeenCalledWith(
      shapes,
      { autoAlpha: 0, scale: 0.78 },
      expect.objectContaining({ duration: 0.7, stagger: 0.06 }),
      "energy",
    );
  });

  it("pausa o repouso vivo fora da tela e encerra seus recursos", async () => {
    const view = render(<FeatureHarness />);

    await waitFor(() => expect(motionMock.triggerCreate).toHaveBeenCalled());

    const ambient = motionMock.timelines.find(
      ({ options }) => options?.repeat === -1,
    );
    const triggerOptions = motionMock.triggerCreate.mock.calls[0][0] as {
      onEnterBack(): void;
      onLeave(): void;
    };

    expect(ambient).toBeTruthy();
    triggerOptions.onLeave();
    expect(ambient?.timeline.pause).toHaveBeenCalled();
    triggerOptions.onEnterBack();
    expect(ambient?.timeline.play).toHaveBeenCalled();

    view.unmount();

    expect(motionMock.triggerKill).toHaveBeenCalled();
    expect(motionMock.media.revert).toHaveBeenCalled();
    expect(motionMock.contextRevert).toHaveBeenCalled();
  });

  it("responde ao ponteiro com quickTo e remove os listeners ao desmontar", async () => {
    const view = render(<FeatureHarness />);
    const card = view.container.querySelector<HTMLElement>("[data-feature-card]")!;
    const field = view.container.querySelector<HTMLElement>(".fc-energy__field");

    await waitFor(() => expect(motionMock.quickTo).toHaveBeenCalled());

    expect(motionMock.quickTo).toHaveBeenCalledWith(
      field,
      "x",
      expect.objectContaining({ duration: 0.42, ease: "power3.out" }),
    );

    fireEvent.pointerEnter(card, { clientX: 100, clientY: 50 });
    fireEvent.pointerMove(card, { clientX: 200, clientY: 100 });
    expect(motionMock.quickSetter).toHaveBeenCalled();

    view.unmount();
    const callsAfterUnmount = motionMock.quickSetter.mock.calls.length;
    fireEvent.pointerMove(card, { clientX: 0, clientY: 0 });
    expect(motionMock.quickSetter).toHaveBeenCalledTimes(callsAfterUnmount);
  });

  it("preserva o estado final quando a media query desktop deixa de corresponder", async () => {
    const view = render(<FeatureHarness />);
    const animatedLayers = Array.from(
      view.container.querySelectorAll<HTMLElement>(
        "[data-feature-shape], [data-feature-beam], [data-feature-frame], .fc-btn",
      ),
    );

    await waitFor(() => expect(motionMock.media.add).toHaveBeenCalledTimes(2));
    animatedLayers.forEach((layer) => layer.removeAttribute("style"));

    motionMock.media.revert();

    expect(animatedLayers.map((layer) => layer.getAttribute("style"))).toEqual(
      [null, null, null, null, null, null],
    );
  });

  it("mantém o estado estático quando motion está desabilitado", async () => {
    motionMock.motionEnabled = false;
    const view = render(<FeatureHarness />);

    await Promise.resolve();

    expect(motionMock.context).not.toHaveBeenCalled();
    expect(
      view.container.querySelectorAll("[data-feature-shape]"),
    ).toHaveLength(3);
    expect(
      view.container.querySelector("[data-feature-card]")?.getAttribute("style"),
    ).toBeNull();
  });
});
