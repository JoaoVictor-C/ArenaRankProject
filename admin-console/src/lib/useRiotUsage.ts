/* Poll of /admin/riot/usage — Riot key consumption.

   Its own hook rather than a field on useOverview: the bucket gauges are
   live-ish state (a 10s window refills continuously) and deserve a faster
   cadence than the DB-backed overview, while staying far cheaper than the
   worker telemetry stream. */
import { useEffect, useRef, useState } from "react";
import { ApiError, type Conn } from "./backend";
import { fetchRiotUsage } from "./actions";
import type { RiotUsage } from "./types";

export interface RiotUsageState {
  usage: RiotUsage | null;
  loading: boolean;
  error: string | null;
}

export function useRiotUsage(conn: Conn, intervalMs = 5000, nonce = 0): RiotUsageState {
  const [usage, setUsage] = useState<RiotUsage | null>(null);
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
        const next = await fetchRiotUsage(conn, ctrl.signal);
        if (!stopped) {
          setUsage(next);
          setError(null);
          setLoading(false);
        }
      } catch (e) {
        if ((e as Error)?.name === "AbortError") return;
        if (!stopped) {
          setLoading(false);
          // 401/503 are surfaced by the gate; only note anything else, and keep
          // the last good snapshot on screen rather than blanking the gauges.
          if (!(e instanceof ApiError) || (e.status !== 401 && e.status !== 503)) {
            setError((e as Error).message ?? "Falha ao carregar uso da chave Riot");
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
  }, [conn.id, conn.base, conn.key, nonce]);

  return { usage, loading, error };
}
