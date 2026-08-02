import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { LensTree } from "./LensTree";
import { createLensMock, type LensAxisKey } from "./lensModel";

afterEach(cleanup);

function TreeHarness() {
  const data = createLensMock("Clesio#BR1");
  const [activeKey, setActiveKey] = useState<LensAxisKey>("adapt");
  const [metricKey, setMetricKey] = useState<string | null>(null);

  return (
    <>
      <LensTree
        axes={data.axes}
        overallScore={data.overall.score}
        overallPercentile={data.overall.percentile}
        activeKey={activeKey}
        activeMetricKey={metricKey}
        onSelectAxis={(key) => {
          setActiveKey(key);
          setMetricKey(null);
        }}
        onSelectMetric={(axis, metric) => {
          setActiveKey(axis);
          setMetricKey(metric);
        }}
      />
      <output role="status">{activeKey}:{metricKey ?? "sem-métrica"}</output>
    </>
  );
}

describe("LensTree", () => {
  it("expõe o núcleo, os cinco ramos e as submétricas como uma árvore interativa", () => {
    render(<TreeHarness />);

    expect(screen.getByRole("region", { name: "Árvore de desempenho do Arena Lens" }))
      .toBeTruthy();
    expect(screen.getByLabelText("Nota geral 71 de 100")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Economia, nota 62 de 100/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Ouro parado, nota 31 de 100/i })).toBeTruthy();
    expect(screen.getByLabelText(/Ritmo de compra, indisponível/i)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Economia, nota 62 de 100/i }));
    expect(screen.getByRole("status").textContent).toBe("eco:sem-métrica");

    fireEvent.click(screen.getByRole("button", { name: /Ouro parado, nota 31 de 100/i }));
    expect(screen.getByRole("status").textContent).toBe("eco:unspentGoldRate");
  });

  it("percorre os cinco eixos pelas setas e mantém o foco no ramo ativo", () => {
    render(<TreeHarness />);
    const adapt = screen.getByRole("button", { name: /Adaptabilidade, nota 74 de 100/i });

    adapt.focus();
    fireEvent.keyDown(adapt, { key: "ArrowRight" });

    const economy = screen.getByRole("button", { name: /Economia, nota 62 de 100/i });
    expect(screen.getByRole("status").textContent).toBe("eco:sem-métrica");
    expect(document.activeElement).toBe(economy);
  });
});
