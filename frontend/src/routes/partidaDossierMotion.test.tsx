import { StrictMode, useRef } from "react";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePartidaDossierMotion } from "./partidaDossierMotion";

const motionMocks = vi.hoisted(() => ({
  contextReverts: [] as Array<ReturnType<typeof vi.fn>>,
  fromTo: vi.fn(),
  loadMotion: vi.fn(),
  prefersReducedMotion: vi.fn(),
  timelineFromTo: vi.fn(),
}));

vi.mock("../lib/motion", () => ({
  EASE: {
    enter: "power3.out",
    ui: "power2.out",
  },
  MO: {
    enter: 0.42,
    ui: 0.22,
  },
  loadMotion: motionMocks.loadMotion,
  prefersReducedMotion: motionMocks.prefersReducedMotion,
}));

function Harness({
  teamKey,
  playerKey,
  direction,
  withRails = true,
}: {
  teamKey: number;
  playerKey: string;
  direction: -1 | 0 | 1;
  withRails?: boolean;
}): JSX.Element {
  const scope = useRef<HTMLDivElement>(null);

  usePartidaDossierMotion(scope, {
    teamKey,
    playerKey,
    direction,
    ready: true,
  });

  return (
    <div ref={scope}>
      <header data-hero-copy />
      <button data-testid="selected-orbit" data-orbit-node aria-pressed="true" />
      <div data-orbit-core data-team-swap />
      <section data-dossier-section>
        <button data-team-player />
      </section>
      <section data-focused-player />
      <section data-testid="comparison-section" data-comparison-section>
        {withRails && (
          <div data-comparison-rail>
            <span className="partida-comparison-mark" />
          </div>
        )}
      </section>
    </div>
  );
}

function fromToCallsWith(
  key: string,
): Array<Parameters<typeof motionMocks.fromTo>> {
  return motionMocks.fromTo.mock.calls.filter(
    (call) =>
      call[1] &&
      typeof call[1] === "object" &&
      key in (call[1] as Record<string, unknown>),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  motionMocks.contextReverts.length = 0;
  motionMocks.prefersReducedMotion.mockReturnValue(false);
  motionMocks.timelineFromTo.mockReturnThis();
  motionMocks.loadMotion.mockResolvedValue({
    gsap: {
      context: (run: () => void) => {
        run();
        const revert = vi.fn();
        motionMocks.contextReverts.push(revert);
        return { revert };
      },
      fromTo: motionMocks.fromTo,
      timeline: () => ({
        fromTo: motionMocks.timelineFromTo,
      }),
    },
  });
});

afterEach(() => {
  cleanup();
});

