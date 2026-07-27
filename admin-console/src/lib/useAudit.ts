/* Shared by both the Audit Log page (table) and the Activity Feed page
   (timeline) — same rows, newest-first, unfiltered here (client-side filter
   chips narrow the table view). Light poll: audit events are sparse. */
import { useEffect, useState } from "react";
import { ApiError, type Conn } from "./backend";
import { fetchAuditEvents } from "./auditActions";
import type { AuditEventInfo } from "./types";

export interface AuditState {
  events: AuditEventInfo[] | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useAudit(conn: Conn, intervalMs = 20000, nonce = 0): AuditState {
  const [events, setEvents] = useState<AuditEventInfo[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [manual, setManual] = useState(0);

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
        const list = await fetchAuditEvents(conn, ctrl.signal);
        if (!stopped) {
          setEvents(list);
          setError(null);
          setLoading(false);
        }
      } catch (e) {
        if ((e as Error)?.name === "AbortError") return;
        if (!stopped) {
          setLoading(false);
          if (!(e instanceof ApiError) || (e.status !== 401 && e.status !== 403 && e.status !== 503)) {
            setError((e as Error).message ?? "Falha ao carregar auditoria");
          }
        }
      }
      if (!stopped) timer = setTimeout(tick, intervalMs);
    };
    void tick();

    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      ctrl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conn.id, conn.base, conn.key, nonce, manual]);

  return { events, loading, error, refresh: () => setManual((n) => n + 1) };
}
