import { Component, type ErrorInfo, type ReactNode } from "react";
import "./ErrorBoundary.css";

interface Props {
  children: ReactNode;
  /** Fallback custom; por padrão mostra um painel amigável em PT-BR. */
  fallback?: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Captura erros de RENDER de qualquer subárvore e mostra um fallback em vez de
 * "tela branca" — sem um boundary, o React desmonta a árvore inteira quando um
 * erro de render escapa. Erros assíncronos (fetch) seguem tratados por
 * <StateBlock>; este pega os de renderização. Reseta ao navegar quando montado
 * com `key={pathname}` (ver Layout).
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("ErrorBoundary:", error, info.componentStack);
  }

  private readonly reset = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    if (this.props.fallback !== undefined) return this.props.fallback;

    return (
      <div className="error-boundary" role="alert">
        <h1 className="error-boundary-title">Algo deu errado</h1>
        <p className="error-boundary-sub">
          Esta seção encontrou um erro inesperado. Tente novamente ou volte ao início.
        </p>
        <pre className="error-boundary-detail">{error.message}</pre>
        <div className="error-boundary-actions">
          <button type="button" className="error-boundary-btn" onClick={this.reset}>
            Tentar novamente
          </button>
          <a className="error-boundary-btn ghost" href="/">
            Início
          </a>
        </div>
      </div>
    );
  }
}
