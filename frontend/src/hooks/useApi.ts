/* ============================================================
   useApi — fetch tipado com estado loading/error/data + retry.
   Uso: const { data, loading, error, retry } = useApi(() => api.leaderboard({...}), [deps]);

   Implementado sobre TanStack Query (assinatura preservada — as rotas
   não mudam). A queryKey é o fonte do fetcher (estável por call site,
   e call sites idênticos compartilham cache de propósito) + os deps,
   que continuam obrigatórios para valores capturados pelo closure.
   Defaults (staleTime/gcTime/retry/keepPreviousData) em lib/queryClient.
   ============================================================ */
import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { ApiError } from "../lib/api";
import type { Seed } from "../lib/snapshot";

export interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: ApiError | Error | null;
  /** Refaz a chamada com os mesmos deps (botão "Tentar de novo"). */
  retry: () => void;
  /** Revalidando em fundo com dado antigo no ar (badge "atualizando..."). */
  refreshing: boolean;
  /** Epoch ms da última resposta OK; 0 = nunca respondeu. Fonte do "há N min". */
  updatedAt: number;
}

export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  /** Semente de build (lib/snapshot.seedFrom): pinta na 1ª visita, sem rede.
   *  O initialDataUpdatedAt vem do build, então a query nasce stale e refaz
   *  o fetch na montagem — a semente adianta o pixel, não o dado. */
  seed: Seed<T> = {},
  /** Sobrescreve o `retry` global (1) por chamada — para endpoints que ainda
   *  não existem no backend (404 permanente, não transiente), onde o retry
   *  padrão vira ~2 minutos martelando o servidor antes de mostrar o erro. */
  options: { retry?: number | boolean } = {},
): ApiState<T> {
  const query = useQuery<T, ApiError | Error>({
    queryKey: [fetcher.toString(), ...deps],
    queryFn: fetcher,
    initialData: seed.initialData,
    initialDataUpdatedAt: seed.initialDataUpdatedAt,
    ...(options.retry !== undefined ? { retry: options.retry } : {}),
  });

  const refetch = query.refetch;
  const retry = useCallback(() => {
    void refetch();
  }, [refetch]);

  return {
    data: query.data ?? null,
    // isPending só na 1ª carga sem cache: com keepPreviousData a troca de
    // página/filtro mantém os dados anteriores no ar em vez de spinner.
    loading: query.isPending,
    error: query.error ?? null,
    retry,
    // isFetching cobre a 1ª carga também; descontar isPending deixa "refreshing"
    // significar exatamente "tem dado velho na tela e estou buscando o novo".
    refreshing: query.isFetching && !query.isPending,
    updatedAt: query.dataUpdatedAt,
  };
}
