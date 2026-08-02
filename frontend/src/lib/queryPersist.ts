/* ============================================================
   queryPersist — cache do TanStack Query sobrevivendo ao reload.

   Sem isto o cache mora só em memória: F5 ou aba nova = tela branca até a
   API responder. Com isto o primeiro paint sai do IndexedDB (~0ms) e a
   revalidação acontece atrás, com badge de frescor (ver `useApi.updatedAt`).

   IndexedDB e não localStorage: localStorage é síncrono e bloquearia o main
   thread justo no boot, que é o momento que estamos tentando acelerar.
   ============================================================ */
import { get, set, del } from "idb-keyval";
import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister";
import type { PersistQueryClientOptions } from "@tanstack/react-query-persist-client";
import { defaultShouldDehydrateQuery } from "@tanstack/react-query";

const IDB_KEY = "arenarank.queryCache";

/** Além disto, o cache é lixo: descartamos e mostramos skeleton em vez de
 *  pintar um CR de ontem como se fosse de agora. */
const MAX_AGE_MS = 6 * 60 * 60 * 1000;

/** Bump manual quando o shape de alguma resposta mudar de forma incompatível:
 *  invalida todo o cache persistido dos clientes que ainda têm o antigo. */
const CACHE_BUSTER = "v1";

const persister = createAsyncStoragePersister({
  storage: {
    getItem: (key) => get(key).then((v) => v ?? null),
    setItem: (key, value) => set(key, value),
    removeItem: (key) => del(key),
  },
  key: IDB_KEY,
  // O throttle evita reescrever o IDB a cada refetch de fundo.
  throttleTime: 1_000,
});

export const persistOptions: Omit<PersistQueryClientOptions, "queryClient"> = {
  persister,
  maxAge: MAX_AGE_MS,
  buster: CACHE_BUSTER,
  dehydrateOptions: {
    shouldDehydrateQuery: (query) => {
      // /admin/* é dado operacional atrás de X-Admin-Key: não deixamos
      // resíduo no disco do navegador. A queryKey do useApi é o fonte da
      // função fetcher, e o nome do método (api.adminX) sobrevive à
      // minificação por ser acesso a propriedade.
      if (/admin/i.test(String(query.queryKey[0]))) return false;
      return defaultShouldDehydrateQuery(query);
    },
  },
};
