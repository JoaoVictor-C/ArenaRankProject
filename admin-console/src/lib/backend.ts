/* ============================================================
   Backend selection (local ↔ produção ↔ custom), admin-key storage,
   the admin API client, and an SSE-over-fetch reader.

   Why fetch-based SSE (not EventSource): the admin surface is gated by an
   `X-Admin-Key` header, and the browser `EventSource` API cannot set headers.
   `fetch` + a ReadableStream reader lets us stream `text/event-stream` while
   still sending the key.

   The "local" preset uses an EMPTY base so requests go to a relative `/api`
   path and ride the Vite dev proxy (no CORS). "produção"/"custom" use an
   absolute base and hit the API directly (CORS governed by that backend).

   Admin keys are stored PER BACKEND — local and production normally have
   different ADMIN_API_KEY values, so switching backends keeps each key.
   ============================================================ */

export type BackendId = "local" | "production" | "custom";

export interface Conn {
  /** Stable id of the active backend selection. */
  id: BackendId;
  label: string;
  /** Base origin. "" => relative (Vite proxy). Otherwise absolute, no trailing slash. */
  base: string;
  /** Admin key for THIS backend, or null. Sent as `X-Admin-Key`. */
  key: string | null;
}

const LS = {
  backend: "arenarank.console.backend",
  customUrl: "arenarank.console.customUrl",
  prodUrl: "arenarank.console.prodUrl",
  adminKeyPrefix: "arenarank.console.adminKey.", // + backend id
} as const;

function lsGet(k: string): string | null {
  try {
    return typeof localStorage !== "undefined" ? localStorage.getItem(k) : null;
  } catch {
    return null;
  }
}
function lsSet(k: string, v: string | null): void {
  try {
    if (v === null || v === "") localStorage.removeItem(k);
    else localStorage.setItem(k, v);
  } catch {
    /* storage unavailable (private mode) — ignore */
  }
}

const stripSlash = (u: string): string => u.trim().replace(/\/+$/, "");

/* ---- Persisted selections ---- */

export function getBackendId(): BackendId {
  const v = lsGet(LS.backend);
  return v === "production" || v === "custom" ? v : "local";
}
export function setBackendId(id: BackendId): void {
  lsSet(LS.backend, id);
}

export function getProdUrl(): string {
  return lsGet(LS.prodUrl) ?? stripSlash(import.meta.env.VITE_PROD_API_URL ?? "");
}
export function setProdUrl(url: string): void {
  lsSet(LS.prodUrl, stripSlash(url));
}

export function getCustomUrl(): string {
  return lsGet(LS.customUrl) ?? "";
}
export function setCustomUrl(url: string): void {
  lsSet(LS.customUrl, stripSlash(url));
}

export function getAdminKey(id: BackendId = getBackendId()): string | null {
  const v = lsGet(LS.adminKeyPrefix + id);
  return v && v.trim() ? v : null;
}
export function setAdminKey(key: string, id: BackendId = getBackendId()): void {
  lsSet(LS.adminKeyPrefix + id, key.trim() || null);
}
export function clearAdminKey(id: BackendId = getBackendId()): void {
  lsSet(LS.adminKeyPrefix + id, null);
}

/** Resolve the current Conn from persisted state. */
export function resolveConn(): Conn {
  const id = getBackendId();
  const key = getAdminKey(id);
  if (id === "production") return { id, label: "Produção", base: getProdUrl(), key };
  if (id === "custom") return { id, label: "Custom", base: getCustomUrl(), key };
  return { id: "local", label: "Local", base: "", key };
}

/** Human-readable origin for display ("proxy → :8000" for local). */
export function displayOrigin(conn: Conn): string {
  if (conn.id === "local") return "proxy local → :8000";
  return conn.base || "(defina a URL)";
}

/* ---- Errors ---- */

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function url(conn: Conn, path: string): string {
  return `${conn.base}/api/v1${path}`;
}

function headers(conn: Conn, withBody: boolean): HeadersInit {
  const h: Record<string, string> = { Accept: "application/json" };
  if (withBody) h["Content-Type"] = "application/json";
  if (conn.key) h["X-Admin-Key"] = conn.key;
  return h;
}

async function parseError(res: Response): Promise<ApiError> {
  let detail = res.statusText || `HTTP ${res.status}`;
  try {
    const data = await res.json();
    if (typeof data?.detail === "string") detail = data.detail;
    else if (data?.detail) detail = JSON.stringify(data.detail);
  } catch {
    /* non-JSON body */
  }
  return new ApiError(res.status, detail);
}

/* ---- JSON client ---- */

export async function apiGet<T>(conn: Conn, path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url(conn, path), { headers: headers(conn, false), signal });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as T;
}

export async function apiSend<T>(
  conn: Conn,
  method: "POST" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(url(conn, path), {
    method,
    headers: headers(conn, body !== undefined),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw await parseError(res);
  const text = await res.text();
  return (text ? JSON.parse(text) : {}) as T;
}

/* ---- SSE over fetch ---- */

export interface StreamHandlers {
  onOpen?: () => void;
  onFrame: (data: string) => void;
  onError: (err: Error) => void;
}

/**
 * Consume a `text/event-stream` from `path`, invoking `onFrame` with the
 * `data:` payload of each event. Resolves when the stream ends; reports
 * failures via `onError`. Abort through `signal`.
 */
export async function streamSSE(
  conn: Conn,
  path: string,
  handlers: StreamHandlers,
  signal: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(url(conn, path), {
      headers: { ...headers(conn, false), Accept: "text/event-stream" },
      signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    handlers.onError(err as Error);
    return;
  }
  if (!res.ok) {
    handlers.onError(await parseError(res));
    return;
  }
  if (!res.body) {
    handlers.onError(new Error("Stream sem corpo (ReadableStream indisponível)."));
    return;
  }
  handlers.onOpen?.();

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      buf = buf.replace(/\r\n/g, "\n");
      let sep: number;
      while ((sep = buf.indexOf("\n\n")) !== -1) {
        const rawEvent = buf.slice(0, sep);
        buf = buf.slice(sep + 2);
        const dataLines = rawEvent
          .split("\n")
          .filter((l) => l.startsWith("data:"))
          .map((l) => l.slice(5).replace(/^ /, ""));
        if (dataLines.length) handlers.onFrame(dataLines.join("\n"));
      }
    }
  } catch (err) {
    if ((err as Error).name !== "AbortError") handlers.onError(err as Error);
  }
}
