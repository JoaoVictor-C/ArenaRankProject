import { useLayoutEffect, useRef } from "react";
import {
  cleanup,
  fireEvent,
  render,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  dockInfluence,
  useAugmentsHorizontalGallery,
} from "./augmentGalleryMotion";

const motionMock = vi.hoisted(() => ({
  contextRevert: vi.fn(),
  quickTo: vi.fn((...args: [unknown, string, unknown]) => {
    void args;
    return vi.fn();
  }),
  set: vi.fn(),
  to: vi.fn(),
}));
const mediaListeners = new Set<(event: MediaQueryListEvent) => void>();

vi.mock("../lib/motion", () => ({
  loadMotion: async () => ({
    gsap: {
      context: (run: () => void) => {
        run();
        return { revert: motionMock.contextRevert };
      },
      quickTo: motionMock.quickTo,
      set: motionMock.set,
      to: motionMock.to,
    },
  }),
}));

function GalleryHarness() {
  const rootRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const rows = Array.from(
      rootRef.current?.querySelectorAll<HTMLElement>(
        "[data-augment-gallery-row]",
      ) ?? [],
    );
    rows.forEach((row) => {
      Object.defineProperties(row, {
        clientWidth: { configurable: true, value: 800 },
        scrollWidth: { configurable: true, value: 2400 },
      });
      row.scrollLeft = 480;
    });
  }, []);

  useAugmentsHorizontalGallery(rootRef, "all|4");

  return (
    <div ref={rootRef}>
      {["prismatic", "gold"].map((rarity) => (
        <section className="augment-rarity-section" key={rarity}>
          <button
            type="button"
            data-augment-scroll="prev"
            aria-label={`Voltar ${rarity}`}
          />
          <button
            type="button"
            data-augment-scroll="next"
            aria-label={`Avançar ${rarity}`}
          />
          <div data-augment-gallery-row>
            <article data-augment-dock-item />
            <article data-augment-dock-item />
          </div>
        </section>
      ))}
    </div>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mediaListeners.clear();
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: !query.includes("prefers-reduced-motion: reduce"),
      media: query,
      onchange: null,
      addEventListener: (
        _type: string,
        listener: (event: MediaQueryListEvent) => void,
      ) => mediaListeners.add(listener),
      removeEventListener: (
        _type: string,
        listener: (event: MediaQueryListEvent) => void,
      ) => mediaListeners.delete(listener),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("dockInfluence", () => {
  it("entrega força total no centro e zera fora do alcance horizontal", () => {
    expect(dockInfluence(100, 100, 280)).toBe(1);
    expect(dockInfluence(380, 100, 280)).toBe(0);
    expect(dockInfluence(420, 100, 280)).toBe(0);
  });

  it("reduz a resposta suavemente para os vizinhos do cursor", () => {
    expect(dockInfluence(240, 100, 280)).toBeCloseTo(Math.SQRT1_2);
    expect(dockInfluence(100, 240, 280)).toBeCloseTo(Math.SQRT1_2);
    expect(dockInfluence(100, 100, 0)).toBe(0);
  });
});

describe("useAugmentsHorizontalGallery", () => {
  it("mantém cada raridade em um trilho independente", async () => {
    const { container } = render(<GalleryHarness />);
    const root = container.firstElementChild as HTMLElement;

    await waitFor(() => {
      expect(root.classList.contains("has-augment-shelves")).toBe(true);
    });

    const rows = container.querySelectorAll("[data-augment-gallery-row]");
    expect(rows).toHaveLength(2);
    expect((rows[0] as HTMLElement).scrollLeft).toBe(0);
    expect((rows[1] as HTMLElement).scrollLeft).toBe(0);
    expect(container.querySelector(".augment-gallery-track")).toBeNull();

    const nextButtons = container.querySelectorAll(
      "[data-augment-scroll='next']",
    );
    expect(nextButtons).toHaveLength(2);
    expect((nextButtons[0] as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(nextButtons[0]);

    await waitFor(() => {
      expect(motionMock.to).toHaveBeenCalledWith(
        rows[0],
        expect.objectContaining({
          scrollLeft: expect.any(Number),
        }),
      );
    });
    expect(motionMock.to).toHaveBeenCalledTimes(1);
    expect(motionMock.to.mock.calls[0][0]).toBe(rows[0]);
    expect(motionMock.to.mock.calls[0][0]).not.toBe(rows[1]);
  });

  it("usa eixos de escala individuais e limpa todo estado", async () => {
    const { container, unmount } = render(<GalleryHarness />);
    const root = container.firstElementChild as HTMLElement;

    await waitFor(() => {
      const properties = motionMock.quickTo.mock.calls.map(
        (call) => call[1],
      );
      expect(properties).toContain("scaleX");
      expect(properties).toContain("scaleY");
      expect(properties).not.toContain("scale");
    });

    unmount();

    expect(root.classList.contains("has-augment-shelves")).toBe(false);
    expect(motionMock.contextRevert).toHaveBeenCalledOnce();

    mediaListeners.forEach((listener) =>
      listener({ matches: true } as MediaQueryListEvent),
    );
    expect(root.classList.contains("has-augment-shelves")).toBe(false);
  });
});
