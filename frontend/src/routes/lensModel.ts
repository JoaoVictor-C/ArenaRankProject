export type LensAxisKey = "adapt" | "eco" | "surv" | "meta" | "impact";
export type LensPhase = "T0" | "T1" | "T2";
export type LensWindowSize = 20 | 50 | 100 | "season";
export type LensMetricDirection = "up" | "down" | "neutral";
export type LensMetricReason =
  | "requires_round_timeline"
  | "before_detailed_ingestion"
  | "insufficient_sample";

export interface LensMetric {
  key: string;
  label: string;
  description: string;
  phase: LensPhase;
  available: boolean;
  display?: string;
  score?: number;
  cohortScore?: number;
  top100Score?: number;
  sample?: number;
  direction?: LensMetricDirection;
  reason?: LensMetricReason;
}
export interface LensAxis {
  key: LensAxisKey;
  label: string;
  shortLabel: string;
  question: string;
  score: number;
  delta30d: number;
  percentile: number;
  metrics: LensMetric[];
}

export interface LensInsight {
  key: string;
  eyebrow: string;
  text: string;
  axis: LensAxisKey;
  tone: "positive" | "warning" | "neutral";
}

export interface LensMockView {
  mocked: true;
  riotId: string;
  player: {
    name: string;
    handle: string;
    region: string;
    cr: number;
    rank: number;
  };
  window: {
    size: LensWindowSize;
    games: number;
    from: string;
    to: string;
    format: "trios";
  };
  cohort: {
    label: string;
    size: number;
    updatedAt: string;
    fallback: boolean;
  };
  coverage: {
    t0: number;
    t1: number;
    t2: number;
    detailedSince: string;
  };
  overall: {
    score: number;
    percentile: number;
    delta30d: number;
  };
  archetype: {
    label: string;
    confidence: number;
    summary: string;
  };
  trajectory: {
    crDelta30d: number;
    rankDelta30d: number;
    days: Array<{ day: string; cr: number; games: number }>;
  };
  axes: LensAxis[];
  insights: LensInsight[];
}

const metric = (
  key: string,
  label: string,
  description: string,
  display: string,
  score: number,
  cohortScore: number,
  top100Score: number,
  phase: LensPhase,
  direction: LensMetricDirection = "up",
): LensMetric => ({
  key,
  label,
  description,
  display,
  score,
  cohortScore,
  top100Score,
  phase,
  direction,
  sample: phase === "T0" ? 50 : 34,
  available: true,
});

const locked = (
  key: string,
  label: string,
  description: string,
  phase: LensPhase,
  reason: LensMetricReason,
): LensMetric => ({ key, label, description, phase, reason, available: false });

