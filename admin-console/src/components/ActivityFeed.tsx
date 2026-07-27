import type { AuditEventInfo } from "../lib/types";
import { timeAgo } from "../lib/format";

interface Props {
  events: AuditEventInfo[];
}

/** Same audit rows as AuditLogPanel, timeline-styled instead of table-styled
 *  — newest-first, unfiltered (the table view is where filtering lives). */
export function ActivityFeed({ events }: Props) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Feed de atividade</h2>
        <span className="panel-note">{events.length} eventos</span>
      </div>
      <div className="activity-list">
        {events.length === 0 && <div className="empty">Nenhuma atividade registrada.</div>}
        {events.map((e, i) => (
          <div className="activity-row" key={e.id}>
            <div className="activity-when">{timeAgo(e.occurredAt)}</div>
            <div className="activity-rail">
              <span className="activity-tick" style={{ visibility: i === 0 ? "hidden" : "visible" }} />
              <span className={`activity-dot kind-${e.kind}`} />
              <span
                className="activity-tick"
                style={{ visibility: i === events.length - 1 ? "hidden" : "visible" }}
              />
            </div>
            <div className="activity-body">
              <div className="activity-title">{e.action}</div>
              <div className="activity-detail">
                {e.target ?? "—"} · {e.result}
              </div>
              <div className="activity-actor">{e.actor}</div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
