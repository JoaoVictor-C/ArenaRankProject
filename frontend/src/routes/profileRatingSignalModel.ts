import type { Modifier } from "../lib/types";

type SignalKind =
  | "colocacao"
  | "sequencia"
  | "protecao"
  | "boosting"
  | "grupo"
  | "penalidade"
  | "confianca"
  | "teto_ganho"
  | "teto_perda"
  | "piso_ganho"
  | "ajuste"
  | "piso_zero"
  | "outro";

export interface SignalContext {
  placement: number;
  premade: boolean;
  crDelta: number;
}

export interface ProfileRatingSignal {
  kind: SignalKind;
  title: string;
  icon: string;
  impact: number;
  formattedImpact: string;
  description: string;
}

const KIND_ALIASES: Record<string, SignalKind> = {
  placement: "colocacao",
  colocacao: "colocacao",
  streak: "sequencia",
  sequencia: "sequencia",
  protection: "protecao",
  protecao: "protecao",
  boosting: "boosting",
  premade: "grupo",
  group: "grupo",
  grupo: "grupo",
  penalty: "penalidade",
  penalidade: "penalidade",
  // Raio-X do resultado (v1.4) — novos fatores, todos com pdlImpact real vindo
  // do backend (arena/rating/explain.py). Ver buildProfileRatingSignal.
  confidence: "confianca",
  confianca: "confianca",
  teto_ganho: "teto_ganho",
  gain_cap: "teto_ganho",
  teto_perda: "teto_perda",
  loss_cap: "teto_perda",
  piso_ganho: "piso_ganho",
  min_gain: "piso_ganho",
  ajuste: "ajuste",
  display_adjust: "ajuste",
  piso_zero: "piso_zero",
  zero_floor: "piso_zero",
};

function displayImpact(value: number): number {
  const rounded = Math.round(value);
  return Object.is(rounded, -0) ? 0 : rounded;
}

function formatPdlImpact(value: number): string {
  const rounded = displayImpact(value);
  if (rounded > 0) return `+${rounded} PDL`;
  if (rounded < 0) return `−${Math.abs(rounded)} PDL`;
  return "0 PDL";
}

function placementDescription(impact: number, context: SignalContext): string {
  const amount = Math.abs(displayImpact(impact));
  if (impact > 0) {
    return `Você ganhou ${amount} PDL por terminar em ${context.placement}º.`;
  }
  if (impact < 0) {
    return `Você perdeu ${amount} PDL por terminar em ${context.placement}º.`;
  }
  return `Sua colocação manteve o resultado em 0 PDL ao terminar em ${context.placement}º.`;
}

function streakDescription(
  impact: number,
  context: SignalContext,
  lossStreak: boolean,
): string {
  const amount = Math.abs(displayImpact(impact));
  if (lossStreak && impact > 0) {
    return `Você deixou de perder ${amount} PDL graças ao amortecedor da sua sequência de derrotas.`;
  }
  if (impact > 0) {
    return `Sua sequência acrescentou ${amount} PDL a esta vitória.`;
  }
  if (context.crDelta < 0) {
    return `Sua sequência aumentou esta perda em ${amount} PDL.`;
  }
  return `Sua sequência reduziu este ganho em ${amount} PDL.`;
}

function protectionDescription(impact: number, context: SignalContext): string {
  const amount = Math.abs(displayImpact(impact));
  if (impact < 0 && context.crDelta >= 0) {
    return `Você deixou de ganhar ${amount} PDL por vencer uma partida com nível de habilidade inferior ao esperado para seu elo atual.`;
  }
  if (impact > 0 && context.crDelta < 0) {
    return `Você deixou de perder ${amount} PDL por cair em uma partida com nível de habilidade superior ao esperado para seu elo atual.`;
  }
  if (impact < 0 && context.crDelta < 0) {
    return `Você perdeu ${amount} PDL a mais por perder em uma partida com nível de habilidade inferior ao esperado para seu elo atual.`;
  }
  if (impact > 0) {
    return `Você ganhou ${amount} PDL a mais por vencer uma partida com nível de habilidade superior ao esperado para seu elo atual.`;
  }
  return "O nível de habilidade da partida não alterou seu PDL.";
}

