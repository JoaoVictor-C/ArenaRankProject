import { useState } from "react";
import type { Conn } from "../lib/backend";
import { createOperator, revokeOperator } from "../lib/operatorActions";
import type { OperatorInfo, OperatorRole, PermissionRow } from "../lib/types";
import { timeAgo } from "../lib/format";

const ROLE_ORDER: OperatorRole[] = ["owner", "admin", "moderator", "analyst", "support"];
const ROLE_LABEL: Record<OperatorRole, string> = {
  owner: "Owner",
  admin: "Admin",
  moderator: "Moderador",
  analyst: "Analista",
  support: "Suporte",
};

interface Props {
  operators: OperatorInfo[];
  permissions: PermissionRow[];
  conn: Conn;
  onMutated: () => void;
}

export function RolesPermissionsPanel({ operators, permissions, conn, onMutated }: Props) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<OperatorRole>("support");
  const [creating, setCreating] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<{ email: string; apiKey: string } | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setCreating(true);
    setErr(null);
    try {
      const result = await createOperator(conn, { email: email.trim(), role });
      setRevealed({ email: result.email, apiKey: result.apiKey });
      setEmail("");
      onMutated();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setCreating(false);
    }
  }

  async function revoke(id: string) {
    setBusyId(id);
    setErr(null);
    try {
      await revokeOperator(conn, id);
      onMutated();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <h2>Matriz de permissões</h2>
          <span className="panel-note">Aplicada no backend a cada requisição admin</span>
        </div>
        <div className="perm-grid">
          <div className="perm-head">
            <div>Permissão</div>
            {ROLE_ORDER.map((r) => (
              <div key={r}>{ROLE_LABEL[r]}</div>
            ))}
          </div>
          {permissions.map((p) => (
            <div className="perm-row" key={p.scope}>
              <div>
                {p.label}
                <span className="perm-scope">{p.scope}</span>
              </div>
              {ROLE_ORDER.map((r) => (
                <div key={r} className={`perm-cell ${p.roles.includes(r) ? "perm-yes" : "perm-no"}`}>
                  {p.roles.includes(r) ? "✓" : "—"}
                </div>
              ))}
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Operadores</h2>
          <span className="panel-note">{operators.length} chaves ativas ou revogadas</span>
        </div>

        {revealed && (
          <div className="op-key-reveal">
            <code>{revealed.apiKey}</code>
            <button
              className="mini is-primary"
              type="button"
              onClick={() => navigator.clipboard?.writeText(revealed.apiKey)}
            >
              Copiar
            </button>
            <button className="mini" type="button" onClick={() => setRevealed(null)}>
              Fechar
            </button>
          </div>
        )}
        {revealed && (
          <div className="row-note">
            Chave de {revealed.email} criada. Copie agora — ela não será mostrada novamente.
          </div>
        )}
        {err && <div className="row-err">{err}</div>}

        <form className="op-form" onSubmit={submit}>
          <label>
            <span>E-mail do operador</span>
            <input
              type="email"
              value={email}
              placeholder="pessoa@arenarank.gg"
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
          <label>
            <span>Papel</span>
            <select value={role} onChange={(e) => setRole(e.target.value as OperatorRole)}>
              {ROLE_ORDER.filter((r) => r !== "owner").map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r]}
                </option>
              ))}
            </select>
          </label>
          <button className="mini is-primary" type="submit" disabled={creating}>
            {creating ? "Criando…" : "Criar operador"}
          </button>
        </form>

        <div className="rows" style={{ marginTop: 14 }}>
          {operators.length === 0 && <div className="empty">Nenhum operador criado ainda.</div>}
          {operators.map((o) => (
            <div className={`op-row${o.revoked ? " is-revoked" : ""}`} key={o.id}>
              <span className="op-email">{o.email}</span>
              <span className={`role-badge role-${o.role}`}>{ROLE_LABEL[o.role]}</span>
              <span className="op-key">
                chave …{o.keyPrefix} · criada {timeAgo(o.createdAt)}
              </span>
              <span className="op-lastseen">{o.revoked ? "revogado" : timeAgo(o.lastSeenAt)}</span>
              <span>
                {!o.revoked && (
                  <button
                    className="mini is-danger"
                    type="button"
                    disabled={busyId === o.id}
                    onClick={() => revoke(o.id)}
                  >
                    {busyId === o.id ? "…" : "Revogar"}
                  </button>
                )}
              </span>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
