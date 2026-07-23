import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { ErrorBoundary } from "./ErrorBoundary";

afterEach(cleanup);

function Boom(): never {
  throw new Error("explodiu");
}

describe("ErrorBoundary", () => {
  it("renderiza os filhos quando não há erro", () => {
    render(
      <ErrorBoundary>
        <p>conteúdo ok</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("conteúdo ok")).toBeTruthy();
    expect(screen.queryByText("Algo deu errado")).toBeNull();
  });

  it("mostra o fallback (e a mensagem) quando um filho lança no render", () => {
    // O React + o boundary registram o erro no console; silencia durante o teste.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Algo deu errado")).toBeTruthy();
    expect(screen.getByText("explodiu")).toBeTruthy();
    expect(screen.queryByText("conteúdo ok")).toBeNull();
    spy.mockRestore();
  });
});
