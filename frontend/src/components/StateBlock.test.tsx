import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { StateBlock } from "./StateBlock";

afterEach(cleanup);

describe("StateBlock", () => {
  it("anuncia a carga sem expor o spinner à árvore acessível", () => {
    const { container } = render(<StateBlock loading />);

    const status = screen.getByRole("status");
    expect(status.getAttribute("aria-busy")).toBe("true");
    expect(screen.getByText("Carregando…")).toBeTruthy();
    expect(container.querySelector(".state-spinner")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("anuncia a falha como alerta e mantém a recuperação acionável", () => {
    const retry = vi.fn();
    render(<StateBlock error={new Error("offline")} onRetry={retry} />);

    expect(screen.getByRole("alert")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("permite copy contextual no estado vazio compacto", () => {
    render(<StateBlock empty compact emptyLabel="Sem augments neste patch." />);

    const status = screen.getByRole("status");
    expect(status.classList.contains("state-block-compact")).toBe(true);
    expect(screen.getByText("Sem augments neste patch.")).toBeTruthy();
  });

  it("permite nomear precisamente o recurso que está carregando", () => {
    render(<StateBlock loading loadingLabel="Carregando histórico diário…" />);

    expect(screen.getByRole("status")).toBeTruthy();
    expect(screen.getByText("Carregando histórico diário…")).toBeTruthy();
  });

  it("permite contextualizar a falha sem perder o detalhe de recuperação", () => {
    render(
      <StateBlock
        error={new Error("offline")}
        errorLabel="Não foi possível carregar os rounds."
      />,
    );

    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByText("Não foi possível carregar os rounds.")).toBeTruthy();
    expect(screen.getByText("Falha de rede — verifique sua conexão.")).toBeTruthy();
  });
});