const AXES: LensAxis[] = [
  {
    key: "adapt",
    label: "Adaptabilidade",
    shortLabel: "ADAPT",
    question: "Quanto do seu resultado sobrevive quando o plano A desaparece?",
    score: 74,
    delta30d: 2,
    percentile: 0.8,
    metrics: [
      metric("poolBreadth", "Amplitude do pool", "Diversidade real entre os campeões da janela.", "0,81", 88, 50, 73, "T0"),
      metric("offMainYield", "Rendimento fora do main", "Diferença de colocação longe do campeão principal.", "+0,42 pos.", 72, 50, 79, "T0"),
      metric("tiltResistance", "Resistência a tilt", "Top-half depois de uma partida na metade inferior.", "−2,1 p.p.", 41, 50, 76, "T0"),
      metric("recoveryHalfLife", "Recuperação de queda", "Partidas necessárias para recuperar um vale de PDL.", "6 partidas", 63, 50, 82, "T0", "down"),
      metric("championSwitchRate", "Troca após derrota", "Frequência de mudança de campeão após bottom-half.", "64%", 58, 50, 61, "T0", "neutral"),
      locked("counterpickBreadth", "Resposta ao lobby", "Adaptação ao draft e aos oponentes por round.", "T2", "requires_round_timeline"),
    ],
  },
  {
    key: "eco",
    label: "Economia",
    shortLabel: "ECO",
    question: "Você transforma cada compra em força ou deixa recurso na mesa?",
    score: 62,
    delta30d: -3,
    percentile: 0.67,
    metrics: [
      metric("unspentGoldRate", "Ouro parado", "Parcela do ouro disponível que termina sem virar item.", "14,2%", 31, 50, 84, "T1", "down"),
      metric("prismaticRate", "Prismáticos por partida", "Frequência de augments prismáticos na janela.", "1,8", 72, 50, 67, "T0", "neutral"),
      metric("prismaticYield", "Retorno do prismático", "Ganho de colocação quando aparece ao menos um prismático.", "+0,31 pos.", 67, 50, 73, "T0"),
      metric("anvilSpendShare", "Aposta em bigornas", "Parcela do orçamento convertida em bigornas.", "22%", 61, 50, 68, "T1", "neutral"),
      locked("itemsPerRound", "Ritmo de compra", "Itens comprados a cada round jogado.", "T1", "before_detailed_ingestion"),
    ],
  },
  {
    key: "surv",
    label: "Sobrevivência",
    shortLabel: "SURV",
    question: "Quanto tempo você permanece relevante antes de entregar espaço?",
    score: 68,
    delta30d: 5,
    percentile: 0.72,
    metrics: [
      metric("roundsSurvived", "Rounds jogados", "Sobrevida normalizada pelo maior percurso da lobby.", "78%", 76, 50, 82, "T1"),
      metric("deathsPerRound", "Mortes por round", "Mortes divididas pelos rounds efetivamente jogados.", "0,29", 69, 50, 81, "T1", "down"),
      metric("mitigationRatio", "Absorção", "Dano mitigado sobre toda a pressão recebida.", "36%", 64, 50, 78, "T1"),
      metric("timeDeadShare", "Tempo morto", "Parcela do tempo de jogo fora do combate.", "8,4%", 61, 50, 80, "T1", "down"),
      metric("clutchRate", "Clutch", "Sobrevivências em vida de um dígito por round.", "0,18", 73, 50, 85, "T1"),
      locked("comebackRate", "Virada por round", "Rounds vencidos depois de ficar em desvantagem.", "T2", "requires_round_timeline"),
    ],
  },
  {
    key: "meta",
    label: "Meta",
    shortLabel: "META",
    question: "Você lê o patch cedo — e extrai mais dele que a sua faixa?",
    score: 81,
    delta30d: 7,
    percentile: 0.88,
    metrics: [
      metric("metaAlignment", "Alinhamento ao meta", "Partidas em campeões S+ ou S no patch.", "68%", 79, 50, 88, "T0"),
      metric("metaEdge", "Vantagem no campeão", "Sua colocação contra a média global do mesmo campeão.", "+0,34 pos.", 84, 50, 91, "T0"),
      metric("gapToTop100", "Distância do Top-100", "Quanto falta para o rendimento dos melhores no mesmo pool.", "−0,18 pos.", 62, 50, 100, "T0"),
      metric("augmentPickScore", "Leitura de augments", "Qualidade das escolhas no contexto do campeão.", "57º pct.", 57, 50, 86, "T1"),
      metric("tierChurn", "Rotação de tier alto", "Campeões fortes diferentes usados na janela.", "5 campeões", 76, 50, 83, "T0", "neutral"),
      locked("augmentComboHit", "Combos do meta", "Combinações de augments no decil superior.", "T2", "requires_round_timeline"),
    ],
  },
  {
    key: "impact",
    label: "Impacto",
    shortLabel: "IMPACT",
    question: "O seu time vence por causa da sua presença ou apesar dela?",
    score: 77,
    delta30d: 4,
    percentile: 0.84,
    metrics: [
      metric("subteamDamageShare", "Dano dentro do time", "Sua parcela do dano produzido pelo subteam.", "44%", 81, 50, 89, "T0"),
      metric("combatScore", "Nota de combate", "Sinal de combate Riot ajustado à lobby.", "7,8", 86, 50, 91, "T1"),
      metric("winContribution", "Contribuição ao resultado", "Mudança de top-half entre combates fortes e fracos.", "+18 p.p.", 74, 50, 82, "T1"),
      metric("ccPerRound", "Controle por round", "Controle de grupo aplicado por round jogado.", "2,7 s", 58, 50, 75, "T1"),
      metric("soloLift", "Rendimento sem duo", "Diferença de colocação entre partidas solo e premade.", "+0,48 pos.", 88, 50, 72, "T0", "neutral"),
      metric("premadeShare", "Partidas com duo", "Participação de premades na janela analisada.", "38%", 55, 50, 58, "T0", "neutral"),
      locked("earlyRoundsForm", "Forma nos 5 primeiros rounds", "Impacto produzido antes de a lobby estabilizar.", "T2", "requires_round_timeline"),
    ],
  },
];