function groupDescription(impact: number, context: SignalContext): string {
  const amount = Math.abs(displayImpact(impact));
  const group = context.premade ? "uma dupla ou grupo recorrente" : "um grupo recorrente";
  if (impact < 0 && context.crDelta >= 0) {
    return `Você deixou de ganhar ${amount} PDL porque entrou em ${group}.`;
  }
  if (impact > 0 && context.crDelta < 0) {
    return `Você deixou de perder ${amount} PDL após jogar em ${group}.`;
  }
  return `Jogar em ${group} ajustou seu resultado em ${formatPdlImpact(impact)}.`;
}

function integrityDescription(
  kind: SignalKind,
  impact: number,
  context: SignalContext,
): string {
  const amount = Math.abs(displayImpact(impact));
  if (kind === "boosting") {
    if (impact < 0 && context.crDelta >= 0) {
      return `A proteção de integridade reduziu este ganho em ${amount} PDL.`;
    }
    return `A proteção de integridade ajustou seu resultado em ${formatPdlImpact(impact)}.`;
  }
  if (impact < 0 && context.crDelta >= 0) {
    return `O limite de variação reduziu este ganho em ${amount} PDL.`;
  }
  if (impact > 0 && context.crDelta < 0) {
    return `O limite de variação evitou uma perda adicional de ${amount} PDL.`;
  }
  return `O limite de variação ajustou seu resultado em ${formatPdlImpact(impact)}.`;
}

function confidenceDescription(impact: number): string {
  const amount = Math.abs(displayImpact(impact));
  if (impact > 0) {
    return `A margem de incerteza sobre o seu nível diminuiu, o que acrescentou ${amount} PDL ao resultado.`;
  }
  if (impact < 0) {
    return `A margem de incerteza sobre o seu nível aumentou, o que reduziu ${amount} PDL do resultado.`;
  }
  return "A margem de incerteza sobre o seu nível não mudou este resultado.";
}

function adjustDescription(impact: number): string {
  const amount = Math.abs(displayImpact(impact));
  const verb = impact >= 0 ? "acrescentou" : "reduziu";
  return `Esta partida foi registrada antes do detalhamento completo do Raio-X — a consolidação da sua estimativa e o teto/piso de colocação, quando aplicável, aparecem juntos aqui e ${verb} ${amount} PDL ao resultado.`;
}

function zeroFloorDescription(impact: number): string {
  const amount = Math.abs(displayImpact(impact));
  return `Seu PDL não pode ficar negativo — isso poupou ${amount} PDL desta queda.`;
}

function capDescription(kind: SignalKind, impact: number): string {
  const amount = Math.abs(displayImpact(impact));
  if (kind === "teto_ganho") {
    return `Seu ganho bruto foi maior, mas o teto de PDL desta colocação limitou o resultado (redução de ${amount} PDL).`;
  }
  if (kind === "teto_perda") {
    return `Sua perda bruta foi maior, mas o teto de PDL desta colocação limitou o resultado (você poupou ${amount} PDL).`;
  }
  // piso_ganho
  return `Esta colocação garante um PDL mínimo — você recebeu ${amount} PDL a mais para atingir o piso.`;
}

/**
 * Raio-X do resultado (v1.4): `pdlImpact` agora chega REAL do backend
 * (`arena/rating/explain.py`'s reconciling ledger, via `map_modifiers` —
 * `arena/api/routers/_common.py`), nunca mais reconstruído aqui. Esta função
 * costumava inverter a cadeia multiplicativa de `value` para ADIVINHAR um
 * `pdlImpact` por fator — mas essa conta ignorava o termo de "confiança"
 * (`-3·Δσ`, sempre presente na identidade de CR) e qualquer efeito do teto/piso
 * de PDL, então ficava sistematicamente errada sempre que um desses dois
 * mecanismos entrava em jogo. Mantida como uma função (em vez de inline no
 * componente) só por estabilidade de import; hoje é um filtro defensivo —
 * um fator sem `pdlImpact` finito nunca deveria chegar aqui, mas se chegar,
 * é melhor omiti-lo do que fabricar um número.
 */
