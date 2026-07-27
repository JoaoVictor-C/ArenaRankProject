/* ============================================================
   useTelemetry — the real-time data engine.

   Strategy (robust by design):
     1. Probe GET /admin/workers/live.
          • 200 → rich "live" source is available.
          • 404/405/501 → endpoint not wired; fall back to GET /admin/overview.
          • 401 → unauthorized (caller shows the key gate).
          • 503 → admin access not configured on the server.
     2. If live + stream preferred → open the SSE stream. A 6s watchdog falls
        back to polling /live if the first frame never arrives (e.g. a proxy
        buffers the stream). Any stream error/close also falls back to polling.
     3. Otherwise poll the chosen endpoint every `intervalMs` (setTimeout
        recursion, so requests never stack).

   Output is always the normalized `Telemetry`, plus rolling history buffers for
   sparklines and a transport/source/status the UI surfaces in the top bar.
   ============================================================ */
import { useEffect, useRef, useState } from "react";
import { ApiError, streamSSE, type Conn } from "./backend";
import { fetchLive, fetchOverview } from "./actions";
import { fromLive, fromOverview } from "./normalize";
import type { LiveSnapshot, Telemetry } from "./types";

export type TeleStatus =
  | "idle"
  | "connecting"
  | "ok"
  | "error"
  | "unauthorized"
  | "unconfigured";

export type Transport = "stream" | "poll" | null;
export type Source = "live" | "overview" | null;

const CAP = 80;

export interface History {
  backlog: number[];
  dlq: number[];
  arqQueues: number[];
}

const EMPTY_HISTORY: History = { backlog: [], dlq: [], arqQueues: [] };

export interface TelemetryState {
  telemetry: Telemetry | null;
  history: History;
  status: TeleStatus;
  transport: Transport;
  source: Source;
  error: string | null;
  /** Monotonic count of frames/polls applied (drives the "pulse" indicator). */
  frames: number;
}

export interface TelemetryOptions {
  intervalMs: number;
  preferStream: boolean;
  /** Bump to force a full reconnect. */
  nonce: number;
}

function pushCapped(arr: number[], v: number): number[] {
  const next = arr.length >= CAP ? arr.slice(arr.length - CAP + 1) : arr.slice();
  next.push(v);
  return next;
}

export function useTelemetry(conn: Conn, opts: TelemetryOptions): TelemetryState {
  const { intervalMs, preferStream, nonce } = opts;

  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  const [history, setHistory] = useState<History>(EMPTY_HISTORY);
  const [status, setStatus] = useState<TeleStatus>("idle");
  const [transport, setTransport] = useState<Transport>(null);
  const [source, setSource] = useState<Source>(null);
  const [error, setError] = useState<string | null>(null);
  const [frames, setFrames] = useState(0);

  // Keep latest opts available without re-subscribing the whole effect.
  const intervalRef = useRef(intervalMs);
  intervalRef.current = intervalMs;

  useEffect(() => {
    // No key → idle; the gate handles auth before we ever stream.
    if (!conn.key || (conn.id !== "local" && !conn.base)) {
      setStatus("idle");
      setTransport(null);
      setSource(null);
      return;
    }

    let stopped = false;
    let settledFallback = false;
    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    let watchdog: ReturnType<typeof setTimeout> | undefined;
    const pollCtrl = new AbortController();
    let streamCtrl: AbortController | null = null;

    setStatus("connecting");
    setError(null);
    setHistory(EMPTY_HISTORY);

    const apply = (t: Telemetry, tp: Transport) => {
      if (stopped) return;
      setTelemetry(t);
      setError(null);
      setStatus("ok");
      setTransport(tp);
      setSource(t.source);
      setFrames((n) => n + 1);
      setHistory((h) => ({
        backlog: pushCapped(h.backlog, t.pipeline.totalBacklog),
        dlq: pushCapped(h.dlq, t.pipeline.dlq),
        arqQueues: pushCapped(h.arqQueues, t.pipeline.priorityQueue + t.pipeline.standardQueue),
      }));
    };

    /** Returns true if the error is terminal and the loop must stop. */
    const handleFatal = (e: unknown): boolean => {
      if ((e as Error)?.name === "AbortError") return true;
      if (e instanceof ApiError) {
        if (e.status === 401) {
          if (!stopped) setStatus("unauthorized");
          return true;
        }
        if (e.status === 503) {
          if (!stopped) setStatus("unconfigured");
          return true;
        }
      }
      return false;
    };

    const pollLoop = (src: "live" | "overview") => {
      const tick = async () => {
        if (stopped) return;
        try {
          if (src === "live") {
            const snap = await fetchLive(conn, pollCtrl.signal);
            apply(fromLive(snap), "poll");
          } else {
            const ov = await fetchOverview(conn, pollCtrl.signal);
            apply(fromOverview(ov, new Date().toISOString()), "poll");
          }
        } catch (e) {
          if (handleFatal(e)) return;
          if (!stopped) {
            setStatus("error");
            setError((e as Error).message ?? "Falha de rede");
          }
        }
        if (!stopped) pollTimer = setTimeout(tick, intervalRef.current);
      };
      void tick();
    };

    const fallbackToPollLive = () => {
      if (settledFallback || stopped) return;
      settledFallback = true;
      if (watchdog) clearTimeout(watchdog);
      streamCtrl?.abort();
      pollLoop("live");
    };

    const startStream = () => {
      streamCtrl = new AbortController();
      let gotFrame = false;
      watchdog = setTimeout(() => {
        if (!gotFrame) fallbackToPollLive();
      }, 6000);

      void streamSSE(
        conn,
        "/admin/workers/stream?interval=1.5",
        {
          onFrame: (data) => {
            gotFrame = true;
            try {
              const snap = JSON.parse(data) as LiveSnapshot;
              apply(fromLive(snap), "stream");
            } catch {
              /* ignore malformed frame */
            }
          },
          onError: () => fallbackToPollLive(),
        },
        streamCtrl.signal,
      ).then(() => {
        // Stream closed by the server (or aborted). If it was working, degrade
        // gracefully to polling the live endpoint.
        if (!stopped && !streamCtrl?.signal.aborted) fallbackToPollLive();
      });
    };

    const boot = async () => {
      try {
        const snap = await fetchLive(conn, pollCtrl.signal);
        apply(fromLive(snap), preferStream ? "stream" : "poll");
        if (preferStream) startStream();
        else pollLoop("live");
      } catch (e) {
        if ((e as Error)?.name === "AbortError") return;
        if (e instanceof ApiError) {
          if (e.status === 401) {
            setStatus("unauthorized");
            return;
          }
          if (e.status === 503) {
            setStatus("unconfigured");
            return;
          }
          if (e.status === 404 || e.status === 405 || e.status === 501) {
            // Live telemetry not wired — use the always-present overview.
            pollLoop("overview");
            return;
          }
        }
        // Network/other: the live endpoint may be unreachable; try overview so
        // the console still shows queue/DLQ/season data.
        pollLoop("overview");
      }
    };

    void boot();

    return () => {
      stopped = true;
      if (pollTimer) clearTimeout(pollTimer);
      if (watchdog) clearTimeout(watchdog);
      pollCtrl.abort();
      streamCtrl?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conn.id, conn.base, conn.key, preferStream, nonce]);

  return { telemetry, history, status, transport, source, error, frames };
}
