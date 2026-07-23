/* ============================================================
   useApi — fetch tipado com estado loading/error/data.
   Uso: const { data, loading, error } = useApi(() => api.leaderboard({...}), [deps]);
   ============================================================ */
import { useEffect, useState } from "react";
import { ApiError } from "../lib/api";

export interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: ApiError | Error | null;
}

export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []): ApiState<T> {
  const [state, setState] = useState<ApiState<T>>({ data: null, loading: true, error: null });

  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    fetcher()
      .then((data) => {
        if (alive) setState({ data, loading: false, error: null });
      })
      .catch((error: Error) => {
        if (alive) setState({ data: null, loading: false, error });
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
