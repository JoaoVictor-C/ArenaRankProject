import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError, clearAdminKey, getAdminKey, setAdminKey } from "../lib/api";
import "./AdminGate.css";

type Phase = "checking" | "locked" | "authed";

/**
 * Porta de acesso do painel administrativo. A aplicação ainda não tem login de
 * usuário — o backend protege `/admin/*` com uma chave compartilhada
 * (`X-Admin-Key`). Este componente coleta a chave, valida-a contra a API e só
 * então renderiza o painel. A segurança real é no servidor; isto é a guarda de
 * UX no cliente (evita expor a tela do painel sem chave válida).
 */
export function AdminGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>(getAdminKey() ? "checking" : "locked");
  const [keyInput, setKeyInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Revalida uma chave já armazenada ao montar (StrictMode-safe via `alive`).
  useEffect(() => {
    if (!getAdminKey()) return;
    let alive = true;
    api.adminOverview().then(
      () => {
        if (alive) setPhase("authed");
      },
      (err: unknown) => {
        if (!alive) return;
        clearAdminKey();
        setPhase("locked");
        if (err instanceof ApiError && err.status === 503) {
          setError("Acesso administrativo não está configurado no servidor.");
        }
      },
    );
    return () => {
      alive = false;
    };
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setAdminKey(keyInput);
    try {
      await api.adminOverview();
      setPhase("authed");
    } catch (err) {
      clearAdminKey();
      if (err instanceof ApiError && err.status === 503) {
        setError("Acesso administrativo não está configurado no servidor (defina ADMIN_API_KEY).");
      } else if (err instanceof ApiError && err.status === 401) {
        setError("Chave inválida.");
      } else {
        setError("Falha ao validar a chave. Tente novamente.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (phase === "authed") return <>{children}</>;

  if (phase === "checking") {
    return (
      <div className="admin-gate">
        <p className="admin-gate-checking">Verificando acesso…</p>
      </div>
    );
  }

  return (
    <div className="admin-gate">
      <form className="admin-gate-card" onSubmit={onSubmit}>
        <h1 className="admin-gate-title">Acesso administrativo</h1>
        <p className="admin-gate-sub">Informe a chave de administrador para continuar.</p>
        <input
          className="admin-gate-input"
          type="password"
          autoFocus
          value={keyInput}
          onChange={(e) => setKeyInput(e.target.value)}
          placeholder="ADMIN_API_KEY"
          aria-label="Chave de administrador"
        />
        {error && <p className="admin-gate-error">{error}</p>}
        <button
          className="admin-gate-btn"
          type="submit"
          disabled={submitting || !keyInput.trim()}
        >
          {submitting ? "Verificando…" : "Entrar"}
        </button>
      </form>
    </div>
  );
}
