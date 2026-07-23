import { useState } from "react";
import type { Conn } from "../lib/backend";
import { pauseWorker, resumeWorker } from "../lib/actions";
import type { NormWorker } from "../lib/types";
import { dur, fmtInt, fmtPct } from "../lib/format";

interface Props {
  workers: NormWorker[];
  conn: Conn;
  onMutated: () => void;
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

  async function toggle() {
    setBusy(true);
    setErr(null);
    try {
      if (w.paused) await resumeWorker(conn, w.name);
      else await pauseWorker(conn, w.name);
      onMutated();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="worker" data-health={w.health}>
      <header className="wk-head">
        <span className={`led led-health led-${w.health}`} />
        <div className="wk-id">
          <div className="wk-name">{w.label}</div>
          <code className="wk-code">{w.name}</code>
        </div>
        <span className={`wk-badge badge-${w.health}`}>{HEALTH_LABEL[w.health] ?? w.health}</span>
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
            className={`wk-btn ${w.paused ? "is-resume" : "is-pause"}`}
            type="button"
            disabled={busy}
            onClick={toggle}
          >
            {busy ? "…" : w.paused ? "Retomar" : "Pausar"}
          </button>
        ) : (
          <span className="wk-note">somente leitura</span>
        )}
        {err && <span className="wk-err">{err}</span>}
      </footer>
    </article>
  );
}

export function WorkersPanel({ workers, conn, onMutated }: Props) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Workers &amp; processadores</h2>
        <span className="panel-note">{workers.length} pools · pausa/retomada em tempo real</span>
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
