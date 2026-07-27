import { useEffect, useState } from "react";
import type { BackendId, Conn } from "../lib/backend";
import { displayOrigin } from "../lib/backend";

interface Props {
  conn: Conn;
  preferStream: boolean;
  intervalMs: number;
  onBackend: (id: BackendId) => void;
  onUrl: (url: string) => void;
  onToggleStream: (v: boolean) => void;
  onInterval: (ms: number) => void;
  onReconnect: () => void;
  onChangeKey: () => void;
  onClose: () => void;
}

const BACKENDS: { id: BackendId; label: string }[] = [
  { id: "local", label: "Local" },
  { id: "production", label: "Produção" },
  { id: "custom", label: "Custom" },
];

const INTERVALS = [1000, 1500, 2000, 3000, 5000];

export function ConnectionDrawer(props: Props) {
  const {
    conn,
    preferStream,
    intervalMs,
    onBackend,
    onUrl,
    onToggleStream,
    onInterval,
    onReconnect,
    onChangeKey,
    onClose,
  } = props;

  const editable = conn.id === "production" || conn.id === "custom";
  const [urlDraft, setUrlDraft] = useState(conn.base);
  useEffect(() => setUrlDraft(conn.base), [conn.base, conn.id]);

  return (
    <div className="drawer-overlay">
      <button type="button" className="drawer-scrim" aria-label="Fechar painel de conexão" onClick={onClose} />
      <aside className="drawer">
        <div className="drawer-head">
          <div>
            <h2>Conexão</h2>
            <p>Backend, transporte e chave de admin. Nada aqui altera os endpoints.</p>
          </div>
          <button type="button" className="drawer-close" onClick={onClose} aria-label="Fechar">
            <span className="ms ms-18" aria-hidden="true">
              close
            </span>
          </button>
        </div>

        <div className="drawer-section">
          <span className="drawer-label">Ambiente</span>
          <div className="seg" role="tablist" aria-label="Backend">
            {BACKENDS.map((b) => (
              <button
                key={b.id}
                type="button"
                role="tab"
                aria-selected={conn.id === b.id}
                className={conn.id === b.id ? "seg-on" : ""}
                onClick={() => onBackend(b.id)}
              >
                {b.label}
              </button>
            ))}
          </div>
        </div>

        <div className="drawer-section">
          <span className="drawer-label">URL do backend</span>
          {editable ? (
            <input
              className="drawer-input"
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
            <input className="drawer-input" value={displayOrigin(conn)} readOnly aria-label="URL do backend" />
          )}
        </div>

        <div className="drawer-section">
          <span className="drawer-label">Transporte</span>
          <label className="drawer-toggle">
            <input
              type="checkbox"
              checked={preferStream}
              onChange={(e) => onToggleStream(e.target.checked)}
            />
            <span>Preferir stream SSE</span>
            <span className="drawer-toggle-note">fallback automático</span>
          </label>
        </div>

        <div className="drawer-section">
          <span className="drawer-label">Cadência do polling</span>
          <div className="drawer-chips">
            {INTERVALS.map((ms) => (
              <button
                key={ms}
                type="button"
                className={intervalMs === ms ? "drawer-chip drawer-chip-on" : "drawer-chip"}
                onClick={() => onInterval(ms)}
              >
                {ms >= 1000 ? `${ms / 1000}s` : `${ms}ms`}
              </button>
            ))}
          </div>
        </div>

        <div className="drawer-actions">
          <button type="button" className="btn-primary" onClick={onReconnect}>
            <span className="ms ms-17" aria-hidden="true">
              refresh
            </span>
            Reconectar
          </button>
          <button type="button" className="btn-secondary" onClick={onChangeKey}>
            <span className="ms ms-17" aria-hidden="true">
              key
            </span>
            Trocar chave de admin
          </button>
          <p className="drawer-note">
            A chave fica apenas no localStorage deste navegador e viaja no header X-Admin-Key.
          </p>
        </div>
      </aside>
    </div>
  );
}