function splitRiotId(riotId: string): { name: string; handle: string } {
  const [name, tag] = riotId.split("#", 2);
  return {
    name: name.trim() || "Jogador",
    handle: `#${tag?.trim() || "BR1"}`,
  };
}

export function createLensMock(
  riotId: string,
  size: LensWindowSize = 50,
): LensMockView {
  const identity = splitRiotId(riotId);
  const games = size === "season" ? 186 : size;

  return {
    mocked: true,
    riotId,
    player: { ...identity, region: "BR", cr: 1842, rank: 37 },
    window: {
      size,
      games,
      from: size === 20 ? "2026-07-13" : size === 50 ? "2026-06-02" : "2026-04-18",
      to: "2026-07-28",
      format: "trios",
    },
    cohort: {
      label: "Trios · Top 500 · Patch 16.14",
      size: 8421,
      updatedAt: "2026-07-28T07:00:00Z",
      fallback: false,
    },
    coverage: { t0: games, t1: Math.min(games, 34), t2: 0, detailedSince: "12/08/2026" },
    overall: { score: 71, percentile: 0.72, delta30d: 4 },
    archetype: {
      label: "Camaleão de duelo",
      confidence: 0.68,
      summary: "Troca de plano sem perder pressão e encontra vantagem em pools menos óbvios.",
    },
    trajectory: {
      crDelta30d: 128,
      rankDelta30d: 42,
      days: [
        { day: "20/07", cr: 1714, games: 3 },
        { day: "21/07", cr: 1748, games: 5 },
        { day: "22/07", cr: 1732, games: 2 },
        { day: "23/07", cr: 1785, games: 6 },
        { day: "24/07", cr: 1802, games: 4 },
        { day: "25/07", cr: 1791, games: 3 },
        { day: "26/07", cr: 1830, games: 5 },
        { day: "27/07", cr: 1842, games: 4 },
      ],
    },
    axes: AXES.map((axis) => ({
      ...axis,
      metrics: axis.metrics.map((entry) => ({
        ...entry,
        sample: entry.available ? Math.min(entry.sample ?? games, games) : undefined,
      })),
    })),
    insights: [
      {
        key: "solo_carry",
        eyebrow: "Força escondida",
        text: "Você rende 0,48 posição melhor sozinho do que com o seu duo habitual.",
        axis: "impact",
        tone: "positive",
      },
      {
        key: "unspent_gold",
        eyebrow: "Maior vazamento",
        text: "14,2% do seu ouro termina parado. É o pior sinal do seu Lens hoje.",
        axis: "eco",
        tone: "warning",
      },
      {
        key: "meta_edge",
        eyebrow: "Leitura do patch",
        text: "Seu pool está no 84º percentil mesmo antes de copiar integralmente o Top-100.",
        axis: "meta",
        tone: "neutral",
      },
    ],
  };
}

export function scoreTone(score: number): "low" | "neutral" | "high" | "elite" {
  if (score < 40) return "low";
  if (score <= 60) return "neutral";
  if (score <= 85) return "high";
  return "elite";
}

export function radarPoint(
  score: number,
  index: number,
  cx: number,
  cy: number,
  radius: number,
): [number, number] {
  const angle = -Math.PI / 2 + (index * Math.PI * 2) / 5;
  const distance = radius * Math.max(0, Math.min(100, score)) / 100;
  return [cx + Math.cos(angle) * distance, cy + Math.sin(angle) * distance];
}

export function radarPath(
  scores: number[],
  cx: number,
  cy: number,
  radius: number,
): string {
  return scores
    .map((score, index) => {
      const [x, y] = radarPoint(score, index, cx, cy, radius);
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ") + " Z";
}
