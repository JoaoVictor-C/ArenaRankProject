/* Slow poll of /admin/matches/daily — DB-backed per-day match volume, same
   cadence family as useOverview (this is a daily rollup, not live telemetry). */
import { useEffect, useRef, useState } from "react";
import { ApiError, type Conn } from "./backend";
import { fetchDailyMatches } from "./actions";
import type { AdminDailyMatches } from "./types";

export interface DailyMatchesState {
  daily: AdminDailyMatches | null;
  loading: boolean;
  error: string | null;
}

export function useDailyMatches(
  conn: Conn,
  days = 14,
  intervalMs = 60000,
  nonce = 0,
): DailyMatchesState {
  const [daily, setDaily] = useState<AdminDailyMatches | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
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
        const next = await fetchDailyMatches(conn, days, ctrl.signal);
        if (!stopped) {
          setDaily(next);
          setError(null);
          setLoading(false);
        }
      } catch (e) {
        if ((e as Error)?.name === "AbortError") return;
        if (!stopped) {
          setLoading(false);
          if (!(e instanceof ApiError) || (e.status !== 401 && e.status !== 503)) {
            setError((e as Error).message ?? "Falha ao carregar partidas por dia");
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
  }, [conn.id, conn.base, conn.key, days, nonce]);

  return { daily, loading, error };
}
