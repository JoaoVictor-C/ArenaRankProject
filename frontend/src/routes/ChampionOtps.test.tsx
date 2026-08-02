import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import type { ApiState } from "../hooks/useApi";
import { ChampionOtps } from "./ChampionOtps";

const loadingState: ApiState<never> = {
  data: null,
  loading: true,
  error: null,
  retry: () => {},
  refreshing: false,
  updatedAt: 0,
};

vi.mock("../hooks/useApi", () => ({
  useApi: () => loadingState,
}));

vi.mock("../lib/motion", () => ({
  STATE_SPINNER_LOOP: {},
  useFlipList: () => ({ capture: () => {} }),
  useGsapEntrance: () => {},
  useGsapInteractions: () => {},
  useGsapLoop: () => {},
}));

afterEach(cleanup);

function renderRoute(path: string) {
  return render(
    <MemoryRouter
      initialEntries={[path]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Routes>
        <Route path="/campeao/:championId/otps" element={<ChampionOtps />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ChampionOtps", () => {
  it("não apresenta zero jogadores antes da resposta do ranking", () => {
    const { container } = renderRoute("/campeao/50/otps");

    expect(container.querySelector(".otp-page")?.hasAttribute("data-gsap-scope")).toBe(true);
    expect(screen.getByLabelText("Total de jogadores carregando")).toBeTruthy();
    expect(screen.getByText("—")).toBeTruthy();
  });

  it("trata um identificador inválido como rota inválida, não como falha de rede", () => {
    renderRoute("/campeao/invalido/otps");

    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByText("Campeão inválido.")).toBeTruthy();
    expect(screen.queryByText(/falha de rede/i)).toBeNull();
  });
});
