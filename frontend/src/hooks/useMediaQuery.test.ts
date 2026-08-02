/* useMediaQuery — o gate do bottom sheet do /winrate (≤1080px).
   jsdom não tem matchMedia: mock com controle manual do estado + listeners. */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useMediaQuery } from "./useMediaQuery";

type Listener = (e: { matches: boolean }) => void;

function installMatchMedia(initial: boolean) {
  const listeners = new Set<Listener>();
  let matches = initial;
  const mql = {
    get matches() {
      return matches;
    },
    media: "",
    addEventListener: (_: string, cb: Listener) => listeners.add(cb),
    removeEventListener: (_: string, cb: Listener) => listeners.delete(cb),
  };
  vi.stubGlobal("matchMedia", () => mql);
  return {
    set(next: boolean) {
      matches = next;
      listeners.forEach((cb) => cb({ matches: next }));
    },
    listenerCount: () => listeners.size,
  };
}

describe("useMediaQuery", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("lê o estado inicial da media query", () => {
    installMatchMedia(true);
    const { result } = renderHook(() => useMediaQuery("(max-width: 1080px)"));
    expect(result.current).toBe(true);
  });

  it("reage à mudança da media query (ex.: rotação do aparelho)", () => {
    const media = installMatchMedia(false);
    const { result } = renderHook(() => useMediaQuery("(max-width: 1080px)"));
    expect(result.current).toBe(false);
    act(() => media.set(true));
    expect(result.current).toBe(true);
    act(() => media.set(false));
    expect(result.current).toBe(false);
  });

  it("remove o listener no unmount", () => {
    const media = installMatchMedia(false);
    const { unmount } = renderHook(() => useMediaQuery("(max-width: 1080px)"));
    expect(media.listenerCount()).toBe(1);
    unmount();
    expect(media.listenerCount()).toBe(0);
  });
});
