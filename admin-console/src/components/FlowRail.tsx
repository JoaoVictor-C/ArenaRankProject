/* Signature hero: the match-processing pipeline as a live flow rail.
   Discovery (sweeps) → arq queue (arena:standard/priority) → continuous
   processing (StandardWorker/PriorityWorker) → processed / DLQ.
   StandardWorker/PriorityWorker have no LiveWorker entity (arq consumers, no
   cron tick, no pause) — the "Processamento" stage is informational only; the
   queue depth is the real signal for how much work is in flight.
   Discovery and the final outcome are STATUS stages (state, not a raw count —
   the sweeps' own volume already shows up one stage over, in the queue), while
   Fila and DLQ are the two real counted quantities in the pipeline. Keeping
   that distinction explicit avoids the old design's tell: a hero number that
   reads "0" or "—" even when the stage is healthy and busy. */
import type { ReactNode } from "react";
import type { NormWorker, Telemetry } from "../lib/types";
import { fmtInt, dur } from "../lib/format";

function worker(t: Telemetry, name: string): NormWorker | undefined {
  return t.workers.find((w) => w.name === name);
}

type Tone = "cyan" | "green" | "amber" | "red" | "violet";
type StageState = "active" | "paused" | "idle";

function stageState(active?: boolean, paused?: boolean): StageState {
  return paused ? "paused" : active ? "active" : "idle";
}

/* ---- minimal inline icon set (no icon dependency in this app) ---- */
function IconRadar() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="1.5" fill="currentColor" />
      <path d="M8 8V2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M4.6 4.6a5 5 0 0 1 6.8 0" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" opacity="0.7" />
      <path d="M2.3 2.3a8 8 0 0 1 11.4 0" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" opacity="0.4" />
    </svg>
  );
}
function IconLayers() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M8 2 13.5 5 8 8 2.5 5Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M2.5 8 8 11 13.5 8" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M2.5 11 8 14 13.5 11" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" opacity="0.55" />
    </svg>
  );
}
function IconCpu() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="4" y="4" width="8" height="8" rx="1.3" stroke="currentColor" strokeWidth="1.3" />
      <rect x="6.4" y="6.4" width="3.2" height="3.2" rx="0.5" fill="currentColor" />
      <path d="M8 1v2.2M8 12.8V15M1 8h2.2M12.8 8H15" stroke="currentColor" strokeWidth="1" strokeLinecap="round" opacity="0.6" />
    </svg>
  );
}
function IconCheck() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="6.1" stroke="currentColor" strokeWidth="1.3" />
      <path d="M5.2 8.3 7.1 10.2 10.9 6.1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
function IconAlert() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M8 2.1 14.4 13.3H1.6Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M8 6.3v3.1" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <circle cx="8" cy="11.1" r="0.85" fill="currentColor" />
    </svg>
  );
}

function StageHead({ icon, kicker, state }: { icon: ReactNode; kicker: string; state: StageState }) {
  return (
    <div className="stage-head">
      <span className="stage-icon">{icon}</span>
      <span className="stage-kicker">
        <span className="led" data-state={state} />
        {kicker}
      </span>
    </div>
  );
}

/* A stage carrying a real counted quantity (Fila). */
function StatStage({
  icon,
  kicker,
  title,
  value,
  unit,
  tone,
  active,
  paused,
  sub,
}: {
  icon: ReactNode;
  kicker: string;
  title: string;
  value: number | null;
  unit: string;
  tone: Tone;
  active?: boolean;
  paused?: boolean;
  sub?: string;
}) {
  const state = stageState(active, paused);
  return (
    <div className={`stage-card tone-${tone}`} data-state={state} data-kind="stat">
      <StageHead icon={icon} kicker={kicker} state={state} />
      <div className="stage-title">{title}</div>
      <div className="stage-value tnum">
        {value === null ? "—" : fmtInt(value)}
        <span className="stage-unit">{unit}</span>
      </div>
      {sub && <div className="stage-sub">{sub}</div>}
    </div>
  );
}

/* A stage that reports state rather than a count (Descoberta / Processamento). */
function StatusStage({
  icon,
  kicker,
  title,
  tone,
  active,
  paused,
  children,
}: {
  icon: ReactNode;
  kicker: string;
  title: string;
  tone: Tone;
  active?: boolean;
  paused?: boolean;
  children?: ReactNode;
}) {
  const state = stageState(active, paused);
  return (
    <div className={`stage-card tone-${tone}`} data-state={state} data-kind="status">
      <StageHead icon={icon} kicker={kicker} state={state} />
      <div className="stage-title">{title}</div>
      <div className="stage-body">{children}</div>
    </div>
  );
}

