import { useRef, useState, type RefObject } from "react";
import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  queryChartParts,
  useDrawCharts,
  useGsapEntrance,
  useGsapInteractions,
  useGsapLoop,
  useGsapMatchDetail,
  useGsapSwap,
  visibleTargets,
} from "./motion";

const gsapMock = vi.hoisted(() => {
  const timeline = {
    from: vi.fn(),
    fromTo: vi.fn(),
    to: vi.fn(),
  };
  timeline.from.mockReturnValue(timeline);
  timeline.fromTo.mockReturnValue(timeline);
  timeline.to.mockReturnValue(timeline);

  return {
    timeline,
    context: vi.fn((callback: () => void) => {
      callback();
      return { revert: vi.fn() };
    }),
    timelineFactory: vi.fn(() => timeline),
    to: vi.fn(() => ({ pause: vi.fn(), resume: vi.fn(), kill: vi.fn() })),
    fromTo: vi.fn(),
    set: vi.fn(),
    registerPlugin: vi.fn(),
  };
});

const drawSvgPluginMock = vi.hoisted(() => ({}));
const splitTextMock = vi.hoisted(() => ({
  construct: vi.fn(),
  revert: vi.fn(),
}));

vi.mock("gsap", () => ({
  gsap: {
    context: gsapMock.context,
    timeline: gsapMock.timelineFactory,
    to: gsapMock.to,
    fromTo: gsapMock.fromTo,
    set: gsapMock.set,
    registerPlugin: gsapMock.registerPlugin,
  },
}));

vi.mock("gsap/ScrollTrigger", () => ({
  ScrollTrigger: {},
}));

vi.mock("gsap/Flip", () => ({
  Flip: {
    getState: vi.fn(),
    from: vi.fn(),
  },
}));

vi.mock("gsap/DrawSVGPlugin", () => ({
  DrawSVGPlugin: drawSvgPluginMock,
}));

vi.mock("gsap/SplitText", () => ({
  SplitText: class SplitText {
    words: Element[];

    constructor(target: Element) {
      splitTextMock.construct(target);
      this.words = [target];
    }

    revert() {
      splitTextMock.revert();
    }
  },
}));

afterEach(() => {
  vi.restoreAllMocks();
  gsapMock.timeline.from.mockClear();
  gsapMock.timeline.from.mockReturnValue(gsapMock.timeline);
  gsapMock.timeline.fromTo.mockClear();
  gsapMock.timeline.fromTo.mockReturnValue(gsapMock.timeline);
  gsapMock.timeline.to.mockClear();
  gsapMock.timeline.to.mockReturnValue(gsapMock.timeline);
  gsapMock.timelineFactory.mockClear();
  gsapMock.to.mockClear();
  gsapMock.fromTo.mockClear();
  splitTextMock.construct.mockClear();
  splitTextMock.revert.mockClear();
  document.body.innerHTML = "";
});

describe("queryChartParts", () => {
  it("selects a chart line rendered with fill none", () => {
    document.body.innerHTML = `
      <svg>
        <path data-area fill="url(#area)" />
        <path data-line fill="none" stroke="#ffcc00" />
        <line data-chart-mark stroke-dasharray="2 3" />
        <circle data-chart-mark />
        <text data-axis>26/06</text>
      </svg>`;

    const svg = document.querySelector("svg") as SVGSVGElement;
    const parts = queryChartParts(svg);

    expect(parts.line?.hasAttribute("data-line")).toBe(true);
    expect(parts.area?.hasAttribute("data-area")).toBe(true);
    expect(parts.marks).toHaveLength(2);
  });
});

describe("visibleTargets", () => {
  it("returns only elements intersecting the viewport", () => {
    document.body.innerHTML = `<div id="root"><i/><i/><i/></div>`;
    const items = Array.from(document.querySelectorAll<HTMLElement>("i"));

    vi.spyOn(items[0], "getBoundingClientRect").mockReturnValue({
      top: 10,
      bottom: 40,
    } as DOMRect);
    vi.spyOn(items[1], "getBoundingClientRect").mockReturnValue({
      top: -80,
      bottom: -10,
    } as DOMRect);
    vi.spyOn(items[2], "getBoundingClientRect").mockReturnValue({
      top: window.innerHeight + 10,
      bottom: window.innerHeight + 40,
    } as DOMRect);

    expect(
      visibleTargets(document.querySelector("#root") as HTMLElement, "i"),
    ).toEqual([items[0]]);
  });
});

