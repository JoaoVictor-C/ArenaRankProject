import type { Modifier } from "../lib/types";

type SignalKind =
  | "colocacao"
  | "sequencia"
  | "protecao"
  | "boosting"
  | "grupo"
  | "penalidade"
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

export function resolveProfileRatingModifiers(
  modifiers: Modifier[],
  crDelta: number,
): Modifier[] {
  const placementIndex = modifiers.findIndex(
    (modifier) =>
      KIND_ALIASES[modifier.kind.toLocaleLowerCase()] === "colocacao",
  );
  const allImpactsPresent = modifiers.every((modifier) =>
    Number.isFinite(modifier.pdlImpact),
  );

  if (placementIndex >= 0 && allImpactsPresent) {
    return modifiers;
  }

  if (!Number.isFinite(crDelta)) return modifiers;

  const syntheticPlacement = (impact: number): Modifier => ({
    kind: "colocacao",
    label: "Colocação",
    value: 0,
    pdlImpact: impact,
    icon: "leaderboard",
  });

  if (placementIndex < 0 && allImpactsPresent) {
    if (modifiers.length === 0 && crDelta === 0) return [];

    const knownImpact = modifiers.reduce(
      (sum, modifier) => sum + (modifier.pdlImpact ?? 0),
      0,
    );
    const baseImpact = Math.round((crDelta - knownImpact) * 10) / 10;
    return [syntheticPlacement(baseImpact), ...modifiers];
  }

  const multipliers = modifiers.map((modifier) => 1 + modifier.value / 100);
  const combinedMultiplier = multipliers.reduce(
    (product, multiplier) => product * multiplier,
    1,
  );
  if (
    !Number.isFinite(combinedMultiplier) ||
    Math.abs(combinedMultiplier) < Number.EPSILON
  ) {
    return modifiers;
  }

  let currentDelta = crDelta / combinedMultiplier;
  const resolved: Modifier[] = [];
  if (placementIndex < 0) {
    resolved.push(
      syntheticPlacement(Math.round(currentDelta * 10) / 10),
    );
  }

  modifiers.forEach((modifier, index) => {
    const nextDelta = currentDelta * multipliers[index];
    const isPlacement = index === placementIndex;
    const derivedImpact = Math.round(
      (isPlacement ? nextDelta : nextDelta - currentDelta) * 10,
    ) / 10;
    currentDelta = nextDelta;

    resolved.push(
      Number.isFinite(modifier.pdlImpact)
        ? modifier
        : { ...modifier, pdlImpact: derivedImpact },
    );
  });

  return resolved;
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

  return {
    kind,
    title: modifier.label,
    icon: modifier.icon,
    impact,
    formattedImpact: formatPdlImpact(impact),
    description: `Este fator ajustou seu resultado em ${formatPdlImpact(impact)}.`,
  };
}
