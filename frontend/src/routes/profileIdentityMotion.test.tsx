import { useRef } from "react";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { nf } from "../lib/format";
import { useGsapProfilePdl } from "./profileIdentityMotion";

const motionMocks = vi.hoisted(() => ({
  counter: null as { value: number } | null,
  tweenVars: null as {
    duration: number;
    ease: string;
    snap: { value: number };
    onUpdate: () => void;
  } | null,
  revert: vi.fn(),
  to: vi.fn(),
  loadMotion: vi.fn(),
  reduced: false,
}));

vi.mock("../lib/motion", () => ({
  loadMotion: motionMocks.loadMotion,
  prefersReducedMotion: () => motionMocks.reduced,
}));

function Harness({ value, identity = "ArenaLab#MOCK" }: {
  value: number;
  identity?: string;
}) {
  const scopeRef = useRef<HTMLDivElement>(null);
  useGsapProfilePdl(scopeRef, value, identity);

  return (
    <div ref={scopeRef}>
      <span
        aria-label={`${nf(value)} PDL`}
        aria-live="off"
        data-profile-pdl
      >
        {nf(value)}
      </span>
    </div>
  );
}

beforeEach(() => {
  motionMocks.counter = null;
  motionMocks.tweenVars = null;
  motionMocks.revert.mockReset();
  motionMocks.reduced = false;
  motionMocks.loadMotion.mockReset();
  motionMocks.loadMotion.mockResolvedValue({
    gsap: {
      context: (callback: () => void) => {
        callback();
        return { revert: motionMocks.revert };
      },
      to: motionMocks.to,
    },
  });
  motionMocks.to.mockReset();
  motionMocks.to.mockImplementation(
    (
      counter: { value: number },
      vars: {
        duration: number;
        ease: string;
        snap: { value: number };
        onUpdate: () => void;
      },
    ) => {
      motionMocks.counter = counter;
      motionMocks.tweenVars = vars;
      return { kill: vi.fn() };
    },
  );
});

afterEach(() => {
  cleanup();
});

describe("useGsapProfilePdl", () => {
  it("conta de zero ao PDL final com frames inteiros em PT-BR", async () => {
    render(<Harness value={2348} />);

    await waitFor(() => expect(motionMocks.to).toHaveBeenCalledTimes(1));
    expect(motionMocks.counter).toEqual({ value: 0 });
    expect(motionMocks.tweenVars).toMatchObject({
      duration: 2,
      ease: "power1.out",
      snap: { value: 1 },
    });

    act(() => {
      if (!motionMocks.counter || !motionMocks.tweenVars) {
        throw new Error("Tween do contador não foi registrado.");
      }
      motionMocks.counter.value = 2348;
      motionMocks.tweenVars.onUpdate();
    });

    expect(screen.getByLabelText("2.348 PDL").textContent).toBe("2.348");
  });

  it("mantém o valor final estático quando movimento reduzido está ativo", async () => {
    motionMocks.reduced = true;

    render(<Harness value={2348} />);

    expect(screen.getByLabelText("2.348 PDL").textContent).toBe("2.348");
    await Promise.resolve();
    expect(motionMocks.to).not.toHaveBeenCalled();
  });

  it("reverte o contexto GSAP ao desmontar", async () => {
    const view = render(<Harness value={2348} />);
    await waitFor(() => expect(motionMocks.to).toHaveBeenCalledTimes(1));

    view.unmount();

    expect(motionMocks.revert).toHaveBeenCalledTimes(1);
  });
});
