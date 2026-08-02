/* ============================================================
   BuildHoverCard.tsx — popup de dados no hover de ícones de item/
   augment, reusado em Winrate.tsx, Perfil.tsx e Augments.tsx.

   Usa portal p/ document.body: vários dos anchors (`.wr-fcard`,
   `.augment-card`) têm `overflow: hidden` (recortam a arte/glow do
   card) — um popup posicionado ali dentro seria cortado. O portal
   escapa disso e se posiciona por coordenadas reais (getBoundingClientRect),
   mesmo padrão do `.champ-pop` do leaderboard, só que "fixed".
   ============================================================ */
import { createElement, useRef, useState, type HTMLAttributes, type ReactNode } from "react";
import { createPortal } from "react-dom";
import "./BuildHoverCard.css";

export interface BuildHoverStat {
  label: string;
  value: string;
}

export interface BuildHoverData {
  name: string;
  iconUrl?: string | null;
  /** Selo pequeno ao lado do nome, já formatado pelo chamador (ex.: "S+",
      "Prismático") — mantém este componente sem depender de um enum de
      raridade/tier específico de cada página. */
  badge?: string | null;
  /** Classe de cor do selo — ver `.bh-badge.tier-*` / `.bh-badge.rarity-*`
      em BuildHoverCard.css. */
  badgeClassName?: string;
  description?: string | null;
  stats?: BuildHoverStat[];
}

export function BuildHoverIcon({
  data,
  children,
  as = "span",
  ...rest
}: {
  data: BuildHoverData;
  children: ReactNode;
  /** Tag do wrapper — "span" por padrão, "article" p/ manter semântica em
      cards que já eram `<article>` antes de ganhar o hover. */
  as?: "span" | "article" | "div";
} & HTMLAttributes<HTMLElement>) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const ref = useRef<HTMLElement>(null);

  function show() {
    const r = ref.current?.getBoundingClientRect();
    if (r) setPos({ x: r.left + r.width / 2, y: r.top });
  }

  return createElement(
    as,
    { ...rest, ref, onMouseEnter: show, onMouseLeave: () => setPos(null) },
    <>
      {children}
      {pos &&
        createPortal(
          <span className="bh-pop" role="tooltip" style={{ left: pos.x, top: pos.y }}>
            <span className="bh-head">
              {data.iconUrl && <img className="bh-icon" src={data.iconUrl} alt="" />}
              <span className="bh-name">{data.name}</span>
              {data.badge && (
                <span className={`bh-badge${data.badgeClassName ? ` ${data.badgeClassName}` : ""}`}>
                  {data.badge}
                </span>
              )}
            </span>
            {data.description && <span className="bh-desc">{data.description}</span>}
            {data.stats && data.stats.length > 0 && (
              <span className="bh-grid">
                {data.stats.map((s) => (
                  <span className="bh-row" key={s.label}>
                    <span className="bh-k">{s.label}</span>
                    <span className="bh-v">{s.value}</span>
                  </span>
                ))}
              </span>
            )}
          </span>,
          document.body,
        )}
    </>,
  );
}
