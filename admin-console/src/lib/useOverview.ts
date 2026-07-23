/* Slow poll of /admin/overview for DB-backed context (season, integrity,
   flags, DLQ items, business metrics) — separate from the fast worker stream. */
import { useEffect, useRef, useState } from "react";
import { ApiError, type Conn } from "./backend";
import { fetchOverview } from "./actions";
import type { AdminOverview } from "./types";

export interface OverviewState {
  overview: AdminOverview | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useOverview(conn: Conn, intervalMs = 8000, nonce = 0): OverviewState {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [manual, setManual] = useState(0);
  const intervalRef = useRef(intervalMs);
  intervalRef.current = intervalMs;

  useEffect(() => {
    if (!conn.key || (conn.id !== "local" && !conn.base)) {
      setLoading(false);
      return;
    }
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ctrl = new AbortController();

    const tick = async () => {
      if (stopped) return;
      try {
        const ov = await fetchOverview(conn, ctrl.signal);
        if (!stopped) {
          setOverview(ov);
          setError(null);
          setLoading(false);
        }
      } catch (e) {
        if ((e as Error)?.name === "AbortError") return;
        if (!stopped) {
          setLoading(false);
          // 401/503 are surfaced by the telemetry hook / gate; just note others.
          if (!(e instanceof ApiError) || (e.status !== 401 && e.status !== 503)) {
            setError((e as Error).message ?? "Falha ao carregar visão geral");
          }
        }
      }
      if (!stopped) timer = setTimeout(tick, intervalRef.current);
    };
    void tick();

    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      ctrl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conn.id, conn.base, conn.key, nonce, manual]);

  return { overview, loading, error, refresh: () => setManual((n) => n + 1) };
}
