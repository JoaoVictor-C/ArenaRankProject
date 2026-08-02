import "./Lens.css";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { Mi, ProfileSurfaceNav } from "../components";
import {
  createLensMock,
  scoreTone,
  type LensAxis,
  type LensAxisKey,
  type LensMetric,
  type LensMetricReason,
  type LensMockView,
  type LensWindowSize,
} from "./lensModel";
import { LensTree } from "./LensTree";
import { useLensAxisMotion, useLensEntrance } from "./lensMotion";

const WINDOW_OPTIONS: Array<{ value: LensWindowSize; label: string }> = [
  { value: 20, label: "20" },
  { value: 50, label: "50" },
  { value: 100, label: "100" },
  { value: "season", label: "Temporada" },
];

const REASON_COPY: Record<LensMetricReason, string> = {
  requires_round_timeline: "Requer dados de round · em avaliação",
  before_detailed_ingestion: "Requer telemetria detalhada",
  insufficient_sample: "Amostra insuficiente",
};

type LensPreviewState = "ready" | "loading" | "empty" | "partial" | "error" | "fallback";

function parsePreviewState(value: string | null): LensPreviewState {
  if (
    value === "loading"
    || value === "empty"
    || value === "partial"
    || value === "error"
    || value === "fallback"
  ) {
    return value;
  }
  return "ready";
}

function applyPreviewState(data: LensMockView, state: LensPreviewState): LensMockView {
  if (state === "fallback") {
    return {
      ...data,
      cohort: {
        ...data.cohort,
        label: "Trios · Top 1.000 · Patch 16.14",
        size: 16492,
        fallback: true,
      },
    };
  }

  if (state !== "partial") return data;

  const games = 14;
  return {
    ...data,
    window: { ...data.window, games },
    coverage: { ...data.coverage, t0: games, t1: games },
    axes: data.axes.map((axis) => ({
      ...axis,
      metrics: axis.metrics.map((metric) => ({
        ...metric,
        sample: metric.sample === undefined ? undefined : Math.min(metric.sample, games),
      })),
    })),
  };
}

function formatNumber(value: number): string {
  return value.toLocaleString("pt-BR");
}
function LensIdentity({ data }: { data: LensMockView }) {
  const initials = data.player.name.slice(0, 2).toUpperCase();

  return (
    <header className="lens-identity">
      <div className="lens-avatar" aria-hidden="true">
        <span>{initials}</span>
      </div>
      <div className="lens-player-copy">
        <div className="lens-player-name">
          <strong>{data.player.name}</strong>
          <span>{data.player.handle}</span>
        </div>
        <div className="lens-player-meta">
          <span>{data.player.region}</span>
          <span>#{formatNumber(data.player.rank)}</span>
          <span>{formatNumber(data.player.cr)} PDL</span>
        </div>
      </div>
      <div className="lens-identity-mark">
        <span className="lens-wordmark">LENS</span>
        <span className="lens-mock-chip"><i />Dados mockados</span>
      </div>
    </header>
  );
}

function LensArchetype({ data, partial = false }: { data: LensMockView; partial?: boolean }) {
  return (
    <section className={`lens-archetype${partial ? " is-partial" : ""}`}>
      <span className="lens-kicker">SEU PADRÃO</span>
      <h1>{partial ? "Padrão em formação" : data.archetype.label}</h1>
      <p>
        {partial
          ? "A árvore já mostra sinais iniciais, mas o arquétipo precisa de 30 partidas para ganhar forma."
          : data.archetype.summary}
      </p>
      <div className="lens-confidence">
        <span>{partial ? "Amostra do padrão" : "Confiança do padrão"}</span>
        <b>{partial ? "14/30" : `${Math.round(data.archetype.confidence * 100)}%`}</b>
      </div>
      <div className="lens-confidence-track" aria-hidden="true">
        <i style={{ width: partial ? `${(14 / 30) * 100}%` : `${data.archetype.confidence * 100}%` }} />
      </div>
    </section>
  );
}

function LensAxisSummary({ axis }: { axis: LensAxis }) {
  return (
    <section className="lens-tree-summary" aria-live="polite">
      <span className="lens-kicker">EIXO SELECIONADO</span>
      <div className="lens-tree-summary-head">
        <div>
          <span>{axis.shortLabel}</span>
          <h2>{axis.label}</h2>
        </div>
        <strong>{axis.score}</strong>
      </div>
      <p>{axis.question}</p>
      <div className="lens-tree-summary-stats">
        <span><b>P{Math.round(axis.percentile * 100)}</b> na sua faixa</span>
        <span><b>{axis.delta30d >= 0 ? "+" : ""}{axis.delta30d}</b> em 30 dias</span>
      </div>
      <small>Selecione os nós menores para abrir a métrica correspondente.</small>
    </section>
  );
}

