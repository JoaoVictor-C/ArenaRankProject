/* Badges do design system: tier, placement, delta, streak, tags de jogador. */
import type { TierKey, PlayerTag } from "../lib/types";
import { tierBadgeClass, tierLabel, signed, deltaClass } from "../lib/format";
import { useIconColors } from "../hooks/useIconColors";
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

/** Cor neutra (deep, bright) enquanto a cor do campeão carrega ou não resolve. */
const CHAMP_FALLBACK: [string, string] = ["#3a3f4a", "#5a6270"];

/** Tag de jogador. As tags de campeão ("OTP VLAD", "TOP 2 EZREAL") são tingidas
 *  com a cor dominante do próprio campeão — extraída do ícone ddragon via
 *  {@link useIconColors} e aplicada como degradê (Vladimir → vermelho). "Em alta"
 *  mantém sua cor fixa. Sem `champIconUrl`, degrada p/ a cor base da kind. */
export function PlayerTagChip({ tag }: { tag: PlayerTag }) {
  const champColors = useIconColors(tag.champIconUrl ?? undefined);
  if (tag.champIconUrl) {
    const [deep, bright] = champColors ?? CHAMP_FALLBACK;
    return (
      <span
        className={`ptag ptag-champ ptag-${tag.kind}`}
        style={{
          background: `linear-gradient(135deg, ${deep}, color-mix(in srgb, ${deep} 56%, #000))`,
          borderColor: `color-mix(in srgb, ${bright} 50%, transparent)`,
        }}
      >
        {tag.label}
      </span>
    );
  }
  return (
    <span className={`ptag ptag-${tag.kind}`}>
      {tag.icon ? <Mi name={tag.icon} /> : null}
      {tag.label}
    </span>
  );
}
