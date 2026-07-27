/* Audit-log read. Same conventions as operatorActions.ts. */
import { apiGet, type Conn } from "./backend";
import type { AuditEventInfo } from "./types";

export const fetchAuditEvents = (conn: Conn, signal?: AbortSignal): Promise<AuditEventInfo[]> =>
  apiGet<AuditEventInfo[]>(conn, "/admin/audit", signal);