export function resolveProfileRatingModifiers(modifiers: Modifier[]): Modifier[] {
  return modifiers.filter((modifier) => Number.isFinite(modifier.pdlImpact));
}

export function buildProfileRatingSignal(
  modifier: Modifier,
  context: SignalContext,
): ProfileRatingSignal | null {
  if (typeof modifier.pdlImpact !== "number" || !Number.isFinite(modifier.pdlImpact)) {
    return null;
  }

  const kind = KIND_ALIASES[modifier.kind.toLocaleLowerCase()] ?? "outro";
  const impact = displayImpact(modifier.pdlImpact);
  if (impact === 0) return null;

  const lossStreak =
    kind === "sequencia" && modifier.label.toLocaleLowerCase().includes("derrota");

  if (kind === "colocacao") {
    return {
      kind,
      title: "Colocação",
      icon: modifier.icon,
      impact,
      formattedImpact: formatPdlImpact(impact),
      description: placementDescription(impact, context),
    };
  }

  if (kind === "sequencia") {
    return {
      kind,
      title: lossStreak ? "Sequência de derrotas" : "Sequência de vitórias",
      icon: modifier.icon,
      impact,
      formattedImpact: formatPdlImpact(impact),
      description: streakDescription(impact, context, lossStreak),
    };
  }

  if (kind === "protecao") {
    return {
      kind,
      title: "Proteção do topo",
      icon: modifier.icon,
      impact,
      formattedImpact: formatPdlImpact(impact),
      description: protectionDescription(impact, context),
    };
  }

  if (kind === "grupo") {
    return {
      kind,
      title: context.premade ? "Penalidade em dupla" : "Penalidade de grupo",
      icon: modifier.icon,
      impact,
      formattedImpact: formatPdlImpact(impact),
      description: groupDescription(impact, context),
    };
  }

  if (kind === "boosting" || kind === "penalidade") {
    return {
      kind,
      title: kind === "boosting" ? "Proteção de integridade" : "Variação limitada",
      icon: modifier.icon,
      impact,
      formattedImpact: formatPdlImpact(impact),
      description: integrityDescription(kind, impact, context),
    };
  }

  if (kind === "confianca") {
    return {
      kind,
      title: "Consolidação da sua estimativa",
      icon: modifier.icon,
      impact,
      formattedImpact: formatPdlImpact(impact),
      description: confidenceDescription(impact),
    };
  }

  if (kind === "teto_ganho" || kind === "teto_perda" || kind === "piso_ganho") {
    return {
      kind,
      title: modifier.label,
      icon: modifier.icon,
      impact,
      formattedImpact: formatPdlImpact(impact),
      description: capDescription(kind, impact),
    };
  }

  if (kind === "ajuste") {
    // The label is backend-picked (arena/api/routers/_common.py) and names the
    // specific mechanism (e.g. "Piso de ganho da colocação (parcial)") whenever
    // explain() could identify WHICH cap rule bound, even though it couldn't
    // split its exact PDL share from the confiança term — only falls back to
    // the generic "Ajuste de exibição" when neither is knowable.
    return {
      kind,
      title: modifier.label,
      icon: modifier.icon,
      impact,
      formattedImpact: formatPdlImpact(impact),
      description: adjustDescription(impact),
    };
  }

  if (kind === "piso_zero") {
    return {
      kind,
      title: "PDL mínimo (0)",
      icon: modifier.icon,
      impact,
      formattedImpact: formatPdlImpact(impact),
      description: zeroFloorDescription(impact),
    };
  }

  return {
    kind,
    title: modifier.label,
    icon: modifier.icon,
    impact,
    formattedImpact: formatPdlImpact(impact),
    description: `Este fator ajustou seu resultado em ${formatPdlImpact(impact)}.`,
  };
}