function DrawChartsHarness() {
  const scope = useRef<HTMLDivElement>(null);
  useDrawCharts(scope);

  return (
    <div ref={scope}>
      <svg data-draw-duration="2">
        <path data-chart-area fill="url(#gold-area)" />
        <path data-chart-line fill="none" stroke="#ffcc00" />
        <circle data-chart-mark />
      </svg>
      <svg data-draw-duration="1">
        <path data-chart-area fill="url(#blue-area)" />
        <path data-chart-line fill="none" stroke="#5aa9ff" />
        <circle data-chart-mark />
      </svg>
    </div>
  );
}

describe("useDrawCharts", () => {
  it("desenha cada linha com DrawSVG e respeita os dois tempos de comparação", async () => {
    Object.defineProperty(window.SVGElement.prototype, "getTotalLength", {
      configurable: true,
      value: () => 100,
    });

    const view = render(<DrawChartsHarness />);
    const [goldChart, blueChart] = Array.from(
      view.container.querySelectorAll<SVGSVGElement>("svg"),
    );
    const goldLine = goldChart.querySelector("[data-chart-line]");
    const goldArea = goldChart.querySelector("[data-chart-area]");
    const goldMark = goldChart.querySelector("[data-chart-mark]");
    const blueLine = blueChart.querySelector("[data-chart-line]");

    await waitFor(() =>
      expect(gsapMock.timelineFactory).toHaveBeenCalledTimes(2),
    );

    expect(gsapMock.registerPlugin).toHaveBeenCalledWith(
      expect.anything(),
      expect.anything(),
      drawSvgPluginMock,
      expect.anything(),
    );
    expect(gsapMock.timeline.fromTo).toHaveBeenCalledWith(
      goldLine,
      { drawSVG: "0%" },
      expect.objectContaining({ drawSVG: "100%", duration: 2 }),
      0,
    );
    expect(gsapMock.timeline.fromTo).toHaveBeenCalledWith(
      goldArea,
      { opacity: 0 },
      expect.objectContaining({ opacity: 1 }),
      0.9,
    );
    expect(gsapMock.timeline.fromTo).toHaveBeenCalledWith(
      [goldMark],
      { opacity: 0 },
      expect.objectContaining({ opacity: 1 }),
      2,
    );
    expect(gsapMock.timeline.fromTo).toHaveBeenCalledWith(
      blueLine,
      { drawSVG: "0%" },
      expect.objectContaining({ drawSVG: "100%", duration: 1 }),
      0,
    );
  });
});

function MotionHarness({
  swapKey = "initial",
}: {
  swapKey?: string;
}) {
  const scope = useRef<HTMLDivElement>(null);
  useGsapEntrance(scope, {
    steps: [
      {
        selector: ".entrance",
        from: { opacity: 0, y: 18 },
      },
    ],
  });
  useGsapSwap(scope, ".swap", swapKey, { from: { opacity: 0, x: 12 } });
  useGsapLoop(scope, [
    {
      selector: ".loop",
      to: { opacity: 0.4 },
      duration: 1,
      repeat: -1,
      yoyo: true,
    },
  ]);
  useGsapInteractions(scope, [
    {
      trigger: ".trigger",
      target: ".target",
      to: { opacity: 0.8, scale: 1.05, y: -2 },
      rest: { opacity: 0.25, scale: 1, y: 0 },
    },
  ]);

  return (
    <div ref={scope as RefObject<HTMLDivElement>}>
      <div className="entrance" />
      <div className="swap" />
      <button className="trigger" type="button">
        <span className="target" />
      </button>
      <i className="loop" />
    </div>
  );
}

function DynamicLoopHarness() {
  const scope = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(false);
  useGsapLoop(scope, [
    {
      selector: ".late-loop",
      to: { rotation: 360 },
      duration: 0.8,
      repeat: -1,
    },
  ]);

  return (
    <div ref={scope}>
      <button type="button" onClick={() => setLoading(true)}>
        Carregar
      </button>
      {loading && <i className="late-loop" />}
    </div>
  );
}