function WorkerRow({ label, w }: { label: string; w: NormWorker | undefined }) {
  const state = stageState(w?.active, w?.paused);
  const text = w?.paused ? "pausado" : w?.active ? `próx. tick ${dur(w.tickLockTtl)}` : "ocioso";
  return (
    <div className="stage-wrow">
      <span className="led" data-state={state} />
      <span className="stage-wname">{label}</span>
      <span className="stage-wstate tnum">{text}</span>
    </div>
  );
}

function FlowBeam({ flowing, tone, label }: { flowing: boolean; tone: string; label?: string }) {
  return (
    <div className={`flow-beam tone-${tone}`} data-flowing={flowing}>
      <svg viewBox="0 0 100 24" preserveAspectRatio="none" aria-hidden="true">
        <line x1="0" y1="12" x2="100" y2="12" className="beam-base" />
        <line x1="0" y1="12" x2="100" y2="12" className="beam-flow" />
        <path d="M93 7 L100 12 L93 17" className="beam-arrow" />
      </svg>
      {label && <span className="beam-label">{label}</span>}
    </div>
  );
}

function FlowFork({ okFlowing, errFlowing }: { okFlowing: boolean; errFlowing: boolean }) {
  return (
    <div className="flow-fork" aria-hidden="true">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none">
        <path d="M0 50 C 42 50, 55 24, 100 24" className="fork-base" />
        <path d="M0 50 C 42 50, 55 76, 100 76" className="fork-base" />
        <path d="M0 50 C 42 50, 55 24, 100 24" className="fork-flow fork-flow-ok" data-flowing={okFlowing} />
        <path d="M0 50 C 42 50, 55 76, 100 76" className="fork-flow fork-flow-err" data-flowing={errFlowing} />
      </svg>
      <span className="fork-label fork-label-ok">ok</span>
      <span className="fork-label fork-label-err">falhou</span>
    </div>
  );
}

export function FlowRail({ t, processedToday }: { t: Telemetry; processedToday?: number | null }) {
  const sweep = worker(t, "sweep");
  const prio = worker(t, "priority_sweep");

  const pendingPri = t.pipeline.priorityQueue;
  const pendingStd = t.pipeline.standardQueue;
  const pendingTotal = pendingPri + pendingStd;
  const dlq = t.pipeline.dlq;

  const discoveryActive = !!(sweep?.active || prio?.active);
  const discoveryPaused = !!(sweep?.paused && prio?.paused);
  const hasPending = pendingTotal > 0;

  return (
    <section className="flowrail panel">
      <div className="panel-head">
        <h2>Pipeline de partidas</h2>
        <span className="panel-note">
          {t.source === "live"
            ? "estado real do Redis · descoberta → fila → processamento → resultado"
            : "telemetria parcial (endpoint ao vivo não conectado)"}
        </span>
      </div>

      <div className="flow-stage">
        <StatusStage icon={<IconRadar />} kicker="Descoberta" title="Sweeps" tone="cyan" active={discoveryActive} paused={discoveryPaused}>
          <WorkerRow label="Sweep padrão" w={sweep} />
          <WorkerRow label="Sweep prioritário" w={prio} />
        </StatusStage>

        <FlowBeam flowing={discoveryActive || hasPending} tone="cyan" label="match ids" />

        <StatStage
          icon={<IconLayers />}
          kicker="Fila"
          title="arena:standard/priority"
          value={pendingTotal}
          unit="partidas"
          tone="amber"
          active={hasPending}
          sub={`pri ${fmtInt(pendingPri)} · padrão ${fmtInt(pendingStd)}`}
        />

        <FlowBeam flowing={hasPending} tone="amber" label="consome" />

        <StatusStage icon={<IconCpu />} kicker="Processamento" title="StandardWorker / PriorityWorker" tone="green" active={hasPending}>
          <div className="stage-note tnum">process_match</div>
          <div className="stage-sub">consumidor contínuo · sem tick</div>
        </StatusStage>

        <FlowFork okFlowing={hasPending} errFlowing={dlq > 0} />

        <div className="stage-card tone-green stage-outcome" data-state={hasPending ? "active" : "idle"}>
          <div className="stage-outcome-row" data-tone="green">
            <span className="stage-outcome-icon">
              <IconCheck />
            </span>
            <div className="stage-outcome-text">
              <div className="stage-outcome-label">Processadas</div>
              <div className="stage-sub">hoje · → ratings / DB</div>
            </div>
            <div className="stage-outcome-value tnum">
              {processedToday == null ? "—" : fmtInt(processedToday)}
            </div>
          </div>
          <div className="stage-outcome-divider" />
          <div className="stage-outcome-row" data-tone="red" data-alert={dlq > 0}>
            <span className="stage-outcome-icon">
              <IconAlert />
            </span>
            <div className="stage-outcome-text">
              <div className="stage-outcome-label">DLQ</div>
              <div className="stage-sub">{dlq > 0 ? "requer revisão" : "fila limpa"}</div>
            </div>
            <div className="stage-outcome-value tnum">
              {fmtInt(dlq)}
              <span className="stage-unit">presas</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
