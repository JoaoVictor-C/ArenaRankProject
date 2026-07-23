import { useEffect, useState } from "react";
import type { BackendId, Conn } from "../lib/backend";
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
  preferStream: boolean;
  onBackend: (id: BackendId) => void;
  onUrl: (url: string) => void;
  onInterval: (ms: number) => void;
  onToggleStream: (v: boolean) => void;
  onReconnect: () => void;
  onChangeKey: () => void;
}

const BACKENDS: { id: BackendId; label: string }[] = [
  { id: "local", label: "Local" },
  { id: "production", label: "Produção" },
  { id: "custom", label: "Custom" },
];

const INTERVALS = [1000, 1500, 2000, 3000, 5000];

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
  const {
    conn,
    status,
    transport,
    source,
    frames,
    lastTs,
    intervalMs,
    preferStream,
    onBackend,
    onUrl,
    onInterval,
    onToggleStream,
    onReconnect,
    onChangeKey,
  } = props;

  const editable = conn.id === "production" || conn.id === "custom";
  const [urlDraft, setUrlDraft] = useState(conn.base);
  useEffect(() => setUrlDraft(conn.base), [conn.base, conn.id]);

  const { tone, label } = statusInfo(status, transport, source, intervalMs);

  return (
    <header className="topbar">
      <div className="tb-brand">
        <span className="tb-logo" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <div className="tb-brand-text">
          <strong>ARENA·OPS</strong>
          <small>console de operações</small>
        </div>
      </div>

      <div className="tb-backend">
        <div className="seg" role="tablist" aria-label="Backend">
          {BACKENDS.map((b) => (
            <button
              key={b.id}
              role="tab"
              aria-selected={conn.id === b.id}
              className={conn.id === b.id ? "seg-on" : ""}
              onClick={() => onBackend(b.id)}
              type="button"
            >
              {b.label}
            </button>
          ))}
        </div>
        {editable ? (
          <input
            className="tb-url"
            value={urlDraft}
            placeholder="https://api.exemplo.com"
            spellCheck={false}
            onChange={(e) => setUrlDraft(e.target.value)}
            onBlur={() => onUrl(urlDraft)}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            }}
            aria-label="URL do backend"
          />
        ) : (
          <span className="tb-origin" title={displayOrigin(conn)}>
            {displayOrigin(conn)}
          </span>
        )}
      </div>

      <div className="tb-status">
        <span className={`conn conn-${tone}`}>
          <span key={frames} className="hb" aria-hidden="true" />
          <span className="conn-label">{label}</span>
        </span>
        <span className="tb-clock tnum" title="Horário do último frame recebido">
          {clock(lastTs)}
        </span>
      </div>

      <div className="tb-controls">
        <label className="ctl" title="Tentar o stream SSE (com fallback automático para polling)">
          <input
            type="checkbox"
            checked={preferStream}
            onChange={(e) => onToggleStream(e.target.checked)}
          />
          <span>Stream</span>
        </label>
        <select
          className="ctl-select"
          value={intervalMs}
          onChange={(e) => onInterval(Number(e.target.value))}
          aria-label="Intervalo de atualização"
          title="Cadência do polling (fallback)"
        >
          {INTERVALS.map((ms) => (
            <option key={ms} value={ms}>
              {ms >= 1000 ? `${ms / 1000}s` : `${ms}ms`}
            </option>
          ))}
        </select>
        <button className="btn-ghost" type="button" onClick={onReconnect} title="Reconectar">
          ↻
        </button>
        <button className="btn-ghost" type="button" onClick={onChangeKey} title="Trocar chave de admin">
          🔑
        </button>
      </div>
    </header>
  );
}
