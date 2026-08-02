/* useApi sobre TanStack Query — os aceites do T0.1 (workaround_readpath):
   remount dentro do staleTime NÃO refaz o fetch; troca de deps (paginação)
   mantém os dados anteriores sem voltar a loading; retry() refaz após erro.
   Usa makeQueryClient() de prod para testar os defaults reais. */
import { describe, it, expect, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useApi } from "./useApi";
import { makeQueryClient } from "../lib/queryClient";

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useApi (TanStack Query)", () => {
  it("1ª carga: loading → data, sem error", async () => {
    const client = makeQueryClient();
    const fetcher = vi.fn().mockResolvedValue({ ok: 1 });
    const { result } = renderHook(() => useApi(fetcher, []), {
      wrapper: wrapperFor(client),
    });

    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBeNull();
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toEqual({ ok: 1 });
    expect(result.current.error).toBeNull();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("remount dentro do staleTime não dispara novo fetch (cache de cliente)", async () => {
    const client = makeQueryClient();
    const fetcher = vi.fn().mockResolvedValue("dados");
    const wrapper = wrapperFor(client);

    const first = renderHook(() => useApi(fetcher, []), { wrapper });
    await waitFor(() => expect(first.result.current.data).toBe("dados"));
    first.unmount();

    // "Trocar de aba e voltar": novo mount do mesmo call site + deps.
    const second = renderHook(() => useApi(fetcher, []), { wrapper });
    expect(second.result.current.data).toBe("dados"); // servido do cache, sem loading
    expect(second.result.current.loading).toBe(false);
    await waitFor(() => expect(second.result.current.loading).toBe(false));
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("paginação: deps mudam, dados anteriores ficam no ar (sem spinner)", async () => {
    const client = makeQueryClient();
    let release!: (rows: string) => void;
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce("página 1")
      .mockImplementationOnce(
        () => new Promise<string>((resolve) => (release = resolve)),
      );

    const { result, rerender } = renderHook(({ page }) => useApi(fetcher, [page]), {
      wrapper: wrapperFor(client),
      initialProps: { page: 1 },
    });
    await waitFor(() => expect(result.current.data).toBe("página 1"));

    rerender({ page: 2 });
    // keepPreviousData: página 1 continua visível, sem voltar a loading.
    expect(result.current.data).toBe("página 1");
    expect(result.current.loading).toBe(false);

    release("página 2");
    await waitFor(() => expect(result.current.data).toBe("página 2"));
  });

  it("erro vira {error} e retry() refaz a chamada", async () => {
    // retry automático desligado só aqui: o teste mira o retry() manual.
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 60_000 } },
    });
    const fetcher = vi
      .fn()
      .mockRejectedValueOnce(new Error("falhou"))
      .mockResolvedValueOnce("recuperado");

    const { result } = renderHook(() => useApi(fetcher, []), {
      wrapper: wrapperFor(client),
    });
    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.loading).toBe(false);

    result.current.retry();
    await waitFor(() => expect(result.current.data).toBe("recuperado"));
    expect(result.current.error).toBeNull();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("call sites diferentes com deps iguais não colidem no cache", async () => {
    const client = makeQueryClient();
    const wrapper = wrapperFor(client);
    // Fontes distintas → queryKeys distintas, mesmo com deps [].
    const a = renderHook(() => useApi(async () => "resposta A", []), { wrapper });
    const b = renderHook(() => useApi(async () => "resposta B", []), { wrapper });
    await waitFor(() => expect(a.result.current.data).toBe("resposta A"));
    await waitFor(() => expect(b.result.current.data).toBe("resposta B"));
  });
});
