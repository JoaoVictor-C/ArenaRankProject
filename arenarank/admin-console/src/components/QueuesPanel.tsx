import type { NormQueue } from "../lib/types";
import type { History } from "../lib/useTelemetry";
import { Sparkline } from "./Sparkline";
import { fmtInt } from "../lib/format";

interface Props {
  queues: NormQueue[];
  history: History;
}

function queueTone(name: string): string {
  if (name.includes("dlq")) return "#ff5c5c";
  if (name.includes("priority")) return "#4cc2ff";
  if (name.includes("standard")) return "#3ddc84";
  return "#8b97a7";
}

export function QueuesPanel({ queues, history }: Props) {
  const last = (arr: number[]) => (arr.length ? arr[arr.length - 1] : 0);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Filas &amp; profundidade</h2>
        <span className="panel-note">arq + listas de sweep · histórico ao vivo</span>
      </div>

      <div className="trend-row">
        <div className="trend">
          <div className="trend-k">Backlog total</div>
          <div className="trend-v tnum">{fmtInt(last(history.backlog))}</div>
          <Sparkline data={history.backlog} color="#4cc2ff" />
        </div>
        <div className="trend">
          <div className="trend-k">Filas arq</div>
          <div className="trend-v tnum">{fmtInt(last(history.arqQueues))}</div>
          <Sparkline data={history.arqQueues} color="#3ddc84" />
        </div>
        <div className="trend">
          <div className="trend-k">Pendentes sweep</div>
          <div className="trend-v tnum">{fmtInt(last(history.sweepPending))}</div>
          <Sparkline data={history.sweepPending} color="#ffb020" />
        </div>
        <div className="trend">
          <div className="trend-k">DLQ</div>
          <div className="trend-v tnum">{fmtInt(last(history.dlq))}</div>
          <Sparkline data={history.dlq} color="#ff5c5c" />
        </div>
      </div>

      <div className="qlist">
        {queues.length === 0 && <div className="empty">Sem filas reportadas.</div>}
        {queues.map((q) => {
          const tone = queueTone(q.name);
          return (
            <div className="qrow" key={q.name}>
              <span className="qdot" style={{ background: tone }} />
              <div className="qmeta">
                <div className="qlabel">{q.label}</div>
                <code className="qname">{q.name}</code>
              </div>
              <span className="qkind">{q.kind}</span>
              <span className="qdepth tnum">{fmtInt(q.depth)}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
