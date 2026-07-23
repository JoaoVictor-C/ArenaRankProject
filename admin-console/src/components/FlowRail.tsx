/* Signature hero: the match-processing pipeline as a live flow rail.
   Discovery (sweeps) → pending queue → bulk processor → processed / DLQ.
   Connectors animate while the adjacent stage is active or carrying backlog. */
import type { NormWorker, Telemetry } from "../lib/types";
import { fmtInt } from "../lib/format";

function worker(t: Telemetry, name: string): NormWorker | undefined {
  return t.workers.find((w) => w.name === name);
}

interface NodeProps {
  kicker: string;
  title: string;
  value: number | null;
  unit: string;
  tone: "cyan" | "green" | "amber" | "red" | "violet";
  active?: boolean;
  paused?: boolean;
  sub?: string;
}

function Node({ kicker, title, value, unit, tone, active, paused, sub }: NodeProps) {
  const state = paused ? "paused" : active ? "active" : "idle";
  return (
    <div className={`flow-node tone-${tone}`} data-state={state}>
      <div className="fn-kicker">
        <span className={`led led-${tone}`} data-state={state} />
        {kicker}
      </div>
      <div className="fn-title">{title}</div>
      <div className="fn-value tnum">
        {value === null ? "—" : fmtInt(value)}
        <span className="fn-unit">{unit}</span>
      </div>
      {sub && <div className="fn-sub">{sub}</div>}
    </div>
  );
}

function Connector({ flowing, tone, label }: { flowing: boolean; tone: string; label?: string }) {
  return (
    <div className={`flow-link tone-${tone}`} data-flowing={flowing}>
      <svg viewBox="0 0 100 24" preserveAspectRatio="none" aria-hidden="true">
        <line x1="0" y1="12" x2="100" y2="12" className="fl-base" />
        <line x1="0" y1="12" x2="100" y2="12" className="fl-flow" />
      </svg>
      {label && <span className="fl-label">{label}</span>}
    </div>
  );
}

export function FlowRail({ t }: { t: Telemetry }) {
  const sweep = worker(t, "sweep");
  const prio = worker(t, "priority_sweep");
  const bulk = worker(t, "bulk_processor");

  const pendingPri = t.pipeline.sweepPendingPriority;
  const pendingStd = t.pipeline.sweepPendingStandard;
  const pendingTotal =
    pendingPri === null && pendingStd === null ? null : (pendingPri ?? 0) + (pendingStd ?? 0);

  const discoveryActive = !!(sweep?.active || prio?.active);
  const discoveryPaused = !!(sweep?.paused && prio?.paused);
  const bulkActive = !!bulk?.active;
  const hasPending = (pendingTotal ?? 0) > 0;

  return (
    <section className="flowrail panel">
      <div className="panel-head">
        <h2>Pipeline de partidas</h2>
        <span className="panel-note">
          {t.source === "live"
            ? "estado real do Redis · descoberta → fila → processamento"
            : "telemetria parcial (endpoint ao vivo não conectado)"}
        </span>
      </div>

      <div className="flow-track">
        <Node
          kicker="Descoberta"
          title="Sweeps"
          value={t.pipeline.topPlayersPool}
          unit="seeds"
          tone="cyan"
          active={discoveryActive}
          paused={discoveryPaused}
          sub={
            sweep || prio
              ? `padrão ${sweep?.paused ? "pausado" : sweep?.active ? "ativo" : "ocioso"} · prio ${
                  prio?.paused ? "pausado" : prio?.active ? "ativo" : "ocioso"
                }`
              : "varre jogadores rastreados"
          }
        />
        <Connector flowing={discoveryActive || hasPending} tone="cyan" label="match ids" />
        <Node
          kicker="Em espera"
          title="Fila pendente"
          value={pendingTotal}
          unit="ids"
          tone="amber"
          active={hasPending}
          sub={
            pendingPri === null
              ? "pri + padrão"
              : `pri ${fmtInt(pendingPri)} · padrão ${fmtInt(pendingStd)}`
          }
        />
        <Connector flowing={bulkActive || hasPending} tone="amber" label="drena" />
        <Node
          kicker="Processamento"
          title="Lote"
          value={t.pipeline.sweepAttemptsTracked}
          unit="em curso"
          tone="green"
          active={bulkActive}
          paused={!!bulk?.paused}
          sub={`process_match · ${bulk?.intervalMinutes ?? "—"}min`}
        />
        <div className="flow-split">
          <Connector flowing={bulkActive} tone="green" label="ok" />
          <Connector flowing={t.pipeline.dlq > 0} tone="red" label="falhou" />
        </div>
        <div className="flow-ends">
          <Node kicker="Saída" title="Processadas" value={null} unit="" tone="green" active={bulkActive} sub="→ ratings / DB" />
          <Node
            kicker="Erro"
            title="DLQ"
            value={t.pipeline.dlq}
            unit="presas"
            tone="red"
            active={t.pipeline.dlq > 0}
            sub={t.pipeline.dlq > 0 ? "requer revisão" : "fila limpa"}
          />
        </div>
      </div>
    </section>
  );
}
