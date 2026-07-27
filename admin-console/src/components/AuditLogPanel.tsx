import { useState } from "react";
import type { AuditEventInfo, AuditKind } from "../lib/types";
import { timeAgo } from "../lib/format";

const KIND_CHIPS: { id: AuditKind | "all"; label: string }[] = [
  { id: "all", label: "Tudo" },
  { id: "workers", label: "Workers" },
  { id: "moderacao", label: "Moderação" },
  { id: "dlq", label: "DLQ" },
  { id: "temporada", label: "Temporada" },
  { id: "campeonatos", label: "Campeonatos" },
  { id: "acesso", label: "Acesso" },
];

interface Props {
  events: AuditEventInfo[];
}

export function AuditLogPanel({ events }: Props) {
  const [filter, setFilter] = useState<AuditKind | "all">("all");
  const rows = filter === "all" ? events : events.filter((e) => e.kind === filter);

  return (
    <section className="panel">
      <div className="audit-chips">
        {KIND_CHIPS.map((c) => (
          <button
            key={c.id}
            type="button"
            className={filter === c.id ? "drawer-chip drawer-chip-on" : "drawer-chip"}
            onClick={() => setFilter(c.id)}
          >
            {c.label}
          </button>
        ))}
        <span className="panel-note" style={{ marginLeft: "auto" }}>
          {rows.length} de {events.length} eventos
        </span>
      </div>

      <div className="audit-grid">
        <div className="audit-head">
          <div>Quando</div>
          <div>Operador</div>
          <div>Ação</div>
          <div>Alvo</div>
          <div>Origem</div>
          <div>Resultado</div>
        </div>
        {rows.length === 0 && <div className="empty">Nenhum evento registrado.</div>}
        {rows.map((e) => (
          <div className="audit-row" key={e.id}>
            <span className="audit-when">{timeAgo(e.occurredAt)}</span>
            <span className="audit-actor">{e.actor}</span>
            <span className={`audit-action kind-${e.kind}`}>{e.action}</span>
            <span className="audit-target">{e.target ?? "—"}</span>
            <span className="audit-ip">{e.sourceIp ?? "—"}</span>
            <span
              className={`audit-result ${e.result === "ok" ? "audit-result-ok" : "audit-result-denied"}`}
            >
              {e.result}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
