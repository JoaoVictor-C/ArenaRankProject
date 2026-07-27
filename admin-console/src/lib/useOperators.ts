/* Operators + the permission matrix rarely change (an admin action, not a
   live metric) — fetch once per mount/backend switch and let callers bump
   `refresh()` after a create/revoke, same convention as useTournaments. */
import { useEffect, useRef, useState } from "react";
import { ApiError, type Conn } from "./backend";
import { fetchOperators, fetchPermissionMatrix } from "./operatorActions";
import type { OperatorInfo, PermissionRow } from "./types";

export interface OperatorsState {
  operators: OperatorInfo[] | null;
  permissions: PermissionRow[] | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useOperators(conn: Conn, nonce = 0): OperatorsState {
  const [operators, setOperators] = useState<OperatorInfo[] | null>(null);
  const [permissions, setPermissions] = useState<PermissionRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [manual, setManual] = useState(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!conn.key || (conn.id !== "local" && !conn.base)) {
      setLoading(false);
      return;
    }
    let stopped = false;
    const ctrl = new AbortController();

    (async () => {
      setLoading(true);
      try {
        const [ops, perms] = await Promise.all([
          fetchOperators(conn, ctrl.signal),
          fetchPermissionMatrix(conn, ctrl.signal),
        ]);
        if (!stopped) {
          setOperators(ops);
          setPermissions(perms);
          setError(null);
        }
      } catch (e) {
        if ((e as Error)?.name === "AbortError") return;
        if (!stopped) {
          if (!(e instanceof ApiError) || (e.status !== 401 && e.status !== 503)) {
            setError((e as Error).message ?? "Falha ao carregar operadores");
          }
        }
      } finally {
        if (!stopped) setLoading(false);
      }
    })();

    return () => {
      stopped = true;
      ctrl.abort();
    };
  }, [conn.id, conn.base, conn.key, nonce, manual]);

  return { operators, permissions, loading, error, refresh: () => setManual((n) => n + 1) };
}
