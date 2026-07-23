/* ============================================================
   ArenaRank — helpers de formatação (pt-BR)
   ============================================================ */
import type { TierKey } from "./types";

/** Número pt-BR com separador de milhar (4.295). */
export function nf(n: number): string {
  return n.toLocaleString("pt-BR");
}

/** Inteiro com sinal explícito; usa "−" (minus real) p/ negativos. Ex: +200 / −64 / 0. */
export function signed(n: number): string {
  if (n > 0) return "+" + nf(n);
  if (n < 0) return "−" + nf(Math.abs(n));
  return "0";
}

/** Porcentagem inteira. */
export function pct(n: number): string {
  return `${Math.round(n)}%`;
}

/** Classe de delta (up/down/flat) p/ as cores semânticas. */
export function deltaClass(n: number): "up" | "down" | "flat" {
  if (n > 0) return "up";
  if (n < 0) return "down";
  return "flat";
}

/** Mapeia TierKey → classe de badge do design system. */
export function tierBadgeClass(t: TierKey): string {
  switch (t) {
    case "top1":
      return "tier-top1";
    case "top10":
      return "tier-top10";
    case "top50":
      return "tier-top50";
    case "top100":
      return "tier-top100";
    case "top500":
      return "tier-top500";
    default:
      return "neutral";
  }
}

/** Rótulo curto do tier. */
export function tierLabel(t: TierKey): string {
  switch (t) {
    case "top1":
      return "Top 1";
    case "top10":
      return "Top 10";
    case "top50":
      return "Top 50";
    case "top100":
      return "Top 100";
    case "top500":
      return "Top 500";
    default:
      return "";
  }
}

/** Faixa de cor do winrate por marco de % (igual ao wrClass do design).
 *  As classes batem com o CSS: .pod-wr/.lb-wr .gold/.blue/.green/.low */
export function winrateBand(wr: number): "gold" | "blue" | "green" | "low" {
  if (wr >= 85) return "gold"; // marco elite
  if (wr >= 80) return "blue"; // forte
  if (wr >= 75) return "green"; // bom
  return "low"; // padrão (<75%)
}

/** "há 11 min", "há 2 h", "há 34 s" — tempo decorrido relativo, pt-BR. */
export function timeAgo(iso: string, nowMs = Date.now()): string {
  const diff = Math.max(0, Math.floor((nowMs - new Date(iso).getTime()) / 1000));
  if (diff < 60) return `há ${diff} s`;
  if (diff < 3600) return `há ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `há ${Math.floor(diff / 3600)} h`;
  return `há ${Math.floor(diff / 86400)} d`;
}

/** Formata duração em "Xs", "Xmin Ys", "Xh Ymin". */
export function fmtCountdown(totalSec: number): string {
  const s = Math.max(0, Math.floor(totalSec));
  if (s < 60) return `${s} s`;
  if (s < 3600) {
    const m = Math.floor(s / 60);
    const r = s % 60;
    return r ? `${m} min ${r} s` : `${m} min`;
  }
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return m ? `${h} h ${m} min` : `${h} h`;
}

/** Formata um valor de premiação conforme a moeda. BRL → "R$ 126" · RP → "126 RP". */
export function fmtPrize(amount: number, currency?: string): string {
  const pretty = nf(amount);
  return currency === "BRL" ? `R$ ${pretty}` : `${pretty} RP`;
}

/** Divide um Riot ID "Nome#TAG" em { name, handle }. */
export function splitRiotId(riotId: string): { name: string; handle: string } {
  const i = riotId.lastIndexOf("#");
  if (i === -1) return { name: riotId, handle: "" };
  return { name: riotId.slice(0, i), handle: riotId.slice(i) };
}