function MatchDetailHarness() {
  const scope = useRef<HTMLElement>(null);
  const [open, setOpen] = useState(false);
  useGsapMatchDetail(scope, open, open);

  return (
    <article ref={scope}>
      <button type="button" onClick={() => setOpen((value) => !value)}>
        Alternar
      </button>
      <div className="hist-detail">
        <div className="hist-detail-inner">
          <h3 data-match-title>Placar da Arena</h3>
          <section data-match-team>
            <div data-match-player>
              <i data-match-item />
              <i data-match-augment />
            </div>
          </section>
        </div>
      </div>
    </article>
  );
}

describe("GSAP route hooks", () => {
  it("builds entrance and loop timelines from real scoped elements", async () => {
    const view = render(<MotionHarness />);
    const entrance = view.container.querySelector(".entrance");
    const loop = view.container.querySelector(".loop");

    await waitFor(() => expect(gsapMock.timelineFactory).toHaveBeenCalled());

    expect(gsapMock.timeline.fromTo).toHaveBeenCalledWith(
      [entrance],
      { opacity: 0, y: 18 },
      expect.objectContaining({ opacity: 1, y: 0 }),
      undefined,
    );
    expect(gsapMock.to).toHaveBeenCalledWith(
      [loop],
      expect.objectContaining({ opacity: 0.4, repeat: -1, yoyo: true }),
    );
  });

  it("animates the scoped target on pointer and keyboard feedback", async () => {
    const view = render(<MotionHarness />);
    const trigger = view.container.querySelector(".trigger") as HTMLButtonElement;
    const target = view.container.querySelector(".target");

    await waitFor(() => expect(gsapMock.timelineFactory).toHaveBeenCalled());
    gsapMock.to.mockClear();
    fireEvent.pointerOver(trigger);

    expect(gsapMock.to).toHaveBeenCalledWith(
      target,
      expect.objectContaining({ scale: 1.05, y: -2, overwrite: "auto" }),
    );

    gsapMock.to.mockClear();
    fireEvent.focusIn(trigger);
    expect(gsapMock.to).toHaveBeenCalledWith(
      target,
      expect.objectContaining({ scale: 1.05, y: -2, overwrite: "auto" }),
    );

    gsapMock.to.mockClear();
    fireEvent.focusOut(trigger);
    expect(gsapMock.to).toHaveBeenCalledWith(
      target,
      expect.objectContaining({ opacity: 0.25, scale: 1, y: 0 }),
    );
  });

  it("animates a replacement only after its state key changes", async () => {
    const view = render(<MotionHarness swapKey="one" />);
    await waitFor(() => expect(gsapMock.timelineFactory).toHaveBeenCalled());
    gsapMock.fromTo.mockClear();

    view.rerender(<MotionHarness swapKey="two" />);

    await waitFor(() => expect(gsapMock.fromTo).toHaveBeenCalled());
    expect(gsapMock.fromTo).toHaveBeenCalledWith(
      view.container.querySelector(".swap"),
      { opacity: 0, x: 12 },
      expect.objectContaining({ opacity: 1, x: 0, overwrite: "auto" }),
    );
  });

  it("starts a loop for a target mounted after the hook", async () => {
    const view = render(<DynamicLoopHarness />);
    await waitFor(() => expect(gsapMock.context).toHaveBeenCalled());
    gsapMock.to.mockClear();

    fireEvent.click(view.getByRole("button", { name: "Carregar" }));

    const lateLoop = await view.findByText("", { selector: ".late-loop" });
    await waitFor(() =>
      expect(gsapMock.to).toHaveBeenCalledWith(
        [lateLoop],
        expect.objectContaining({ rotation: 360, repeat: -1 }),
      ),
    );
  });

  it("opens the match detail and reveals its hierarchy with SplitText", async () => {
    const view = render(<MatchDetailHarness />);
    const panel = view.container.querySelector(".hist-detail");

    fireEvent.click(view.getByRole("button", { name: "Alternar" }));

    await waitFor(() =>
      expect(gsapMock.fromTo).toHaveBeenCalledWith(
        panel,
        expect.objectContaining({ height: 0 }),
        expect.objectContaining({ height: "auto" }),
      ),
    );
    expect(splitTextMock.construct).toHaveBeenCalledWith(
      view.container.querySelector("[data-match-title]"),
    );
    expect(gsapMock.timeline.from).toHaveBeenCalled();
  });
});
