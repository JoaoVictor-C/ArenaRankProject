/* On-demand search (not a poll) — debounced so typing doesn't fire a
   request per keystroke. */
import { useEffect, useRef, useState } from "react";
import { ApiError, type Conn } from "./backend";
import { searchPlayers } from "./playerActions";
import type { PlayerSearchRow } from "./types";

export interface PlayerSearchState {
  query: string;
  setQuery: (q: string) => void;
  results: PlayerSearchRow[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

const MIN_QUERY_LEN = 2;
const DEBOUNCE_MS = 300;

export function usePlayerSearch(conn: Conn): PlayerSearchState {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PlayerSearchRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manual, setManual] = useState(0);

  const connRef = useRef(conn);
  connRef.current = conn;

  useEffect(() => {
    const q = query.trim();
    if (q.length < MIN_QUERY_LEN) {
      setResults([]);
      setLoading(false);
      setError(null);
      return;
    }
    if (!conn.key) return;

    const ctrl = new AbortController();
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const rows = await searchPlayers(connRef.current, q, ctrl.signal);
        setResults(rows);
        setError(null);
      } catch (e) {
        if ((e as Error)?.name === "AbortError") return;
        if (!(e instanceof ApiError) || (e.status !== 401 && e.status !== 503)) {
          setError((e as Error).message ?? "Falha na busca");
        }
      } finally {
        setLoading(false);
      }
    }, DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [conn.id, conn.base, conn.key, query, manual]);

  return { query, setQuery, results, loading, error, refresh: () => setManual((n) => n + 1) };
}
