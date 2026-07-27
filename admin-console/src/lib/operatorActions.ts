/* Operator actions against the RBAC surface. Same conventions as
   actions.ts / tournamentActions.ts (apiGet/apiSend, Conn-first args). */
import { apiGet, apiSend, type Conn } from "./backend";
import type {
  OperatorCreateBody,
  OperatorCreateResult,
  OperatorInfo,
  OperatorRevokeResult,
  PermissionRow,
} from "./types";

export const fetchPermissionMatrix = (conn: Conn, signal?: AbortSignal): Promise<PermissionRow[]> =>
  apiGet<PermissionRow[]>(conn, "/admin/operators/permissions", signal);

export const fetchOperators = (conn: Conn, signal?: AbortSignal): Promise<OperatorInfo[]> =>
  apiGet<OperatorInfo[]>(conn, "/admin/operators", signal);

export const createOperator = (
  conn: Conn,
  body: OperatorCreateBody,
): Promise<OperatorCreateResult> => apiSend<OperatorCreateResult>(conn, "POST", "/admin/operators", body);

export const revokeOperator = (conn: Conn, operatorId: string): Promise<OperatorRevokeResult> =>
  apiSend<OperatorRevokeResult>(
    conn,
    "DELETE",
    `/admin/operators/${encodeURIComponent(operatorId)}`,
  );
