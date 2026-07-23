/* Badges do design system: tier, placement, delta, streak, tags de jogador. */
import type { TierKey, PlayerTag } from "../lib/types";
import { tierBadgeClass, tierLabel, signed, deltaClass } from "../lib/format";
import { Mi } from "./Mi";

/** Badge de tier (Top 1/10/50...). */
export function TierBadge({ tier }: { tier: TierKey }) {
  if (tier === "none") return null;
  const star = tier === "top1" ? "★ " : "";
  return <span className={`badge ${tierBadgeClass(tier)}`}>{star}{tierLabel(tier)}</span>;
}

/** Badge de colocação (1..8) com cor por posição. */
export function Placement({ place }: { place: number }) {
  return <span className={`place p${place}`}>{place}º</span>;
}

/** Delta de CR/pontos colorido, com sinal "−" real e sem seta. */
export function Delta({ value, className = "" }: { value: number; className?: string }) {
  return <span className={`delta ${deltaClass(value)}${className ? " " + className : ""}`}>{signed(value)}</span>;
}

/** Sequência (win/loss streak). */
export function Streak({ kind, count }: { kind: "win" | "loss"; count: number }) {
  return (
    <span className={`streak ${kind}`}>
      <Mi name={kind === "win" ? "trending_up" : "trending_down"} />
      {count}
    </span>
  );
}

/** Tag de jogador (Top 1 Global, Top 1 BR, Em alta, OTP...). */
export function PlayerTagChip({ tag }: { tag: PlayerTag }) {
  return (
    <span className={`ptag ptag-${tag.kind}`}>
      <Mi name={tag.icon} />
      {tag.label}
    </span>
  );
}
