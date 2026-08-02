/* ============================================================
   snapshot — semente de build para a PRIMEIRA visita.

   `scripts/build-snapshot.mjs` congela as respostas globais quentes em
   src/generated/*.json no momento do build. Aqui elas viram `initialData`
   do TanStack Query: a página pinta sem esperar rede, e revalida em seguida.

   Honestidade é o ponto: passamos `initialDataUpdatedAt = generatedAt`, a
   idade REAL da semente. Como ela é sempre mais velha que o staleTime de
   60s, a query nasce stale e refaz o fetch na montagem — e o FreshnessBadge
   mostra "há 3h" em vez de fingir "agora".
   ============================================================ */

/** Acima disto a semente é pior que um skeleton: um leaderboard da semana
 *  passada apresentado como ranking atual mina a legitimidade do CR. */
const MAX_AGE_MS = 24 * 60 * 60 * 1000;

export interface SnapshotFile {
  generatedAt: number;
  entries: Record<string, unknown>;
}

export interface Seed<T> {
  initialData?: T;
  initialDataUpdatedAt?: number;
}

/**
 * Converte uma entrada do snapshot em opções de semente do useApi.
 * Devolve `{}` (nenhuma semente) quando o build não conseguiu buscar o dado
 * ou quando a semente passou de MAX_AGE_MS.
 */
export function seedFrom<T>(file: SnapshotFile, key: string, now = Date.now()): Seed<T> {
  const value = file.entries?.[key];
  if (value === null || value === undefined) return {};
  if (!file.generatedAt || now - file.generatedAt > MAX_AGE_MS) return {};
  return { initialData: value as T, initialDataUpdatedAt: file.generatedAt };
}
