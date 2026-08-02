/* ============================================================
   queryClient — defaults do cache de cliente (TanStack Query).
   Fábrica compartilhada entre o app (main.tsx) e os testes do
   useApi, para que o teste exercite os MESMOS defaults de prod.
   ============================================================ */
import { QueryClient, keepPreviousData } from "@tanstack/react-query";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Dados de ranking mudam em minutos; 60s sem refetch é invisível
        // e mata o spinner de troca de aba (arquitetura-read-path §3.1).
        staleTime: 60_000,
        gcTime: 30 * 60_000,
        retry: 1,
        // O caso de uso nº1 é "joguei uma partida, voltei pra aba pra ver minha
        // posição". Com refetch desligado esse jogador ficava com dado velho até
        // dar F5. Ligado + staleTime 60s não gera spam (alt-tab rápido não
        // refaz nada) e não pisca spinner: havendo dado em cache o refetch é de
        // fundo, isPending continua false.
        refetchOnWindowFocus: true,
        // Paginação/troca de filtro mantém a página anterior visível
        // enquanto a nova carrega (Leaderboard sem spinner).
        placeholderData: keepPreviousData,
      },
    },
  });
}
