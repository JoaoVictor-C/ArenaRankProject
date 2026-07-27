/* Light poll of /tournaments — tournaments don't change every second, so this
   mirrors useOverview's cadence rather than the fast telemetry stream. */
import { useEffect, useRef, useState } from "react";
import { ApiError, type Conn } from "./backend";
import { fetchTournaments } from "./tournamentActions";
import type { TournamentListItem } from "./types";

export interface TournamentsState {
  tournaments: TournamentListItem[] | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useTournaments(conn: Conn, intervalMs = 15000, nonce = 0): TournamentsState {
  const [tournaments, setTournaments] = useState<TournamentListItem[] | null>(null);
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
        const list = await fetchTournaments(conn, ctrl.signal);
        if (!stopped) {
          setTournaments(list);
          setError(null);
          setLoading(false);
        }
      } catch (e) {
        if ((e as Error)?.name === "AbortError") return;
        if (!stopped) {
          setLoading(false);
          if (!(e instanceof ApiError) || (e.status !== 401 && e.status !== 503)) {
            setError((e as Error).message ?? "Falha ao carregar campeonatos");
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

  return { tournaments, loading, error, refresh: () => setManual((n) => n + 1) };
}
