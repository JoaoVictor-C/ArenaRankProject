/* Estados de carregamento / erro / vazio padronizados. */
import type { ReactNode } from "react";
import { Mi } from "./Mi";

/** Detalhe PT-BR do erro — nunca vaza stack/mensagem técnica em inglês. */
function errorDetail(error: Error): string {
  const status = "status" in error ? (error as { status?: number }).status : undefined;
  if (typeof status === "number") return `Erro ${status} do servidor.`;
  return "Falha de rede — verifique sua conexão.";
}

export function StateBlock({
  loading,
  error,
  empty,
  onRetry,
  compact,
  loadingLabel = "Carregando…",
  errorLabel,
  emptyLabel = "Nada por aqui ainda.",
  children,
}: {
  loading?: boolean;
  error?: Error | null;
  empty?: boolean;
  /** Quando presente, o estado de erro ganha um botão "Tentar de novo". */
  onRetry?: () => void;
  /** Variante enxuta para estados dentro de cards e painéis densos. */
  compact?: boolean;
  loadingLabel?: string;
  errorLabel?: string;
  emptyLabel?: string;
  children?: ReactNode;
}) {
  const className = `state-block${compact ? " state-block-compact" : ""}`;

  if (loading) {
    return (
      <div className={className} role="status" aria-live="polite" aria-busy="true">
        <span className="state-spinner" aria-hidden="true" />
        <span>{loadingLabel}</span>
      </div>
    );
  }
  if (error) {
    const is404 = "status" in error && (error as { status?: number }).status === 404;
    return (
      <div className={className} role="alert">
        <Mi name={is404 ? "search_off" : "error"} style={{ fontSize: 32, color: "var(--text-faint)" }} />
        <span>{errorLabel ?? (is404 ? "Não encontrado." : "Não foi possível carregar.")}</span>
        {!is404 && (
          <span className="faint" style={{ fontSize: 12 }}>{errorDetail(error)}</span>
        )}
        {!is404 && onRetry && (
          <button type="button" className="btn" onClick={onRetry}>
            Tentar de novo
          </button>
        )}
      </div>
    );
  }
  if (empty) {
    return (
      <div className={className} role="status">
        <Mi name="inbox" style={{ fontSize: 32, color: "var(--text-faint)" }} />
        <span>{emptyLabel}</span>
      </div>
    );
  }
  return <>{children}</>;
}