function sparkPath(values: number[]): string {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  return values
    .map((value, index) => {
      const x = 8 + index * (384 / Math.max(values.length - 1, 1));
      const y = 54 - ((value - min) / span) * 42;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
}

function LensTrajectory({ data }: { data: LensMockView }) {
  const values = data.trajectory.days.map((day) => day.cr);
  return (
    <section className="lens-trajectory" aria-labelledby="lens-trajectory-title">
      <div className="lens-trajectory-copy">
        <span className="lens-kicker">TRAJETÓRIA · 30 DIAS</span>
        <h2 id="lens-trajectory-title">A curva voltou a apontar para cima.</h2>
      </div>
      <div className="lens-trajectory-chart">
        <svg viewBox="0 0 400 64" role="img">
          <title>Evolução demonstrativa de PDL nos últimos oito dias</title>
          <path className="lens-trajectory-area" d={`${sparkPath(values)} L 392 60 L 8 60 Z`} />
          <path className="lens-trajectory-line" d={sparkPath(values)} />
          <circle cx="392" cy="12" r="4" />
        </svg>
        <div className="lens-trajectory-days" aria-hidden="true">
          <span>{data.trajectory.days[0].day}</span>
          <span>{data.trajectory.days.at(-1)?.day}</span>
        </div>
      </div>
      <div className="lens-trajectory-stats">
        <div><span>PDL</span><b>+{data.trajectory.crDelta30d}</b></div>
        <div><span>Ranking</span><b>+{data.trajectory.rankDelta30d} posições</b></div>
        <div><span>Ritmo</span><b>{data.trajectory.days.at(-1)?.games} jogos/dia</b></div>
      </div>
    </section>
  );
}

function LensMetricBar({ metric }: { metric: LensMetric }) {
  const score = metric.score ?? 0;
  const style = { "--lens-score": `${score}%` } as CSSProperties;
  return (
    <div className="lens-metric-bar" style={style} aria-hidden="true">
      <div className="lens-metric-track">
        <i className={`lens-metric-fill is-${scoreTone(score)}`} />
        <span className="lens-marker is-cohort" style={{ left: `${metric.cohortScore ?? 50}%` }} />
        <span className="lens-marker is-top" style={{ left: `${metric.top100Score ?? 80}%` }} />
      </div>
      <div className="lens-metric-scale">
        <span>0</span>
        <span className="is-cohort">coorte</span>
        <span className="is-top">Top-100</span>
        <span>100</span>
      </div>
    </div>
  );
}

function LensMetricRow({ metric, selected = false }: { metric: LensMetric; selected?: boolean }) {
  if (!metric.available) {
    return (
      <article
        className={`lens-metric lens-metric-locked${selected ? " is-selected" : ""}`}
        id={`lens-metric-${metric.key}`}
      >
        <div className="lens-metric-lock-icon"><Mi name="lock" /></div>
        <div>
          <div className="lens-metric-title">
            <h3>{metric.label}</h3>
            <span>{metric.phase}</span>
          </div>
          <p>{metric.description}</p>
          <strong>{REASON_COPY[metric.reason ?? "insufficient_sample"]}</strong>
        </div>
      </article>
    );
  }

  return (
    <article
      className={`lens-metric${selected ? " is-selected" : ""}`}
      id={`lens-metric-${metric.key}`}
    >
      <div className="lens-metric-head">
        <div>
          <div className="lens-metric-title">
            <h3>{metric.label}</h3>
            <span>{metric.phase}</span>
          </div>
          <p>{metric.description}</p>
        </div>
        <div className="lens-metric-value">
          <b>{metric.display}</b>
          <small>{metric.sample} partidas</small>
        </div>
        <strong className={`lens-metric-score is-${scoreTone(metric.score ?? 0)}`}>
          {metric.score}
        </strong>
      </div>
      <LensMetricBar metric={metric} />
      <div className="lens-direction">
        {metric.direction === "down" ? "Menor é melhor ↓" : metric.direction === "up" ? "Maior é melhor ↑" : "Métrica contextual"}
      </div>
    </article>
  );
}

function AdaptViz() {
  const champions = [
    ["Fiora", 19, 88], ["Viego", 11, 77], ["Sett", 8, 69], ["Sona", 7, 63], ["Kayn", 5, 58],
  ] as const;
  return (
    <div className="lens-viz lens-viz-adapt">
      <div className="lens-viz-head"><span>POOL ATIVO</span><b>5 campeões · 0,81 entropia</b></div>
      <div className="lens-pool-orbit">
        {champions.map(([name, games, score], index) => (
          <div key={name} className={`lens-pool-champion is-${index + 1}`} style={{ "--pool-score": score / 100 } as CSSProperties}>
            <strong>{name.slice(0, 2).toUpperCase()}</strong><span>{name}</span><small>{games}j</small>
          </div>
        ))}
        <div className="lens-pool-core"><b>81</b><span>AMPLITUDE</span></div>
      </div>
    </div>
  );
}

function EconomyViz() {
  const sessions = [
    [72, 14, 14], [81, 10, 9], [68, 19, 13], [84, 7, 9], [75, 13, 12],
  ];
  return (
    <div className="lens-viz lens-viz-economy">
      <div className="lens-viz-head"><span>CONVERSÃO DE OURO</span><b>últimas 5 sessões</b></div>
      <div className="lens-spend-bars">
        {sessions.map(([items, anvils, unspent], index) => (
          <div className="lens-spend-row" key={index}>
            <span>S{index + 1}</span>
            <div><i className="is-items" style={{ width: `${items}%` }} /><i className="is-anvils" style={{ width: `${anvils}%` }} /><i className="is-unspent" style={{ width: `${unspent}%` }} /></div>
          </div>
        ))}
      </div>
      <div className="lens-viz-legend"><span>Itens</span><span>Bigornas</span><span>Parado</span></div>
    </div>
  );
}

function SurvivalViz() {
  const player = [4, 7, 11, 18, 26, 31, 25, 18, 11, 7];
  const cohort = [7, 12, 19, 27, 31, 27, 19, 11, 6, 3];
  return (
    <div className="lens-viz lens-viz-survival">
      <div className="lens-viz-head"><span>ROUNDS SOBREVIVIDOS</span><b>você × coorte</b></div>
      <div className="lens-histogram">
        {player.map((value, index) => (
          <div key={index}><i className="is-cohort" style={{ height: `${cohort[index] * 2.1}px` }} /><i className="is-player" style={{ height: `${value * 2.1}px` }} /><span>{index + 5}</span></div>
        ))}
      </div>
    </div>
  );
}

function MetaViz() {
  const champions = [
    ["Fiora", 84, 91], ["Viego", 76, 88], ["Sett", 69, 80], ["Sona", 62, 74],
  ] as const;
  return (
    <div className="lens-viz lens-viz-meta">
      <div className="lens-viz-head"><span>SEU POOL × TOP-100</span><b>nota por campeão</b></div>
      <div className="lens-meta-list">
        {champions.map(([name, you, top]) => (
          <div key={name}><b>{name}</b><div><i style={{ width: `${you}%` }} /><span style={{ left: `${top}%` }} /></div><strong>{you}</strong></div>
        ))}
      </div>
    </div>
  );
}

function ImpactViz() {
  const points = [[18, 5], [26, 4], [38, 3], [47, 2], [58, 1], [64, 2], [73, 1], [81, 1], [52, 3]];
  return (
    <div className="lens-viz lens-viz-impact">
      <div className="lens-viz-head"><span>COMBATE × COLOCAÇÃO</span><b>cada ponto é uma partida</b></div>
      <div className="lens-scatter" aria-hidden="true">
        <span className="lens-scatter-trend" />
        {points.map(([combat, place], index) => <i key={index} style={{ left: `${combat}%`, top: `${(place - 1) * 17 + 10}%` }} />)}
        <small className="is-y">colocação</small><small className="is-x">força de combate →</small>
      </div>
    </div>
  );
}

function LensAxisViz({ axis }: { axis: LensAxisKey }) {
  if (axis === "adapt") return <AdaptViz />;
  if (axis === "eco") return <EconomyViz />;
  if (axis === "surv") return <SurvivalViz />;
  if (axis === "meta") return <MetaViz />;
  return <ImpactViz />;
}

function LensAxisPanel({ axis, activeMetricKey }: { axis: LensAxis; activeMetricKey: string | null }) {
  return (
    <section
      className="lens-axis-panel"
      id={`lens-panel-${axis.key}`}
      data-axis={axis.key}
      role="region"
      aria-labelledby={`lens-axis-title-${axis.key}`}
    >
      <header className="lens-axis-head">
        <div className="lens-axis-number">0{["adapt", "eco", "surv", "meta", "impact"].indexOf(axis.key) + 1}</div>
        <div>
          <span>{axis.shortLabel} · P{Math.round(axis.percentile * 100)}</span>
          <h2 id={`lens-axis-title-${axis.key}`}>{axis.label}</h2>
          <p>{axis.question}</p>
        </div>
        <div className="lens-axis-score"><strong>{axis.score}</strong><span className={axis.delta30d >= 0 ? "is-up" : "is-down"}>{axis.delta30d >= 0 ? "+" : ""}{axis.delta30d} em 30d</span></div>
      </header>
      <div className="lens-axis-body">
        <LensAxisViz axis={axis.key} />
        <div className="lens-metric-list">
          {axis.metrics.map((entry) => (
            <LensMetricRow
              key={entry.key}
              metric={entry}
              selected={activeMetricKey === entry.key}
            />
          ))}
        </div>
      </div>
    </section>
  );
}

function LensInsights({
  data,
  onSelect,
}: {
  data: LensMockView;
  onSelect: (axis: LensAxisKey) => void;
}) {
  return (
    <section className="lens-insights" aria-labelledby="lens-insights-title">
      <div className="lens-section-heading">
        <span className="lens-kicker">SINAIS PRIORITÁRIOS</span>
        <h2 id="lens-insights-title">O que vale mexer primeiro.</h2>
      </div>
      <div className="lens-insight-grid">
        {data.insights.map((insight, index) => (
          <button key={insight.key} className={`lens-insight is-${insight.tone}`} onClick={() => onSelect(insight.axis)}>
            <span>0{index + 1} · {insight.eyebrow}</span>
            <strong>{insight.text}</strong>
            <small>ABRIR {data.axes.find((axis) => axis.key === insight.axis)?.shortLabel} <Mi name="arrow_outward" /></small>
          </button>
        ))}
      </div>
    </section>
  );
}

function LensCoverage({ data }: { data: LensMockView }) {
  const hasT1Gap = data.coverage.t1 < data.coverage.t0;
  return (
    <footer className="lens-coverage">
      <div>
        <Mi name="database" />
        <span>
          <b>Cobertura do protótipo</b>
          T0 {data.coverage.t0}/{data.window.games} ·{" "}
          {hasT1Gap
            ? `Métricas detalhadas disponíveis desde ${data.coverage.detailedSince} (${data.coverage.t1} partidas)`
            : `T1 ${data.coverage.t1}/${data.window.games}`} · T2 bloqueado
        </span>
      </div>
      <p>Os números desta tela são demonstrativos. O backend substituirá este fixture sem alterar os componentes.</p>
    </footer>
  );
}

export function Lens() {
  const scopeRef = useRef<HTMLDivElement>(null);
  const { riotId = "ArenaLab#MOCK" } = useParams<{ riotId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const decodedId = decodeURIComponent(riotId);
  const [windowSize, setWindowSize] = useState<LensWindowSize>(50);
  const [activeKey, setActiveKey] = useState<LensAxisKey>("adapt");
  const [activeMetricKey, setActiveMetricKey] = useState<string | null>(null);
  const previewState = parsePreviewState(searchParams.get("preview"));
  const data = useMemo(
    () => applyPreviewState(createLensMock(decodedId, windowSize), previewState),
    [decodedId, previewState, windowSize],
  );
  const isPartial = previewState === "partial";
  const activeAxis = data.axes.find((axis) => axis.key === activeKey) ?? data.axes[0];
  const profilePath = `/perfil/${encodeURIComponent(decodedId)}`;

  useLensEntrance(scopeRef);
  useLensAxisMotion(scopeRef, activeKey);

  useEffect(() => {
    if (!activeMetricKey) return;
    document.getElementById(`lens-metric-${activeMetricKey}`)?.scrollIntoView?.({
      behavior: "smooth",
      block: "center",
    });
  }, [activeKey, activeMetricKey]);

  const activateAxis = (key: LensAxisKey) => {
    setActiveKey(key);
    setActiveMetricKey(null);
  };

  const activateMetric = (key: LensAxisKey, metricKey: string) => {
    setActiveKey(key);
    setActiveMetricKey(metricKey);
  };

  const selectAxis = (key: LensAxisKey) => {
    activateAxis(key);
    scopeRef.current?.querySelector(".lens-axis-stage")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const clearPreview = () => {
    const next = new URLSearchParams(searchParams);
    next.delete("preview");
    setSearchParams(next, { replace: true });
  };

  return (
    <div className="shell lens-page" ref={scopeRef} data-gsap-scope>
      <div className="breadcrumb">
        <Link to="/">Início</Link><span className="sep">›</span>
        <Link to={profilePath}>Perfil</Link><span className="sep">›</span>
        <span>Lens de {decodedId}</span>
      </div>

      <LensIdentity data={data} />
      <ProfileSurfaceNav riotId={decodedId} active="lens" />

      {previewState === "loading" && (
        <main className="lens-state lens-loading-state" aria-label="Carregando Arena Lens" aria-live="polite">
          <div className="lens-skeleton is-wide" />
          <div className="lens-skeleton-grid" aria-hidden="true">
            <div className="lens-skeleton" />
            <div className="lens-skeleton" />
            <div className="lens-skeleton" />
          </div>
          <div className="lens-skeleton is-tall" aria-hidden="true" />
          <span className="sr-only">Preparando a leitura das partidas</span>
        </main>
      )}

      {previewState === "empty" && (
        <main className="lens-state lens-empty-state">
          <div className="lens-state-icon" aria-hidden="true"><Mi name="query_stats" /></div>
          <span className="lens-kicker">LENS AINDA FECHADO</span>
          <h1>Jogue algumas partidas de Arena para abrir seu Lens</h1>
          <p>Com 10 partidas o radar começa a aparecer. A partir de 20, liberamos a leitura global.</p>
          <Link to={profilePath}>Voltar ao perfil</Link>
        </main>
      )}

      {previewState === "error" && (
        <main className="lens-state lens-error-state" role="alert">
          <div className="lens-state-icon" aria-hidden="true"><Mi name="sync_problem" /></div>
          <span className="lens-kicker">LEITURA INTERROMPIDA</span>
          <h1>Não foi possível abrir o Lens</h1>
          <p>Este preview simula uma falha transitória. Seus dados mockados continuam intactos.</p>
          <button type="button" onClick={clearPreview}>Tentar novamente</button>
        </main>
      )}

      {(previewState === "ready" || previewState === "partial" || previewState === "fallback") && (
      <><section className="lens-control-bar" aria-label="Configuração do Lens">
        <div>
          <span>Janela</span>
          <div className="lens-window-options">
            {WINDOW_OPTIONS.map((option) => (
              <button
                key={option.value}
                className={windowSize === option.value ? "is-active" : ""}
                aria-pressed={windowSize === option.value}
                onClick={() => setWindowSize(option.value)}
              >{option.label}</button>
            ))}
          </div>
        </div>
        <p>
          <b>{data.window.games} partidas</b> · {data.cohort.label} · {formatNumber(data.cohort.size)} jogadores
          {data.cohort.fallback && <span className="lens-fallback-chip">Comparando com faixa ampliada</span>}
        </p>
      </section>

      {isPartial && (
        <div className="lens-partial-banner" role="status">
          <Mi name="hourglass_top" />
          <span><b>Lens parcial · faltam 6 partidas</b> Árvore provisória com 14 de 20 partidas mínimas.</span>
        </div>
      )}

      <main>
        <section className="lens-tree-stage" data-axis={activeKey}>
          <div className="lens-tree-narrative">
            <LensArchetype data={data} partial={isPartial} />
            <LensAxisSummary axis={activeAxis} />
          </div>
          <LensTree
            axes={data.axes}
            overallScore={data.overall.score}
            overallPercentile={data.overall.percentile}
            partial={isPartial}
            activeKey={activeKey}
            activeMetricKey={activeMetricKey}
            onSelectAxis={activateAxis}
            onSelectMetric={activateMetric}
          />
        </section>

        <LensTrajectory data={data} />

        <section className="lens-axis-stage">
          <LensAxisPanel
            key={activeAxis.key}
            axis={activeAxis}
            activeMetricKey={activeMetricKey}
          />
        </section>

        <LensInsights data={data} onSelect={selectAxis} />
        <LensCoverage data={data} />
        <Link className="lens-back-link" to={profilePath}><Mi name="arrow_back" />Voltar ao perfil</Link>
      </main>
      </>
      )}
    </div>
  );
}
