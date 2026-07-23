/* Estados de carregamento / erro / vazio padronizados. */
import type { ReactNode } from "react";
import { Mi } from "./Mi";

export function StateBlock({
  loading,
  error,
  empty,
  children,
}: {
  loading?: boolean;
  error?: Error | null;
  empty?: boolean;
  children?: ReactNode;
}) {
  if (loading) {
    return (
      <div className="state-block">
        <span className="state-spinner" />
        <span>Carregando…</span>
      </div>
    );
  }
  if (error) {
    const is404 = "status" in error && (error as { status?: number }).status === 404;
    return (
      <div className="state-block">
        <Mi name={is404 ? "search_off" : "error"} style={{ fontSize: 32, color: "var(--text-faint)" }} />
        <span>{is404 ? "Não encontrado." : "Não foi possível carregar."}</span>
        <span className="faint" style={{ fontSize: 12 }}>{error.message}</span>
      </div>
    );
  }
  if (empty) {
    return (
      <div className="state-block">
        <Mi name="inbox" style={{ fontSize: 32, color: "var(--text-faint)" }} />
        <span>Nada por aqui ainda.</span>
      </div>
    );
  }
  return <>{children}</>;
}