describe("usePartidaDossierMotion", () => {
  it("não disputa os alvos da entrada na montagem sob StrictMode", async () => {
    render(
      <StrictMode>
        <Harness teamKey={0} playerKey="a" direction={0} />
      </StrictMode>,
    );

    await waitFor(() =>
      expect(motionMocks.timelineFromTo).toHaveBeenCalled(),
    );
    expect(fromToCallsWith("x")).toHaveLength(0);
  });

  it("ignora o swap inicial e anima a próxima equipe para a direita uma única vez", async () => {
    const { rerender, unmount } = render(
      <Harness teamKey={0} playerKey="a" direction={0} />,
    );

    await waitFor(() =>
      expect(motionMocks.timelineFromTo).toHaveBeenCalled(),
    );
    expect(fromToCallsWith("x")).toHaveLength(0);
    expect(motionMocks.contextReverts).toHaveLength(1);

    rerender(<Harness teamKey={1} playerKey="b" direction={1} />);

    await waitFor(() =>
      expect(motionMocks.fromTo).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ x: 24 }),
        expect.objectContaining({ x: 0, overwrite: "auto" }),
      ),
    );
    expect(motionMocks.contextReverts).toHaveLength(2);

    const swapCallsAfterSelection = fromToCallsWith("x").length;
    rerender(<Harness teamKey={1} playerKey="b" direction={0} />);
    expect(motionMocks.loadMotion).toHaveBeenCalledTimes(2);
    expect(fromToCallsWith("x")).toHaveLength(swapCallsAfterSelection);

    unmount();
    expect(motionMocks.contextReverts[0]).toHaveBeenCalledOnce();
    expect(motionMocks.contextReverts[1]).toHaveBeenCalledOnce();
  });

  it("anima somente a troca de jogador mesmo quando a equipe não muda", async () => {
    const { rerender } = render(
      <Harness teamKey={0} playerKey="a" direction={0} />,
    );

    await waitFor(() =>
      expect(motionMocks.timelineFromTo).toHaveBeenCalled(),
    );
    expect(fromToCallsWith("x")).toHaveLength(0);

    rerender(<Harness teamKey={0} playerKey="b" direction={0} />);

    await waitFor(() =>
      expect(motionMocks.fromTo).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ x: 0 }),
        expect.objectContaining({ x: 0, overwrite: "auto" }),
      ),
    );
  });

  it("anima a equipe anterior para a esquerda", async () => {
    const { rerender } = render(
      <Harness teamKey={1} playerKey="b" direction={0} />,
    );

    await waitFor(() =>
      expect(motionMocks.timelineFromTo).toHaveBeenCalled(),
    );
    expect(fromToCallsWith("x")).toHaveLength(0);

    rerender(<Harness teamKey={0} playerKey="a" direction={-1} />);

    await waitFor(() =>
      expect(motionMocks.fromTo).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ x: -24 }),
        expect.objectContaining({ x: 0, overwrite: "auto" }),
      ),
    );
  });

  it("não cria tween de trilhos quando a troca não tem comparações", async () => {
    const { rerender } = render(
      <Harness
        teamKey={0}
        playerKey="a"
        direction={0}
        withRails={false}
      />,
    );

    await waitFor(() =>
      expect(motionMocks.timelineFromTo).toHaveBeenCalled(),
    );
    expect(fromToCallsWith("x")).toHaveLength(0);
    expect(fromToCallsWith("scaleX")).toHaveLength(0);

    rerender(
      <Harness
        teamKey={1}
        playerKey="b"
        direction={1}
        withRails={false}
      />,
    );

    await waitFor(() =>
      expect(motionMocks.fromTo).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ x: 24 }),
        expect.objectContaining({ x: 0, overwrite: "auto" }),
      ),
    );
    expect(fromToCallsWith("x")).toHaveLength(1);
    expect(fromToCallsWith("scaleX")).toHaveLength(0);
  });

  it("trata a hidratação vazio para primeiro jogador como alvo inicial", async () => {
    const { rerender } = render(
      <Harness
        teamKey={0}
        playerKey=""
        direction={0}
        withRails={false}
      />,
    );

    await waitFor(() =>
      expect(motionMocks.timelineFromTo).toHaveBeenCalled(),
    );
    rerender(
      <Harness
        teamKey={0}
        playerKey="a"
        direction={0}
        withRails={false}
      />,
    );

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(fromToCallsWith("x")).toHaveLength(0);
  });

  it("realça somente o nó orbital selecionado ao trocar de equipe", async () => {
    const { getByTestId, rerender } = render(
      <Harness teamKey={0} playerKey="a" direction={0} />,
    );

    await waitFor(() =>
      expect(motionMocks.timelineFromTo).toHaveBeenCalled(),
    );
    rerender(<Harness teamKey={1} playerKey="b" direction={1} />);

    await waitFor(() => expect(fromToCallsWith("z")).toHaveLength(1));
    const [target, from, to] = fromToCallsWith("z")[0];
    expect(target).toBe(getByTestId("selected-orbit"));
    expect(from).toMatchObject({ scale: 0.94, z: -16 });
    expect(to).toMatchObject({
      scale: 1.06,
      z: 16,
      overwrite: "auto",
    });
  });

  it("revela os trilhos uma vez quando a comparação entra no viewport", async () => {
    const { getByTestId } = render(
      <Harness teamKey={0} playerKey="a" direction={0} />,
    );

    await waitFor(() => expect(fromToCallsWith("scaleX")).toHaveLength(1));
    const [, from, to] = fromToCallsWith("scaleX")[0];
    expect(from).toMatchObject({ scaleX: 0 });
    expect(to).toMatchObject({
      scaleX: 1,
      transformOrigin: "left center",
      scrollTrigger: {
        trigger: getByTestId("comparison-section"),
        start: "top 88%",
        once: true,
      },
    });
  });

  it("não inicia GSAP com movimento reduzido", async () => {
    motionMocks.prefersReducedMotion.mockReturnValue(true);

    render(<Harness teamKey={0} playerKey="a" direction={0} />);

    await waitFor(() => expect(motionMocks.loadMotion).not.toHaveBeenCalled());
  });
});
