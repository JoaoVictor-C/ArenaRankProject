import { useEffect, useState } from "react";
import type { Conn } from "../lib/backend";
import { pauseWorker, resumeWorker } from "../lib/actions";
import type { NormWorker, TelemetrySource } from "../lib/types";
import { SourceBadge } from "./SourceBadge";
import { dur, fmtInt, fmtPct } from "../lib/format";

interface Props {
  workers: NormWorker[];
  conn: Conn;
  onMutated: () => void;
  /** Procedência da telemetria — ver SourceBadge. */
  dataSource?: TelemetrySource;
  ageSeconds?: number | null;
}

const HEALTH_LABEL: Record<string, string> = {
  active: "processando",
  idle: "ocioso",
  paused: "pausado",
  warn: "alta carga",
  down: "indisponível",
};

function WorkerCard({
  w,
  conn,
  onMutated,
}: {
  w: NormWorker;
  conn: Conn;
  onMutated: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // What we just asked the backend for, held until telemetry catches up.
  // Without it the card keeps rendering the pre-click snapshot until the next
  // frame lands, so "Retomar" stays on screen after a successful resume and the
  // control reads as broken (and a second click fires a redundant request).
  const [optimisticPaused, setOptimisticPaused] = useState<boolean | null>(null);

  // Drop the override as soon as the server-sent state agrees with it.
  useEffect(() => {
    if (optimisticPaused !== null && w.paused === optimisticPaused) setOptimisticPaused(null);
  }, [w.paused, optimisticPaused]);

  const paused = optimisticPaused ?? w.paused;
  const health = optimisticPaused === null ? w.health : optimisticPaused ? "paused" : "idle";

  async function toggle() {
    const next = !paused;
    setBusy(true);
    setErr(null);
    try {
      if (paused) await resumeWorker(conn, w.name);
      else await pauseWorker(conn, w.name);
      setOptimisticPaused(next);
      onMutated();
    } catch (e) {
      setErr((e as Error).message);
      setOptimisticPaused(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="worker" data-health={health}>
      <header className="wk-head">
        <span className={`led led-health led-${health}`} />
        <div className="wk-id">
          <div className="wk-name">{w.label}</div>
          <code className="wk-code">{w.name}</code>
        </div>
        <span className={`wk-badge badge-${health}`}>{HEALTH_LABEL[health] ?? health}</span>
      </header>

      {w.description && <p className="wk-desc">{w.description}</p>}

      <dl className="wk-stats">
        <div>
          <dt>Tick</dt>
          <dd className="tnum">{w.active ? dur(w.tickLockTtl) || "ativo" : "—"}</dd>
        </div>
        <div>
          <dt>Backlog</dt>
          <dd className="tnum">{fmtInt(w.pending)}</dd>
        </div>
        {w.attemptsTracked !== null && (
          <div>
            <dt>Em curso</dt>
            <dd className="tnum">{fmtInt(w.attemptsTracked)}</dd>
          </div>
        )}
        {w.cursor !== null && (
          <div>
            <dt>Cursor</dt>
            <dd className="tnum">{fmtInt(w.cursor)}</dd>
          </div>
        )}
        {w.intervalMinutes !== null && (
          <div>
            <dt>Cadência</dt>
            <dd className="tnum">{w.intervalMinutes}min</dd>
          </div>
        )}
        {w.load !== null && (
          <div>
            <dt>Carga</dt>
            <dd className="tnum">{fmtPct(w.load)}</dd>
          </div>
        )}
      </dl>

      {w.feeds && <div className="wk-feeds">→ {w.feeds}</div>}

      <footer className="wk-foot">
        {w.controllable ? (
          <button
            className={`wk-btn ${paused ? "is-resume" : "is-pause"}`}
            type="button"
            disabled={busy}
            onClick={toggle}
          >
            {busy ? "…" : paused ? "Retomar" : "Pausar"}
          </button>
        ) : (
          <span className="wk-note">somente leitura</span>
        )}
        {err && <span className="wk-err">{err}</span>}
      </footer>
    </article>
  );
}

export function WorkersPanel({ workers, conn, onMutated, dataSource, ageSeconds }: Props) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Workers &amp; processadores</h2>
        <span className="panel-note">{workers.length} pools · pausa/retomada em tempo real</span>
        <SourceBadge source={dataSource} ageSeconds={ageSeconds} what="telemetria de workers" />
      </div>
      <div className="worker-grid">
        {workers.length === 0 && <div className="empty">Sem workers reportados.</div>}
        {workers.map((w) => (
          <WorkerCard key={w.name} w={w} conn={conn} onMutated={onMutated} />
        ))}
      </div>
    </section>
  );
}
