import { useState, type FormEvent } from "react";
import { ApiError, displayOrigin, type BackendId, type Conn } from "../lib/backend";
import { fetchOverview } from "../lib/actions";
import type { TeleStatus } from "../lib/useTelemetry";

interface Props {
  conn: Conn;
  reason: TeleStatus;
  onBackend: (id: BackendId) => void;
  onUrl: (url: string) => void;
  onAuthed: (key: string) => void;
}

const BACKENDS: { id: BackendId; label: string }[] = [
  { id: "local", label: "Local" },
  { id: "production", label: "Produção" },
  { id: "custom", label: "Custom" },
];

const REASON_NOTE: Partial<Record<TeleStatus, string>> = {
  unauthorized: "Chave recusada pelo servidor.",
  unconfigured: "O servidor não tem ADMIN_API_KEY definido (defina-o e reinicie a API).",
  error: "Sem resposta do backend. Confira a URL e se a API está no ar.",
};

export function Gate({ conn, reason, onBackend, onUrl, onAuthed }: Props) {
  const [keyDraft, setKeyDraft] = useState("");
  const [urlDraft, setUrlDraft] = useState(conn.base);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(REASON_NOTE[reason] ?? null);

  const needsUrl = conn.id !== "local" && !urlDraft.trim();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    if (conn.id !== "local") onUrl(urlDraft);
    const probe: Conn = {
      ...conn,
      base: conn.id === "local" ? "" : urlDraft.trim().replace(/\/+$/, ""),
      key: keyDraft.trim(),
    };
    try {
      await fetchOverview(probe);
      onAuthed(keyDraft.trim());
    } catch (e2) {
      if (e2 instanceof ApiError) {
        if (e2.status === 401) setErr("Chave inválida.");
        else if (e2.status === 503)
          setErr("Acesso administrativo não configurado no servidor (defina ADMIN_API_KEY).");
        else setErr(e2.message);
      } else {
        setErr("Não foi possível alcançar o backend. Confira a URL e o CORS.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="gate">
      <form className="gate-card" onSubmit={submit}>
        <div className="gate-mark" aria-hidden="true">
          <i />
          <i />
          <i />
        </div>
        <h1>Console de Operações</h1>
        <p className="gate-sub">
          Painel administrativo em tempo real do pipeline ArenaRank. Selecione o backend e informe a
          chave de administrador.
        </p>

        <div className="seg gate-seg" role="tablist" aria-label="Backend">
          {BACKENDS.map((b) => (
            <button
              key={b.id}
              type="button"
              role="tab"
              aria-selected={conn.id === b.id}
              className={conn.id === b.id ? "seg-on" : ""}
              onClick={() => {
                onBackend(b.id);
                setErr(null);
              }}
            >
              {b.label}
            </button>
          ))}
        </div>

        {conn.id === "local" ? (
          <div className="gate-origin">Alvo: {displayOrigin(conn)}</div>
        ) : (
          <label className="gate-field">
            <span>URL do backend</span>
            <input
              type="url"
              value={urlDraft}
              onChange={(e) => setUrlDraft(e.target.value)}
              placeholder="https://api.arenarank.lol"
              spellCheck={false}
              autoComplete="off"
            />
          </label>
        )}

        <label className="gate-field">
          <span>Chave de administrador (X-Admin-Key)</span>
          <input
            type="password"
            value={keyDraft}
            onChange={(e) => setKeyDraft(e.target.value)}
            placeholder="ADMIN_API_KEY"
            autoFocus
            autoComplete="off"
          />
        </label>

        {err && <div className="gate-err">{err}</div>}

        <button className="gate-btn" type="submit" disabled={busy || !keyDraft.trim() || needsUrl}>
          {busy ? "Verificando…" : "Entrar"}
        </button>
        <p className="gate-foot">
          A chave fica só neste navegador (localStorage), por backend. A autorização real é no
          servidor.
        </p>
      </form>
    </div>
  );
}
