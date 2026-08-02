import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { Lens } from "./Lens";

vi.mock("./lensMotion", () => ({
  useLensEntrance: () => {},
  useLensAxisMotion: () => {},
}));

afterEach(cleanup);

function renderLens(path = "/perfil/Clesio%23BR1/lens") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/perfil/:riotId/lens" element={<Lens />} />
        <Route path="/:riotId/lens" element={<Lens />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Lens", () => {
  it("renderiza o overview completo usando o fixture local", () => {
    renderLens();

    expect(screen.getByRole("heading", { name: /camaleão de duelo/i })).toBeTruthy();
    expect(screen.getByText("Dados mockados")).toBeTruthy();
    expect(screen.getByLabelText("Nota geral 71 de 100")).toBeTruthy();
    expect(screen.getByText("Amplitude do pool")).toBeTruthy();
    expect(screen.getByText(/métricas detalhadas disponíveis desde 12\/08\/2026 \(34 partidas\)/i))
      .toBeTruthy();
    expect(screen.getByRole("link", { name: "Voltar ao perfil" }).getAttribute("href"))
      .toBe("/perfil/Clesio%23BR1");
  });

  it("troca o painel pela árvore e expõe métricas bloqueadas", () => {
    renderLens();

    const economy = screen.getByRole("button", { name: /Economia, nota 62 de 100/i });
    fireEvent.click(economy);

    expect(economy.getAttribute("aria-pressed"))
      .toBe("true");
    expect(screen.getByText("Ouro parado")).toBeTruthy();
    expect(screen.getByText(/requer telemetria detalhada/i)).toBeTruthy();
  });

  it("permite percorrer os cinco eixos pelo teclado", () => {
    renderLens();
    const adapt = screen.getByRole("button", { name: /Adaptabilidade, nota 74 de 100/i });

    adapt.focus();
    fireEvent.keyDown(adapt, { key: "ArrowRight" });

    const economy = screen.getByRole("button", { name: /Economia, nota 62 de 100/i });
    expect(economy.getAttribute("aria-pressed"))
      .toBe("true");
    expect(document.activeElement).toBe(economy);
  });

  it("recalibra a janela do fixture sem buscar o backend", () => {
    renderLens();
    const controls = screen.getByLabelText("Configuração do Lens");

    fireEvent.click(within(controls).getByRole("button", { name: "20" }));

    expect(controls.textContent).toContain("20 partidas");
    expect(within(controls).getByRole("button", { name: "20" }).getAttribute("aria-pressed"))
      .toBe("true");
  });

  it("aceita a rota curta de mercado", () => {
    renderLens("/ArenaLab%23MOCK/lens");

    expect(screen.getByText("ArenaLab")).toBeTruthy();
    expect(screen.getByText("#MOCK")).toBeTruthy();
  });

  it("expõe os estados vazio e de erro sem depender da API", () => {
    const empty = renderLens("/perfil/Clesio%23BR1/lens?preview=empty");
    expect(screen.getByText(/jogue algumas partidas de arena para abrir seu lens/i)).toBeTruthy();
    empty.unmount();

    renderLens("/perfil/Clesio%23BR1/lens?preview=error");
    expect(screen.getByRole("heading", { name: /não foi possível abrir o lens/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /tentar novamente/i })).toBeTruthy();
  });

  it("preserva a árvore no Lens parcial e oculta a nota global", () => {
    renderLens("/perfil/Clesio%23BR1/lens?preview=partial");

    expect(screen.getByText(/lens parcial · faltam 6 partidas/i)).toBeTruthy();
    expect(screen.getByLabelText("Nota global indisponível: Lens parcial")).toBeTruthy();
    expect(screen.queryByLabelText("Nota geral 71 de 100")).toBeNull();
    expect(screen.getByRole("region", { name: "Árvore de desempenho do Arena Lens" }))
      .toBeTruthy();
  });

  it("mostra skeleton e aviso de coorte ampliada nos previews correspondentes", () => {
    const loading = renderLens("/perfil/Clesio%23BR1/lens?preview=loading");
    expect(screen.getByLabelText("Carregando Arena Lens")).toBeTruthy();
    loading.unmount();

    renderLens("/perfil/Clesio%23BR1/lens?preview=fallback");
    expect(screen.getByText("Comparando com faixa ampliada")).toBeTruthy();
  });
});
