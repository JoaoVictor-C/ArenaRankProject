import { useState } from "react";
import type { Conn } from "../lib/backend";
import { discardDlq, requeueDlq, reviewIntegrity } from "../lib/actions";
import type {
  AdminDlqItem,
  AdminFlag,
  AdminIntegrityItem,
  AdminMetric,
  AdminSeason,
} from "../lib/types";
import { timeAgo } from "../lib/format";

/* ---- Metric tiles (activePlayers / matchesToday / queueDepth / dlqDepth) ---- */
export function MetricsTiles({ metrics }: { metrics: AdminMetric[] }) {
  return (
    <div className="tiles">
      {metrics.map((m) => (
        <div className="tile" key={m.key}>
          <div className="tile-k">{m.label}</div>
          <div className="tile-v tnum">{m.value}</div>
          <code className="tile-id">{m.key}</code>
        </div>
      ))}
    </div>
  );
}

/* ---- Season ---- */
export function SeasonCard({ season }: { season: AdminSeason }) {
  const entries = Object.entries(season.config ?? {});
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Temporada</h2>
        <span className={`season-state st-${season.state.toLowerCase()}`}>{season.state}</span>
      </div>
      <div className="season-body">
        <div className="season-now">
          <div className="season-num tnum">T{season.current}</div>
          <div className="season-meta">iniciada {timeAgo(season.startedAt)}</div>
        </div>
        <div className="cfg-grid">
          {entries.length === 0 && <div className="empty">Sem configuração exposta.</div>}
          {entries.map(([k, v]) => (
            <div className="cfg" key={k}>
              <div className="cfg-k">{k}</div>
              <div className="cfg-v tnum">{v}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---- DLQ ---- */
export function DlqPanel({
  items,
  conn,
  onMutated,
}: {
  items: AdminDlqItem[];
  conn: Conn;
  onMutated: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function act(matchId: string, kind: "requeue" | "discard") {
    setBusy(matchId + kind);
    setErr(null);
    try {
      if (kind === "requeue") await requeueDlq(conn, matchId);
      else await discardDlq(conn, matchId);
      onMutated();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Dead-letter (DLQ)</h2>
        <span className="panel-note">{items.length} partidas presas · reprocessar é idempotente</span>
      </div>
      {err && <div className="row-err">{err}</div>}
      <div className="rows">
        {items.length === 0 && <div className="empty">DLQ vazia.</div>}
        {items.map((d) => (
          <div className="dlq-row" key={d.matchId}>
            <code className="dlq-id">{d.matchId}</code>
            <span className="dlq-reason" title={d.reason}>
              {d.reason}
            </span>
            <span className="dlq-attempts tnum">{d.attempts}×</span>
            <span className="dlq-ts">{timeAgo(d.ts)}</span>
            <span className="row-actions">
              <button
                className="mini is-primary"
                type="button"
                disabled={!!busy}
                onClick={() => act(d.matchId, "requeue")}
              >
                {busy === d.matchId + "requeue" ? "…" : "Reprocessar"}
              </button>
              <button
                className="mini is-danger"
                type="button"
                disabled={!!busy}
                onClick={() => act(d.matchId, "discard")}
              >
                {busy === d.matchId + "discard" ? "…" : "Descartar"}
              </button>
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ---- Integrity ---- */
export function IntegrityPanel({
  items,
  conn,
  onMutated,
}: {
  items: AdminIntegrityItem[];
  conn: Conn;
  onMutated: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function review(id: string) {
    setBusy(id);
    setErr(null);
    try {
      await reviewIntegrity(conn, id, "none");
      onMutated();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Fila de integridade</h2>
        <span className="panel-note">{items.length} eventos abertos</span>
      </div>
      {err && <div className="row-err">{err}</div>}
      <div className="rows">
        {items.length === 0 && <div className="empty">Nada para revisar.</div>}
        {items.map((it) => (
          <div className="integ-row" key={it.id} data-sev={it.severity}>
            <span className={`sev sev-${it.severity}`}>{it.severity}</span>
            <div className="integ-main">
              <div className="integ-reason">{it.reason}</div>
              <div className="integ-sub">
                {it.player} · {timeAgo(it.ts)}
              </div>
            </div>
            <button
              className="mini"
              type="button"
              disabled={!!busy}
              onClick={() => review(it.id)}
            >
              {busy === it.id ? "…" : "Revisar"}
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ---- Flags ---- */
export function FlagsPanel({ flags }: { flags: AdminFlag[] }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Flags de conta</h2>
        <span className="panel-note">{flags.length} jogadores sinalizados</span>
      </div>
      <div className="rows">
        {flags.length === 0 && <div className="empty">Nenhuma flag ativa.</div>}
        {flags.map((f) => (
          <div className="flag-row" key={f.id}>
            <span className={`sev sev-${f.severity}`}>{f.severity}</span>
            <span className="flag-player">{f.player}</span>
            <span className="flag-kind">{f.flag}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
