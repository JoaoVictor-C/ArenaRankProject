import type { Conn } from "../lib/backend";
import { displayOrigin } from "../lib/backend";
import type { Source, TeleStatus, Transport } from "../lib/useTelemetry";
import { clock } from "../lib/format";

interface Props {
  conn: Conn;
  status: TeleStatus;
  transport: Transport;
  source: Source;
  frames: number;
  lastTs: string | null;
  intervalMs: number;
  onOpenDrawer: () => void;
}

function statusInfo(
  status: TeleStatus,
  transport: Transport,
  source: Source,
  intervalMs: number,
): { tone: string; label: string } {
  switch (status) {
    case "idle":
      return { tone: "faint", label: "aguardando chave" };
    case "connecting":
      return { tone: "cyan", label: "conectando…" };
    case "error":
      return { tone: "red", label: "erro de rede" };
    case "unauthorized":
      return { tone: "red", label: "chave inválida" };
    case "unconfigured":
      return { tone: "red", label: "admin não configurado" };
    case "ok": {
      if (transport === "stream") return { tone: "green", label: "ao vivo · stream" };
      const every = `${(intervalMs / 1000).toFixed(intervalMs % 1000 ? 1 : 0)}s`;
      if (source === "overview") return { tone: "amber", label: `parcial · overview ${every}` };
      return { tone: "green", label: `ao vivo · poll ${every}` };
    }
    default:
      return { tone: "faint", label: "—" };
  }
}

export function TopBar(props: Props) {
  const { conn, status, transport, source, frames, lastTs, intervalMs, onOpenDrawer } = props;
  const { tone, label } = statusInfo(status, transport, source, intervalMs);

  return (
    <>
      <div className="admin-strip">
        <span className="ms ms-15" aria-hidden="true">
          lock
        </span>
        <span>PAINEL ADMINISTRATIVO</span>
        <span className="admin-strip-note">Autenticado via chave de admin</span>
      </div>

      <header className="masthead">
        <div className="mh-row1">
          <a href="#" className="mh-logo" aria-label="ArenaRank">
            <img src="/logo-wordmark.png" alt="ArenaRank" />
          </a>
          <div className="mh-badges">
            <span className="mh-badge mh-badge-primary">
              <span className="mh-badge-text">
                CONSOLE
                <sup>OPS</sup>
              </span>
            </span>
            <span className="mh-badge">
              <span className="mh-badge-text">ARENA 3V3</span>
            </span>
          </div>
          <span className="mh-region">BR</span>
        </div>

        <div className="mh-row2">
          <div className="mh-backend">
            <span className="mh-backend-label">Backend</span>
            <span className="mh-backend-value" title={displayOrigin(conn)}>
              {displayOrigin(conn)}
            </span>
          </div>

          <div className="mh-right">
            <span className={`conn conn-${tone}`}>
              <span key={frames} className="hb" aria-hidden="true" />
              <span className="conn-label">{label}</span>
            </span>
            <span className="tb-clock tnum" title="Horário do último frame recebido">
              {clock(lastTs)}
            </span>
            <button type="button" className="mh-conn-btn" onClick={onOpenDrawer}>
              <span className="ms ms-15" aria-hidden="true">
                tune
              </span>
              Conexão
            </button>
          </div>
        </div>
      </header>
    </>
  );
}
