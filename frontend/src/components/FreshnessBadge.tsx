/* ============================================================
   FreshnessBadge — "Atualizado agora / há 3 min" + botão de atualizar.

   Contrapartida honesta do cache persistido: a página abre instantânea com o
   último dado conhecido, então precisa DIZER que idade ele tem. Sem isso o
   jogador que acabou de sair de uma partida acha que já está vendo a posição
   nova. Alimentado por `useApi().updatedAt / .refreshing / .retry`.
   ============================================================ */
import { useEffect, useState } from "react";
import { Mi } from "./Mi";
import "./FreshnessBadge.css";

function relLabel(updatedAt: number, now: number): string {
  if (!updatedAt) return "—";
  const s = Math.max(0, Math.round((now - updatedAt) / 1000));
  if (s < 60) return "agora";
  const m = Math.floor(s / 60);
  if (m < 60) return `há ${m} min`;
  const h = Math.floor(m / 60);
  return h < 24 ? `há ${h}h` : `há ${Math.floor(h / 24)}d`;
}

export function FreshnessBadge({
  updatedAt,
  refreshing,
  onRefresh,
  className = "",
}: {
  updatedAt: number;
  refreshing: boolean;
  onRefresh: () => void;
  className?: string;
}) {
  // updatedAt é estático; sem este tick o rótulo congelaria em "agora" numa
  // aba deixada aberta — exatamente o cenário que o badge existe pra evitar.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);

  const stale = !refreshing && updatedAt > 0 && now - updatedAt > 5 * 60_000;

  return (
    <div className={`fresh-badge${stale ? " is-stale" : ""}${className ? " " + className : ""}`}>
      <span
        className="fresh-badge__label"
        title={updatedAt ? new Date(updatedAt).toLocaleString("pt-BR") : undefined}
      >
        {refreshing ? "Atualizando…" : `Atualizado ${relLabel(updatedAt, now)}`}
      </span>
      <button
        type="button"
        className="fresh-badge__btn"
        onClick={onRefresh}
        disabled={refreshing}
        aria-label="Atualizar dados agora"
      >
        <Mi name="refresh" className={refreshing ? "is-spinning" : ""} />
      </button>
    </div>
  );
}
