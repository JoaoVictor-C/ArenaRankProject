import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, act } from "@testing-library/react";
import { FreshnessBadge } from "./FreshnessBadge";

const NOW = new Date("2026-07-24T12:00:00Z").getTime();

function renderAgeMs(ms: number) {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
  return render(<FreshnessBadge updatedAt={NOW - ms} refreshing={false} onRefresh={() => {}} />);
}

// Sem `globals: true` no vitest config o auto-cleanup do RTL não roda: sem isto
// os renders se acumulam no mesmo document e getBy* acha elemento duplicado.
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("FreshnessBadge", () => {
  it('mostra "agora" abaixo de 1 min', () => {
    renderAgeMs(30_000);
    expect(screen.getByText("Atualizado agora")).toBeTruthy();
  });

  it("mostra minutos entre 1 min e 1 h", () => {
    renderAgeMs(3 * 60_000);
    expect(screen.getByText("Atualizado há 3 min")).toBeTruthy();
  });

  it("mostra horas acima de 1 h", () => {
    renderAgeMs(2 * 60 * 60_000);
    expect(screen.getByText("Atualizado há 2h")).toBeTruthy();
  });

  it("marca is-stale acima de 5 min — o jogador precisa desconfiar do número", () => {
    const { container } = renderAgeMs(6 * 60_000);
    expect(container.querySelector(".fresh-badge.is-stale")).toBeTruthy();
  });

  it("revalidando não é stale, mesmo com dado velho", () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    const { container } = render(
      <FreshnessBadge updatedAt={NOW - 60 * 60_000} refreshing onRefresh={() => {}} />
    );
    expect(screen.getByText("Atualizando…")).toBeTruthy();
    expect(container.querySelector(".fresh-badge.is-stale")).toBeNull();
  });

  it("o rótulo envelhece sozinho numa aba deixada aberta", () => {
    renderAgeMs(0);
    expect(screen.getByText("Atualizado agora")).toBeTruthy();
    // act(): o setState vem do setInterval, fora do fluxo do React.
    act(() => {
      vi.advanceTimersByTime(5 * 60_000);
    });
    expect(screen.getByText("Atualizado há 5 min")).toBeTruthy();
  });

  it("botão desabilita enquanto revalida (sem disparar request duplicado)", () => {
    const onRefresh = vi.fn();
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    render(<FreshnessBadge updatedAt={NOW} refreshing onRefresh={onRefresh} />);
    const btn = screen.getByLabelText("Atualizar dados agora") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});
