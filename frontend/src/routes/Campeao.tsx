/* ============================================================
   Campeao.tsx — /campeao/:championId (página do campeão)
   Recriação do mock "Campeao" (mundo handoff, escopado a .cmp-page):
   hero com splash + anel de tier · duplas em tiles · 3 charts de 15d ·
   augments por raridade + botas · itens + rail (OTPs, volume, stats).

   Tudo dado real: api.champions (linha do campeão), championBuild
   (agregado global do patch — augments/itens/botas/duplas),
   championTrend (rollup diário) e championMains (OTPs da ladder).
   Painel sem lastro não inventa número: some ou declara a ausência.
   ============================================================ */
import { useId, useMemo, useRef, useState, type CSSProperties } from "react";
import { Link, useParams } from "react-router-dom";
import "./Campeao.css";
import { api } from "../lib/api";
import { useApi } from "../hooks/useApi";
import { StateBlock, PlayerAvatar, Mi, ParticleField, BuildHoverIcon, type BuildHoverData } from "../components";
import { nf } from "../lib/format";
import {
  buildMonotoneGeometry,
  normalizeTimelineX,
  resolveChartDomain,
} from "./championChartGeometry";
import {
  STATE_SPINNER_LOOP,
  useDrawCharts,
  useGsapEntrance,
  useGsapInteractions,
  useGsapLoop,
  useGsapSwap,
  useReveal,
  type EntranceStep,
  type InteractionMotion,
} from "../lib/motion";
import type {
  BuildEntry,
  BuildTeammate,
  BuildTierKey,
  ChampionBuildVariant,
  ChampionRoundsResponse,
  ChampionTrendPoint,
  ChampTopPlayer,
  MatchupEntry,
  MatchupKind,
} from "../lib/types";

/* ── Formatadores pt-BR ───────────────────────────────────────── */
const pct1 = (n: number) => n.toFixed(1).replace(".", ",") + "%";
const pctInt = (n: number) => `${Math.round(n)}%`;
const PERCENT_DOMAIN = [0, 100] as const;
const fmtPlace = (n: number) => n.toFixed(2).replace(".", ",");
const fmtDelta = (n: number) => (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(n).toFixed(1).replace(".", ",") + "%";
const MONTH_LABELS = [
  "JAN",
  "FEV",
  "MAR",
  "ABR",
  "MAI",
  "JUN",
  "JUL",
  "AGO",
  "SET",
  "OUT",
  "NOV",
  "DEZ",
] as const;

/** "2026-07-22" → "22" (sem Date: a string já vem normalizada do rollup). */
const fmtDayNumber = (iso: string) => iso.split("-")[2] || iso;

function groupDateMonths(dates: string[]) {
  return dates.reduce<Array<{ label: string; start: number; end: number }>>(
    (groups, iso, index) => {
      const month = Number(iso.split("-")[1]);
      const label = MONTH_LABELS[month - 1] ?? "";
      const current = groups.at(-1);

      if (current?.label === label) {
        current.end = index;
      } else if (label) {
        groups.push({ label, start: index, end: index });
      }

      return groups;
    },
    [],
  );
}

/** Normaliza tier ("S+" → "splus") p/ o data-attr de cor. */
const tierKey = (t: string) => t.toLowerCase().replace("+", "plus");

/** Splash centralizada no rosto (CommunityDragon) — capa do hero e dos tiles. */
const splashOf = (championId?: number | null) =>
  championId ? `https://cdn.communitydragon.org/latest/champion/${championId}/splash-art/centered/skin/0` : undefined;

/* ── Arte com degradação silenciosa ───────────────────────────── */
function Art({ url, className }: { url?: string | null; className: string }) {
  const [failed, setFailed] = useState(false);
  if (!url || failed) return <span className={className} aria-hidden="true" />;
  return (
    <span className={className} aria-hidden="true">
      <img src={url} alt="" loading="lazy" draggable={false} onError={() => setFailed(true)} />
    </span>
  );
}

/* ── Chart de área (mesma geometria do mock: viewBox 300×158) ──── */
export function AreaChart({
  values,
  color,
  format,
  xLabels,
  marker,
  dates,
  drawDuration = 1,
  daily = false,
  domain,
}: {
  values: number[];
  color: string;
  format: (n: number) => string;
  /** Rótulos categóricos desenhados DENTRO do svg, alinhados a cada ponto. */
  xLabels?: string[];
  /** Índice destacado (pico) — linha tracejada + ponto em ouro. */
  marker?: number;
  /** Datas ISO observadas. Lacunas preservam um intervalo maior no eixo X. */
  dates?: string[];
  /** Tempo do traçado DrawSVG deste modelo. */
  drawDuration?: number;
  /** Série diária: curva monotônica e um marcador por observação real. */
  daily?: boolean;
  /** Domínio absoluto do eixo Y; percentuais usam [0, 100]. */
  domain?: readonly [number, number];
}) {
  const gid = useId().replace(/:/g, "");
  const PL = 40;
  const PR = 20;
  const PT = 16;
  const W = 300;
  const H = 158;
  const PB = daily ? 34 : 26;
  const renderedLabels =
    daily && dates?.length === values.length
      ? dates.map(fmtDayNumber)
      : xLabels;
  const monthGroups =
    daily && dates?.length === values.length ? groupDateMonths(dates) : [];

  const geom = useMemo(() => {
    if (values.length < 2) return null;
    // Domínio ancorado na média (ver resolveChartDomain): min-máx puro
    // transformava ruído de meio ponto em despencada visual.
    const resolved = domain
      ? { min: domain[0], max: domain[1] }
      : resolveChartDomain(values);
    const min = resolved.min;
    const max = resolved.max;
    const flat = max - min < 1e-9;
    const rng = flat ? 1 : max - min;
    const parsedDates =
      daily && dates?.length === values.length
        ? dates.map((date) => Date.parse(date))
        : [];
    const hasValidDates =
      parsedDates.length === values.length &&
      parsedDates.every((timestamp) => Number.isFinite(timestamp));
    const xPositions = hasValidDates
      ? normalizeTimelineX(parsedDates, PL, W - PR)
      : values.map(
          (_, index) =>
            PL + (index / (values.length - 1)) * (W - PL - PR),
        );
    const x = (i: number) => xPositions[i];
    const y = (v: number) => (flat ? PT + (H - PT - PB) / 2 : PT + (1 - (v - min) / rng) * (H - PT - PB));
    const points = values.map((value, index) => ({
      x: x(index),
      y: y(value),
    }));
    const curved = daily
      ? buildMonotoneGeometry(points, H - PB)
      : null;
    const line =
      curved?.line ??
      points
        .map(
          (point, index) =>
            `${index ? "L" : "M"}${point.x.toFixed(1)} ${point.y.toFixed(1)}`,
        )
        .join(" ");
    const area =
      curved?.area ??
      `M${x(0).toFixed(1)} ${(H - PB).toFixed(1)} ${points
        .map((point) => `L${point.x.toFixed(1)} ${point.y.toFixed(1)}`)
        .join(" ")} L${x(values.length - 1).toFixed(1)} ${(H - PB).toFixed(1)} Z`;
    const ticks = flat ? [max] : [max, (max + min) / 2, min];
    const last = values.length - 1;
    return { line, area, ticks, y, x, last };
  }, [daily, dates, domain, H, PB, values, W]);

  if (!geom) return null;
  return (
    <div
      className={`cmp-chart-plot${daily ? " cmp-chart-plot-daily" : ""}`}
    >
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-hidden="true"
        data-draw-duration={drawDuration}
      >
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.28" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {geom.ticks.map((t, i) => (
        <g key={i}>
          <text
            data-chart-y-label
            className="cmp-axis"
            x="4"
            y={(geom.y(t) + 3).toFixed(1)}
          >
            {format(t)}
          </text>
          <line
            x1={PL}
            y1={geom.y(t).toFixed(1)}
            x2={W - PR}
            y2={geom.y(t).toFixed(1)}
            stroke="rgba(255,255,255,.05)"
          />
        </g>
      ))}
      {typeof marker === "number" && values[marker] !== undefined && (
        <>
          <line
            data-chart-mark
            x1={geom.x(marker).toFixed(1)}
            y1={PT}
            x2={geom.x(marker).toFixed(1)}
            y2={H - PB}
            stroke="rgba(255,204,0,.35)"
            strokeDasharray="2 3"
          />
          <circle
            data-chart-mark
            cx={geom.x(marker).toFixed(1)}
            cy={geom.y(values[marker]).toFixed(1)}
            r="4"
            fill="#ffcc00"
          />
        </>
      )}
      <path data-chart-area d={geom.area} fill={`url(#${gid})`} />
      <path
        data-chart-line
        d={geom.line}
        fill="none"
        stroke={color}
        strokeWidth={daily ? 3.25 : 2}
        strokeLinejoin="round"
        strokeLinecap="round"
        style={{
          strokeWidth: daily ? 3.25 : 2,
          strokeLinejoin: "round",
          strokeLinecap: "round",
        }}
      />
      {(daily ? values.map((_, index) => index) : [geom.last]).map(
        (index) => (
          <circle
            data-chart-mark
            key={`point-${index}`}
            cx={geom.x(index).toFixed(1)}
            cy={geom.y(values[index]).toFixed(1)}
            r={daily ? 2 : 3}
            fill={color}
          />
        ),
      )}
      {renderedLabels?.map((l, i) =>
        l ? (
          <text
            data-chart-mark={daily ? undefined : true}
            data-chart-day-label={daily ? true : undefined}
            key={`${i}-${l}`}
            className={`cmp-axis${daily ? " cmp-axis-day" : ""}${i === marker ? " cmp-axis-peak" : ""}`}
            x={geom.x(i).toFixed(1)}
            y={daily ? H - 14 : H - 8}
            textAnchor="middle"
          >
            {l}
          </text>
        ) : null,
      )}
      {monthGroups.map((month) => (
        <text
          data-chart-month-label
          key={`${month.label}-${month.start}`}
          className="cmp-axis cmp-axis-month"
          x={((geom.x(month.start) + geom.x(month.end)) / 2).toFixed(1)}
          y={H - 3}
          textAnchor="middle"
        >
          {month.label}
        </text>
      ))}
      </svg>
    </div>
  );
}

/* ── Chart de barras (estágios discretos — sem geometria de curva,
   cada categoria é sua própria medida, não um ponto de uma série contínua) */
function BarChart({
  values,
  labels,
  color,
  format,
  marker,
  domain,
  dates,
  daily = false,
}: {
  values: number[];
  labels?: string[];
  color: string;
  format: (n: number) => string;
  /** Índice destacado (pico) — barra em ouro. Sem uso em série diária. */
  marker?: number;
  domain?: readonly [number, number];
  /** Datas ISO — habilita agrupamento de mês sob o eixo (série diária). */
  dates?: string[];
  /** Série diária (10+ barras): rótulo por dia (compacto, sem valor sobre
      cada barra — lotaria o svg) + agrupamento de mês, igual ao AreaChart. */
  daily?: boolean;
}) {
  const PL = 40;
  const PR = 20;
  const PT = 16;
  const PB = daily ? 34 : 26;
  const W = 300;
  const H = 158;
  const dayLabels = daily && dates?.length === values.length ? dates.map(fmtDayNumber) : labels;
  const monthGroups = daily && dates?.length === values.length ? groupDateMonths(dates) : [];

  const geom = useMemo(() => {
    if (!values.length) return null;
    const resolved = domain ? { min: domain[0], max: domain[1] } : resolveChartDomain(values);
    const min = resolved.min;
    const max = resolved.max;
    const rng = max - min < 1e-9 ? 1 : max - min;
    const plotW = W - PL - PR;
    const slot = plotW / values.length;
    const barW = daily ? Math.min(14, slot * 0.6) : Math.min(38, slot * 0.5);
    const y = (v: number) => PT + (1 - (v - min) / rng) * (H - PT - PB);
    const bars = values.map((value, index) => {
      const cx = PL + slot * (index + 0.5);
      const top = y(value);
      return { cx, top, x: cx - barW / 2, width: barW, height: Math.max(H - PB - top, 0) };
    });
    const ticks = [max, (max + min) / 2, min];
    return { bars, ticks, y };
  }, [values, domain, daily, PB, PL, PR, PT, H, W]);

  if (!geom) return null;
  return (
    <div className={`cmp-chart-plot${daily ? " cmp-chart-plot-daily" : ""}`}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" role="img" aria-hidden="true">
        {geom.ticks.map((t, i) => (
          <g key={i}>
            <text className="cmp-axis" x="4" y={(geom.y(t) + 3).toFixed(1)}>
              {format(t)}
            </text>
            <line
              x1={PL}
              y1={geom.y(t).toFixed(1)}
              x2={W - PR}
              y2={geom.y(t).toFixed(1)}
              stroke="rgba(255,255,255,.05)"
            />
          </g>
        ))}
        {geom.bars.map((bar, index) => (
          <g key={index}>
            <rect
              data-chart-mark
              x={bar.x.toFixed(1)}
              y={bar.top.toFixed(1)}
              width={bar.width.toFixed(1)}
              height={bar.height.toFixed(1)}
              rx={daily ? 2 : 4}
              fill={index === marker ? "#ffcc00" : color}
              fillOpacity={index === marker ? 1 : 0.85}
            />
            {!daily && (
              <text
                className={`cmp-axis${index === marker ? " cmp-axis-peak" : ""}`}
                x={bar.cx.toFixed(1)}
                y={(bar.top - 6).toFixed(1)}
                textAnchor="middle"
              >
                {format(values[index])}
              </text>
            )}
            {dayLabels?.[index] && (
              <text
                className={`cmp-axis${daily ? " cmp-axis-day" : ""}${index === marker ? " cmp-axis-peak" : ""}`}
                x={bar.cx.toFixed(1)}
                y={daily ? H - 14 : H - 8}
                textAnchor="middle"
              >
                {dayLabels[index]}
              </text>
            )}
          </g>
        ))}
        {monthGroups.map((month) => (
          <text
            key={`${month.label}-${month.start}`}
            className="cmp-axis cmp-axis-month"
            x={((geom.bars[month.start].cx + geom.bars[month.end].cx) / 2).toFixed(1)}
            y={H - 3}
            textAnchor="middle"
          >
            {month.label}
          </text>
        ))}
      </svg>
    </div>
  );
}

function TrendCard({
  title,
  sub,
  series,
  pick,
  color,
  format,
  drawDuration,
}: {
  title: string;
  sub: string;
  series: ChampionTrendPoint[];
  pick: (p: ChampionTrendPoint) => number;
  color: string;
  format: (n: number) => string;
  drawDuration: number;
}) {
  const values = series.map(pick);
  /* Escala fixa 0–100% escondia a variação real (ex.: 1º lugar oscilando
     entre 15–27%, escolha entre décimos de 1%) num traço quase reto colado
     no fundo. Ancora no valor médio da série (mesma lógica do power spike),
     só respeitando o piso de 0% — uma queda real ainda não pode "sair" do
     gráfico por cima. */
  const domain = useMemo(() => {
    const d = resolveChartDomain(values, { bounds: [0, Infinity] });
    return [d.min, d.max] as const;
  }, [values]);
  return (
    <div className="cmp-panel cmp-chart cmp-chart-daily">
      <h3>{title}</h3>
      <div className="cmp-chart-sub">{sub}</div>
      <AreaChart
        values={values}
        dates={series.map((point) => point.date)}
        color={color}
        format={format}
        drawDuration={drawDuration}
        domain={domain}
        daily
      />
    </div>
  );
}

/* ── Power spike: força por estágio de draft ──────────────────────
   Não é round literal da partida (Arena não tem timeline pública na API da
   Riot) — o eixo é o estágio do draft de augments (prata/ouro/prismático),
   o spike de força real que o próprio modo define. Só 3 pontos, então todo
   rótulo cabe; o pico ganha marcador em ouro e a escala absoluta 0–100%
   mantém a magnitude honesta. */
function RoundSpikeCard({ name, data }: { name: string; data: ChampionRoundsResponse }) {
  const rounds = data.rounds;
  const peakIdx = rounds.findIndex((r) => r.round === data.peakRound);
  const peak = peakIdx >= 0 ? rounds[peakIdx] : null;
  return (
    <div className="cmp-panel cmp-chart">
      <h3>{name} · Power spike</h3>
      <div className="cmp-chart-sub">força por estágio de draft (prata → ouro → prismático)</div>
      <BarChart
        values={rounds.map((r) => r.winRate)}
        labels={rounds.map((r) => r.label)}
        color="#9b5cff"
        format={(v) => `${Math.round(v)}%`}
        marker={peakIdx >= 0 ? peakIdx : undefined}
        domain={PERCENT_DOMAIN}
      />
      {peak && (
        <div className="cmp-peak">
          pico: <b>{peak.label}</b>
          <span className="tnum">{pct1(peak.winRate)}</span>
          <em className="tnum">{nf(peak.games)} jogos</em>
        </div>
      )}
    </div>
  );
}

/** Painel que separa carga, falha e ausência definitiva sem estimar números. */
function ChartStateCard({
  title,
  sub,
  loading,
  loadingLabel,
  error,
  errorLabel,
  onRetry,
  emptyLabel,
  span2,
}: {
  title: string;
  sub: string;
  loading: boolean;
  loadingLabel: string;
  error: Error | null;
  errorLabel: string;
  onRetry: () => void;
  emptyLabel: string;
  span2?: boolean;
}) {
  return (
    <div className={`cmp-panel cmp-chart${span2 ? " cmp-chart-span2" : ""}`}>
      <h3>{title}</h3>
      <div className="cmp-chart-sub">{sub}</div>
      <StateBlock
        compact
        loading={loading}
        loadingLabel={loadingLabel}
        error={error}
        errorLabel={errorLabel}
        onRetry={onRetry}
        empty={!loading && !error}
        emptyLabel={emptyLabel}
      />
    </div>
  );
}

/* ── Tile de augment (raridade real do draft) ─────────────────── */
type Rarity = "prism" | "gold" | "silver";
const RARITY_OF: Record<string, Rarity> = { prismatic: "prism", gold: "gold", silver: "silver" };

/** A arte colorida do augment é a `_large`; a `_small` do CDragon é a versão
    chapada (foi o que fazia todos os tiles lerem como brancos). Degrada para
    a `_small` se a grande não existir — mesmo par usado no /winrate. */
function AugArt({ url }: { url?: string | null }) {
  const large = url?.replace("_small.png", "_large.png") ?? null;
  const [failedLarge, setFailedLarge] = useState(false);
  const src = failedLarge ? url : large;
  if (!src) return <span className="cmp-augt-in" aria-hidden="true" />;
  return (
    <span className="cmp-augt-in" aria-hidden="true">
      <img src={src} alt="" loading="lazy" draggable={false} onError={() => setFailedLarge(true)} />
    </span>
  );
}

function AugTile({ entry, rarity, size }: { entry: BuildEntry; rarity: Rarity; size: "big" | "md" }) {
  /* A raridade servida pelo backend manda; `rarity` é só o fallback de
     contexto (a coluna em que o augment está). */
  const r = (entry.rarity && RARITY_OF[entry.rarity]) || rarity;
  return (
    <span className={`cmp-augt cmp-augt-${r} cmp-augt-${size}`} aria-hidden="true">
      <AugArt url={entry.iconUrl} />
    </span>
  );
}

/** `BuildEntry` -> dados do popup de hover (`BuildHoverIcon`, mesmo padrão
    do /winrate e /augments — ver Winrate.tsx's buildHoverData). */
function buildHoverData(e: BuildEntry): BuildHoverData {
  return {
    name: e.name,
    iconUrl: e.iconUrl,
    badge: e.tier,
    badgeClassName: `tier-${tierKey(e.tier)}`,
    stats: [
      { label: "Escolha", value: pct1(e.pickRate) },
      { label: "1º lugar", value: pctInt(e.top1) },
      { label: "Top 4", value: pctInt(e.top4) },
      { label: "Col. média", value: fmtPlace(e.avgPlace) },
      { label: "Partidas", value: nf(e.games) },
    ],
  };
}

function AugGrid({ entries, rarity, cols }: { entries: BuildEntry[]; rarity: Rarity; cols: number }) {
  if (!entries.length) return <p className="cmp-empty">Sem amostra suficiente neste patch.</p>;
  return (
    <div className="cmp-augrid" style={{ "--cols": cols } as CSSProperties}>
      {entries.map((a) => (
        <BuildHoverIcon as="div" className="cmp-augcell" key={a.id} data={buildHoverData(a)}>
          <AugTile entry={a} rarity={rarity} size={cols <= 3 ? "big" : "md"} />
          <TierPill tier={a.tier} />
          <span className="cmp-augcell-pk tnum">{pct1(a.pickRate)} escolha</span>
        </BuildHoverIcon>
      ))}
    </div>
  );
}

/* ── Tiles de matchup ─────────────────────────────────────────
   Uma forma normalizada serve as duas abas e as duas fontes (o agregado
   de build, que só tem a ponta boa, e o endpoint de matchups). */
interface Face {
  championId: number;
  name: string;
  games: number;
  winRate: number;
  delta: number;
  avgPlace: number;
}
const faceFromTeammate = (t: BuildTeammate, base: number): Face => ({
  championId: t.championId,
  name: t.name,
  games: t.games,
  winRate: t.top4,
  delta: t.top4 - base,
  avgPlace: t.avgPlace,
});
const faceFromMatchup = (m: MatchupEntry): Face => ({
  championId: m.championId,
  name: m.name,
  games: m.games,
  winRate: m.winRate,
  delta: m.delta,
  avgPlace: m.avgPlace,
});

function MatchupTile({ f, unit }: { f: Face; unit: string }) {
  const sign = f.delta >= 0 ? "pos" : "neg";
  return (
    <Link
      to={`/campeao/${f.championId}`}
      className={`cmp-mtile cmp-mtile-${sign}`}
      title={`${f.name} · winrate ${pct1(f.winRate)} · col. média ${fmtPlace(f.avgPlace)} · ${nf(f.games)} ${unit}`}
    >
      <Art url={splashOf(f.championId)} className="cmp-mtile-art" />
      <span className="cmp-mtile-shade" aria-hidden="true" />
      <span className="cmp-mtile-body">
        <span className="cmp-mtile-d tnum">{fmtDelta(f.delta)}</span>
        <span className="cmp-mtile-g tnum">{nf(f.games)} jogos</span>
        <span className="cmp-mtile-nm">{f.name}</span>
      </span>
    </Link>
  );
}

/** O tile do meio: a saída para a lista inteira, no lugar do 6º campeão. */
function FullListTile() {
  return (
    <Link to="/winrate" className="cmp-mtile cmp-mtile-more">
      <Mi name="apps" />
      <small>Lista completa</small>
    </Link>
  );
}

/** Lacuna declarada: ocupa os 5 slots do lado que ainda não tem dado. */
function MissingSide({ label }: { label: string }) {
  return (
    <div className="cmp-mtile-void">
      <Mi name="pending" />
      <span>{label}</span>
    </div>
  );
}

/* ── Linha de OTP (main da ladder BR) ─────────────────────────── */
function OtpRow({ p, pos }: { p: ChampTopPlayer; pos: number }) {
  const inner = (
    <>
      <span className="cmp-otp-pos tnum">{pos}</span>
      <span className="cmp-otp-who">
        <PlayerAvatar colors={p.avatar} url={p.profileIconUrl ?? undefined} alt={p.name} size={26} />
        <span className="cmp-otp-nm">{p.name}</span>
      </span>
      <span className="cmp-otp-w tnum">{pctInt(p.winrate)}</span>
      <span className="cmp-otp-gm tnum">{nf(p.games)}</span>
    </>
  );
  if (!p.handle) return <div className="cmp-otpr">{inner}</div>;
  return (
    <Link
      to={`/perfil/${encodeURIComponent(`${p.name}${p.handle}`)}`}
      className="cmp-otpr cmp-otpr-link"
      aria-label={`Perfil de ${p.name}`}
    >
      {inner}
    </Link>
  );
}

/* ── Selo de tier (força de item/augment) ─────────────────────
   A força de item e augment sai como TIER, nunca como winrate em %:
   a Riot não permite publicar taxa de vitória de item/augment. A única
   porcentagem permitida nessas superfícies é a taxa de ESCOLHA. */
function TierPill({ tier }: { tier: BuildTierKey }) {
  return <span className={`cmp-tierpill t-${tierKey(tier)}`}>{tier}</span>;
}

/* ── Célula de item / bota ────────────────────────────────────── */
function ItemCell({ e, top }: { e: BuildEntry; top?: boolean }) {
  return (
    <BuildHoverIcon as="div" className={`cmp-bcell${top ? " cmp-bcell-top" : ""}`} data={buildHoverData(e)}>
      <Art url={e.iconUrl} className="cmp-it" />
      <TierPill tier={e.tier} />
      <span className="cmp-bcell-pk tnum">{pct1(e.pickRate)}</span>
    </BuildHoverIcon>
  );
}

/* ── Variantes de build ────────────────────────────────────────
   A linha carrega o par inteiro: a itemização E os augments sem os
   quais ela não fecha. O fio tracejado entre as duas faixas é o que
   diz "no Arena o augment é pré-requisito, não enfeite". */
function BuildVariantRow({ v, rank }: { v: ChampionBuildVariant; rank: number }) {
  return (
    <article className="cmp-bvar">
      <header className="cmp-bvar-head">
        <span className={`cmp-seal t-${tierKey(v.tier)}`} aria-label={`Tier ${v.tier}`}>
          {v.tier}
        </span>
        <span className="cmp-bvar-id">
          <span className="cmp-bvar-nm">{v.name}</span>
          <span className="cmp-bvar-sub tnum">
            {nf(v.games)} jogos · {pct1(v.pickRate)} das partidas
          </span>
        </span>
        {/* Sem winrate em % aqui: a força da build é o selo de tier à esquerda.
            Colocação média é dado de placement (permitido) e escolha é % de pick. */}
        <span className="cmp-bvar-kpis">
          <span className="cmp-bvar-kpi">
            <b className="tnum">{fmtPlace(v.avgPlace)}</b>
            <em>Col. média</em>
          </span>
          <span className="cmp-bvar-kpi">
            <b className="tnum">{pct1(v.pickRate)}</b>
            <em>Escolha</em>
          </span>
          <span className="cmp-bvar-kpi">
            <b className="tnum">{nf(v.games)}</b>
            <em>Jogos</em>
          </span>
        </span>
        <span className="cmp-bvar-rank tnum" aria-hidden="true">
          {rank}
        </span>
      </header>

      <div className="cmp-track">
        <span className="cmp-track-l">Itens</span>
        <div className="cmp-track-row">
          {v.items.map((it, i) => (
            <span className="cmp-track-slot" key={it.id} title={`${i + 1}º · ${it.name}`}>
              <Art url={it.iconUrl} className="cmp-it" />
              <em className="tnum">{i + 1}</em>
            </span>
          ))}
        </div>
      </div>

      <div className="cmp-track cmp-track-aug">
        <span className="cmp-track-l">
          Augments necessários
          <Mi name="bolt" />
        </span>
        <div className="cmp-track-row">
          {v.requiredAugments.map((a) => (
            <span
              className="cmp-track-slot"
              key={a.id}
              title={`${a.name} · tier ${a.tier} · escolha ${pct1(a.pickRate)} nesta build`}
            >
              <AugTile entry={a} rarity="prism" size="md" />
              <em className="cmp-track-nm">{a.name}</em>
            </span>
          ))}
        </div>
      </div>
    </article>
  );
}

/** Esqueleto que mostra a forma da tabela sem inventar um número sequer. */
function BuildVariantsSkeleton() {
  return (
    <div className="cmp-bskel" aria-hidden="true">
      {["S", "A", "B"].map((t) => (
        <article className="cmp-bvar cmp-bvar-skel" key={t}>
          <header className="cmp-bvar-head">
            <span className={`cmp-seal t-${tierKey(t)}`}>{t}</span>
            <span className="cmp-bvar-id">
              <span className="cmp-skel-bar" style={{ width: 108 }} />
              <span className="cmp-skel-bar" style={{ width: 148, height: 8 }} />
            </span>
          </header>
          <div className="cmp-track">
            <span className="cmp-track-l">Itens</span>
            <div className="cmp-track-row">
              {[0, 1, 2, 3, 4].map((i) => (
                <span className="cmp-skel-slot" key={i} />
              ))}
            </div>
          </div>
          <div className="cmp-track cmp-track-aug">
            <span className="cmp-track-l">Augments necessários</span>
            <div className="cmp-track-row">
              {[0, 1, 2].map((i) => (
                <span className="cmp-skel-slot cmp-skel-slot-aug" key={i} />
              ))}
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}

/* ── Cabeçalho de painel ──────────────────────────────────────── */
function Ph({ icon, title, side }: { icon: string; title: string; side?: string }) {
  return (
    <div className="cmp-ph">
      <Mi name={icon} />
      <span className="cmp-ph-t">{title}</span>
      {side && <span className="cmp-ph-s">{side}</span>}
    </div>
  );
}

/* ── Página ───────────────────────────────────────────────────── */
/** Rótulos das duas leituras — a aba troca o dado E o vocabulário. */
const MATCHUP_TABS: Record<MatchupKind, { tab: string; good: string; bad: string; unit: string }> = {
  duo: { tab: "Sinergia", good: "Boa dupla no time", bad: "Péssima combinação", unit: "jogos juntos" },
  versus: { tab: "Matchups", good: "Bom contra", bad: "Mau contra", unit: "confrontos" },
};

const CHAMPION_ENTRANCE: EntranceStep[] = [
  {
    selector: ".cmp-crumb",
    from: { opacity: 0, y: -8 },
    duration: 0.28,
  },
  {
    selector: ".cmp-hero-veil",
    from: { clipPath: "inset(0 0 0 78%)" },
    duration: 0.7,
    position: "-=0.08",
  },
  {
    selector: ".cmp-hero-por",
    from: { opacity: 0, x: -24, scale: 0.94, filter: "blur(6px)" },
    duration: 0.55,
    position: "-=0.52",
  },
  {
    selector: ".cmp-hero-id",
    from: { opacity: 0, y: 16 },
    duration: 0.46,
    position: "-=0.38",
  },
  {
    selector: ".cmp-tierbadge, .cmp-k",
    from: { opacity: 0, y: 14, scale: 0.96 },
    duration: 0.42,
    stagger: 0.055,
    position: "-=0.3",
  },
  {
    selector: ".cmp-hero-meta",
    from: { opacity: 0, y: 10 },
    duration: 0.34,
    position: "-=0.2",
  },
  {
    selector: ".cmp-mcard",
    from: { opacity: 0, y: 18, clipPath: "inset(0 0 10% 0 round 12px)" },
    duration: 0.48,
    position: "-=0.14",
  },
];

const CHAMPION_INTERACTIONS: InteractionMotion[] = [
  { trigger: ".cmp-mtile", to: { y: -3 } },
  { trigger: ".cmp-augcell", target: ".cmp-augt", to: { scale: 1.05 } },
  { trigger: ".cmp-bcell", target: ".cmp-it", to: { scale: 1.05 } },
  { trigger: ".cmp-track-slot", target: ".cmp-it", to: { scale: 1.05 } },
  { trigger: ".cmp-bvar", to: { y: -2 } },
  { trigger: ".cmp-otpr-link", to: { x: 3 } },
  { trigger: ".cmp-fullbtn", target: ".mi", to: { x: 3 } },
];

export function Campeao() {
  const { championId } = useParams<{ championId: string }>();
  const id = Number(championId);

  const tierlist = useApi(() => api.champions({}), []);
  const build = useApi(() => api.championBuild(id), [id]);
  const trend = useApi(() => api.championTrend(id, { days: 15 }), [id]);
  // retry:false sobrevive de quando estes endpoints eram 404 permanente —
  // inofensivo agora que respondem 200, mas evita reintroduzir o martelo de
  // retry (~2min) se algum voltar a 404 no futuro.
  const rounds = useApi(() => api.championRounds(id), [id], {}, { retry: false });
  const mains = useApi(() => api.championMains(id, { limit: 10 }), [id]);

  const [kind, setKind] = useState<MatchupKind>("duo");
  const [duoQuery, setDuoQuery] = useState("");

  const matchups = useApi(() => api.championMatchups(id, { kind, limit: 5 }), [id, kind], {}, { retry: false });
  const variants = useApi(() => api.championBuildVariants(id), [id], {}, { retry: false });

  const row = useMemo(
    () => tierlist.data?.table.find((r) => r.championId === id) ?? null,
    [tierlist.data, id],
  );

  const name = row?.name ?? build.data?.name ?? trend.data?.name ?? `Campeão #${id}`;
  const tier = row?.tier ?? build.data?.tier ?? null;
  const tk = tier ? tierKey(tier) : "d";
  const iconUrl = row?.championIconUrl ?? build.data?.championIconUrl ?? trend.data?.championIconUrl ?? null;

  /* Os dois lados do grid. Fonte preferida = endpoint de matchups (tem as
     duas pontas); enquanto ele não existe, a aba `duo` cai no agregado de
     build, que só conhece os BONS parceiros — a ponta ruim fica declarada
     como lacuna em vez de ser preenchida por inferência. */
  const sides = useMemo(() => {
    const q = duoQuery.trim().toLowerCase();
    const match = (f: Face) => !q || f.name.toLowerCase().includes(q);

    if (matchups.data) {
      return {
        best: matchups.data.best.map(faceFromMatchup).filter(match).slice(0, 5),
        worst: matchups.data.worst.map(faceFromMatchup).filter(match).slice(0, 5),
        partial: false,
      };
    }
    if (kind === "duo" && build.data?.teammates.length) {
      const base = build.data.top4;
      return {
        best: build.data.teammates
          .map((t) => faceFromTeammate(t, base))
          .sort((a, b) => b.delta - a.delta)
          .filter(match)
          .slice(0, 5),
        worst: [] as Face[],
        partial: true,
      };
    }
    return { best: [] as Face[], worst: [] as Face[], partial: true };
  }, [matchups.data, build.data, kind, duoQuery]);

  const labels = MATCHUP_TABS[kind];

  const series = trend.data?.series ?? [];
  const hasTrend = series.length >= 2;
  const hasRounds = (rounds.data?.rounds.length ?? 0) >= 2;
  /* 10 prismáticos em 5×2 — a grade casa a altura do card com a das botas. */
  const prismaticItems = (build.data?.prismaticItems ?? []).slice(0, 10);

  const hasBuild = Boolean(build.data && build.data.games > 0);

  /* Movimento: re-arma quando o dado chega (numa SPA o conteúdo nasce
     depois do mount, então armar só na montagem não pegaria nada). */
  const pageRef = useRef<HTMLDivElement>(null);
  const ready = Boolean(row || hasBuild);
  useGsapEntrance(pageRef, { steps: CHAMPION_ENTRANCE, deps: [ready, id] });
  useReveal(pageRef, {
    blocks: ".cmp-panel:not(.cmp-mcard)",
    deps: [ready, hasRounds, hasTrend, id],
  });
  useDrawCharts(pageRef, [hasRounds, hasTrend, id]);
  useGsapLoop(pageRef, [STATE_SPINNER_LOOP]);
  useGsapSwap(pageRef, ".cmp-mcard", `${kind}|${duoQuery}|${Boolean(matchups.data)}`, {
    from: { opacity: 0, y: 10 },
  });
  useGsapInteractions(pageRef, CHAMPION_INTERACTIONS);

  const coreLoading = tierlist.loading && build.loading;
  const coreError = build.error && !row && !tierlist.loading ? build.error : null;
  /* O /build responde 200 com amostra zerada para id inexistente — sem linha na
     tierlist E sem agregado não há campeão nenhum, e a casca vazia leria como bug. */
  const unknown = !coreLoading && !coreError && !row && !build.loading && !hasBuild;

  return (
    <div
      className="cmp-page"
      ref={pageRef}
      data-gsap-scope
      style={{ "--tc": `var(--t-${tk})` } as CSSProperties}
    >
      <div className="cmp-amb" aria-hidden="true" />
      <ParticleField variant="route" />

      <main className="cmp-wrap">
        <nav className="cmp-crumb" aria-label="Trilha">
          <Link to="/winrate">Winrate</Link>
          <Mi name="chevron_right" />
          <Link to="/winrate">Arena 3v3</Link>
          <Mi name="chevron_right" />
          <b>{name}</b>
        </nav>

        <StateBlock loading={coreLoading} error={coreError} empty={unknown} onRetry={build.retry}>
          {/* ═══ HERO ═══ */}
          <section className="cmp-hero">
            <Art url={splashOf(id)} className="cmp-hero-bg" />
            <span className="cmp-hero-veil" aria-hidden="true" />
            <div className="cmp-hero-inner">
              <Art url={iconUrl} className="cmp-hero-por" />
              <div className="cmp-hero-id">
                <div className="cmp-hero-role">{row?.role ? row.role.toUpperCase() : "ARENA"}</div>
                <h1 className="cmp-hero-name">{name}</h1>
                <div className="cmp-hero-tags">
                  {row && <span className="cmp-tag">#{row.rank} na tierlist</span>}
                  {row && <span className="cmp-tag">{nf(row.games)} partidas</span>}
                  {row && row.winrateDelta !== 0 && (
                    <span className={`cmp-tag cmp-tag-${row.winrateDelta > 0 ? "up" : "down"}`}>
                      {fmtDelta(row.winrateDelta)} em 7d
                    </span>
                  )}
                </div>
              </div>
              {tier && (
                <div className="cmp-tierbadge">
                  <b>{tier}</b>
                  <span>TIER</span>
                </div>
              )}
              {row && (
                <div className="cmp-kstats">
                  <div className="cmp-k">
                    <div className="cmp-k-v green tnum">{pct1(row.top4)}</div>
                    <div className="cmp-k-l">Winrate</div>
                  </div>
                  <div className="cmp-k">
                    <div className="cmp-k-v gold tnum">{pct1(row.first)}</div>
                    <div className="cmp-k-l">1º lugar</div>
                  </div>
                  <div className="cmp-k">
                    <div className="cmp-k-v tnum">{fmtPlace(row.avgPlace)}</div>
                    <div className="cmp-k-l">Col. média</div>
                  </div>
                  <div className="cmp-k">
                    <div className="cmp-k-v tnum">{pct1(row.pickRate)}</div>
                    <div className="cmp-k-l">Escolha</div>
                  </div>
                </div>
              )}
            </div>
            <div className="cmp-hero-meta">
              <span className="cmp-fchip">
                <Mi name="public" />
                BR
              </span>
              <span className="cmp-fchip">
                <Mi name="stadium" />
                Arena 3v3
              </span>
              {tierlist.data?.patch && (
                <span className="cmp-fchip">
                  <Mi name="schedule" />
                  Patch {tierlist.data.patch}
                </span>
              )}
            </div>
          </section>

          {/* ═══ MATCHUPS / SINERGIA ═══ */}
          <section className="cmp-panel cmp-mcard">
            <div className="cmp-mtop">
              <div className="cmp-mtitle">
                <Mi name="swords" />
                <span>{labels.tab.toUpperCase()} · {name.toUpperCase()}</span>
              </div>
              <div className="cmp-mtools">
                <div className="cmp-tabs" role="tablist" aria-label="Tipo de confronto">
                  {(Object.keys(MATCHUP_TABS) as MatchupKind[]).map((k) => (
                    <button
                      key={k}
                      type="button"
                      role="tab"
                      aria-selected={kind === k}
                      className={kind === k ? "on" : ""}
                      onClick={() => setKind(k)}
                    >
                      {MATCHUP_TABS[k].tab}
                    </button>
                  ))}
                </div>
                <label className="cmp-msearch">
                  <Mi name="search" />
                  <input
                    type="text"
                    value={duoQuery}
                    onChange={(e) => setDuoQuery(e.target.value)}
                    placeholder="Pesquisar campeão"
                    aria-label={`Pesquisar campeão em ${labels.tab}`}
                  />
                </label>
              </div>
            </div>

            <div className="cmp-mlabels">
              <span className="good">{labels.good}</span>
              <span className="bad">{labels.bad}</span>
            </div>

            {/* Um lado vazio só é LACUNA quando o agregado não tem aquela ponta
                (`partial`). Vazio por causa da busca é resultado de filtro — anunciar
                "em preparação" ali seria mentir sobre o estado do backend. */}
            <StateBlock
              compact
              loading={matchups.loading && !sides.best.length && !sides.worst.length}
              loadingLabel="Carregando confrontos…"
              error={!sides.best.length && !sides.worst.length ? matchups.error : null}
              errorLabel="Não foi possível carregar os confrontos."
              onRetry={matchups.retry}
            >
              {duoQuery && !sides.best.length && !sides.worst.length ? (
                <p className="cmp-empty">Nenhum campeão com esse nome nesta lista.</p>
              ) : (
                <div className="cmp-mgrid">
                  {sides.best.length
                    ? sides.best.map((f) => <MatchupTile key={`b${f.championId}`} f={f} unit={labels.unit} />)
                    : sides.partial && <MissingSide label={`${labels.good}: agregado em preparação`} />}
                  <FullListTile />
                  {sides.worst.length
                    ? sides.worst.map((f) => <MatchupTile key={`w${f.championId}`} f={f} unit={labels.unit} />)
                    : sides.partial && <MissingSide label={`${labels.bad}: agregado em preparação`} />}
                </div>
              )}
            </StateBlock>
          </section>

          {/* ═══ CHARTS — power spike (por round) + tendência (por dia) ═══ */}
          <section className="cmp-charts">
            {hasRounds ? (
              <RoundSpikeCard name={name} data={rounds.data!} />
            ) : (
              <ChartStateCard
                title={`${name} · Power spike`}
                sub="força por estágio de draft · prata → ouro → prismático"
                loading={rounds.loading}
                loadingLabel="Carregando força por estágio…"
                error={rounds.error}
                errorLabel="Não foi possível carregar a força por estágio de draft."
                onRetry={rounds.retry}
                emptyLabel="Ainda sem amostra suficiente de augments para este campeão nesta temporada."
              />
            )}

            {hasTrend ? (
              <>
                <TrendCard
                  title={`${name} · 1º lugar`}
                  sub={`últimos ${trend.data?.days ?? 15} dias`}
                  series={series}
                  pick={(p) => p.first}
                  color="#ffcc00"
                  format={(v) => `${Math.round(v)}%`}
                  drawDuration={2}
                />
                <TrendCard
                  title={`${name} · Escolha`}
                  sub={`últimos ${trend.data?.days ?? 15} dias`}
                  series={series}
                  pick={(p) => p.pickRate}
                  color="#5aa9ff"
                  format={pct1}
                  drawDuration={1}
                />
              </>
            ) : (
              <ChartStateCard
                title="Tendência"
                sub="últimos 15 dias"
                loading={trend.loading}
                loadingLabel="Carregando histórico diário…"
                error={trend.error}
                errorLabel="Não foi possível carregar o histórico diário."
                onRetry={trend.retry}
                emptyLabel="Histórico diário ainda curto para desenhar a curva — a série começa a valer com alguns dias de registro."
                span2
              />
            )}
          </section>

          {/* ═══ AUGMENTS POR RARIDADE + BOTAS ═══ */}
          <section className="cmp-row3">
            <div className="cmp-panel cmp-card">
              <Ph icon="diamond" title="Augments prismáticos" side="Rodada 4" />
              <StateBlock
                compact
                loading={build.loading}
                loadingLabel="Carregando agregado de build…"
                error={build.error}
                errorLabel="Não foi possível carregar os augments prismáticos."
                onRetry={build.retry}
                empty={!build.loading && !build.error && !hasBuild}
                emptyLabel="Sem agregado de build neste patch."
              >
                {build.data && (
                  <AugGrid entries={build.data.augments.prismatic.slice(0, 6)} rarity="prism" cols={3} />
                )}
              </StateBlock>
            </div>

            <div className="cmp-panel cmp-card">
              <Ph icon="hexagon" title="Augments de ouro" side="Rodada 3" />
              <StateBlock
                compact
                loading={build.loading}
                loadingLabel="Carregando agregado de build…"
                error={build.error}
                errorLabel="Não foi possível carregar os augments de ouro."
                onRetry={build.retry}
                empty={!build.loading && !build.error && !hasBuild}
                emptyLabel="Sem agregado de build neste patch."
              >
                {build.data && <AugGrid entries={build.data.augments.gold.slice(0, 6)} rarity="gold" cols={3} />}
              </StateBlock>
            </div>

            <div className="cmp-panel cmp-card">
              <Ph icon="shield_moon" title="Augments de prata" side="Rodada 2" />
              <StateBlock
                compact
                loading={build.loading}
                loadingLabel="Carregando agregado de build…"
                error={build.error}
                errorLabel="Não foi possível carregar os augments de prata."
                onRetry={build.retry}
                empty={!build.loading && !build.error && !hasBuild}
                emptyLabel="Sem agregado de build neste patch."
              >
                {build.data && (
                  <AugGrid entries={build.data.augments.silver.slice(0, 8)} rarity="silver" cols={4} />
                )}
              </StateBlock>
            </div>

            {/* Segunda faixa: itens ocupam a largura dos dois primeiros
                augments; as botas fecham a coluna sob os prateados. */}
            <div className="cmp-panel cmp-card cmp-itemsbox">
              <Ph
                icon="diamond"
                title="Itens prismáticos"
                side={build.data?.patch ? `Patch ${build.data.patch}` : undefined}
              />
              <StateBlock
                compact
                loading={build.loading}
                loadingLabel="Carregando itens prismáticos…"
                error={build.error}
                errorLabel="Não foi possível carregar os itens prismáticos."
                onRetry={build.retry}
                empty={!build.loading && !build.error && !prismaticItems.length}
                emptyLabel="Sem itens prismáticos com amostra suficiente neste patch."
              >
                {prismaticItems.length > 0 && (
                  <div className="cmp-bcells">
                    {prismaticItems.map((it, i) => (
                      <ItemCell key={it.id} e={it} top={i === 0} />
                    ))}
                  </div>
                )}
              </StateBlock>
            </div>

            <div className="cmp-panel cmp-card">
              <Ph icon="footprint" title="Botas" />
              <StateBlock
                compact
                loading={build.loading}
                loadingLabel="Carregando botas…"
                error={build.error}
                errorLabel="Não foi possível carregar as botas."
                onRetry={build.retry}
                empty={!build.loading && !build.error && !(build.data?.boots.length ?? 0)}
                emptyLabel="Sem botas com amostra suficiente."
              >
                {build.data && build.data.boots.length > 0 && (
                  <div className="cmp-boots">
                    {build.data.boots.slice(0, 6).map((b, i) => (
                      <ItemCell key={b.id} e={b} top={i === 0} />
                    ))}
                  </div>
                )}
              </StateBlock>
            </div>
          </section>

          {/* ═══ BUILDS (variantes) + RAIL ═══ */}
          <div className="cmp-dash">
            <section className="cmp-panel cmp-card cmp-builds">
              <Ph
                icon="construction"
                title={`Builds de ${name}`}
                side={variants.data?.variants.length ? `${variants.data.variants.length} variantes` : "por tier"}
              />
              {variants.loading ? (
                <>
                  <BuildVariantsSkeleton />
                  <p className="cmp-note" role="status" aria-live="polite">
                    <Mi name="pending" />
                    Carregando variantes de build…
                  </p>
                </>
              ) : (
                <StateBlock
                  compact
                  error={variants.error}
                  errorLabel="Não foi possível carregar as variantes de build."
                  onRetry={variants.retry}
                  empty={!variants.error && !variants.data?.variants.length}
                  emptyLabel="Agregado de variantes em preparação no backend — nenhuma estimativa é exibida até o dado existir."
                >
                  {variants.data?.variants.length && (
                    <>
                      <div className="cmp-bvars">
                        {variants.data.variants.map((v, i) => (
                          <BuildVariantRow key={v.id} v={v} rank={i + 1} />
                        ))}
                      </div>
                      <p className="cmp-note">
                        <Mi name="bolt" />
                        Cada variante lista os augments sem os quais a itemização não fecha — no Arena eles são
                        pré-requisito, não bônus.
                      </p>
                    </>
                  )}
                </StateBlock>
              )}
            </section>

            <aside className="cmp-side">
              <div className="cmp-panel cmp-card">
                <Ph icon="leaderboard" title={`OTPs de ${name}`} side="Ladder BR" />
                <StateBlock
                  loading={mains.loading}
                  error={mains.error}
                  onRetry={mains.retry}
                  empty={!mains.data?.players.length}
                >
                  <div className="cmp-otp">
                    <div className="cmp-otp-head">
                      <span>#</span>
                      <span>Jogador</span>
                      <span className="r">WR</span>
                      <span className="r">Jogos</span>
                    </div>
                    {mains.data?.players.map((p, i) => (
                      <OtpRow key={`${p.name}${p.handle}`} p={p} pos={i + 1} />
                    ))}
                  </div>
                </StateBlock>
                <Link to={`/campeao/${id}/otps`} className="cmp-fullbtn">
                  <Mi name="format_list_bulleted" />
                  Leaderboard completo
                </Link>
              </div>

              {hasTrend && (
                <div className="cmp-panel cmp-card cmp-wtime">
                  <Ph icon="timeline" title="Volume diário" side="partidas" />
                  <BarChart
                    values={series.map((p) => p.games)}
                    dates={series.map((p) => p.date)}
                    color="#9b5cff"
                    format={(v) => nf(Math.round(v))}
                    domain={[
                      0,
                      Math.max(...series.map((point) => point.games)),
                    ]}
                    daily
                  />
                </div>
              )}

              <div className="cmp-panel cmp-card cmp-stats">
                <Ph icon="bar_chart" title={`${name} · Números`} />
                {row ? (
                  <>
                    <div className="cmp-srow">
                      <span className="k">Colocação média</span>
                      <span className="v tnum">{fmtPlace(row.avgPlace)}</span>
                    </div>
                    <div className="cmp-srow">
                      <span className="k">Winrate (top 4)</span>
                      <span className="v green tnum">{pct1(row.top4)}</span>
                    </div>
                    <div className="cmp-srow">
                      <span className="k">Taxa de 1º lugar</span>
                      <span className="v green tnum">{pct1(row.first)}</span>
                    </div>
                    <div className="cmp-sdiv" />
                    <div className="cmp-srow">
                      <span className="k">Taxa de escolha</span>
                      <span className="v tnum">{pct1(row.pickRate)}</span>
                    </div>
                    <div className="cmp-srow">
                      <span className="k">Partidas amostradas</span>
                      <span className="v tnum">{nf(row.games)}</span>
                    </div>
                    <div className="cmp-srow">
                      <span className="k">Posição na tierlist</span>
                      <span className="v tnum">#{row.rank}</span>
                    </div>
                    <div className="cmp-srow">
                      <span className="k">Variação de winrate (7d)</span>
                      <span
                        className={`v tnum${row.winrateDelta > 0 ? " green" : row.winrateDelta < 0 ? " red" : ""}`}
                      >
                        {row.winrateDelta === 0 ? "—" : fmtDelta(row.winrateDelta)}
                      </span>
                    </div>
                    {hasBuild && (
                      <>
                        <div className="cmp-sdiv" />
                        <div className="cmp-srow">
                          <span className="k">Amostra do agregado de build</span>
                          <span className="v tnum">{nf(build.data!.games)}</span>
                        </div>
                        <div className="cmp-srow">
                          <span className="k">Piso por entrada</span>
                          <span className="v tnum">{nf(build.data!.minGames)}</span>
                        </div>
                      </>
                    )}
                  </>
                ) : (
                  <p className="cmp-empty">Campeão sem linha na tierlist da temporada.</p>
                )}
              </div>
            </aside>
          </div>

          <p className="cmp-foot">
            <Mi name="info" />
            Winrate = taxa de top 4 (metade superior do lobby). Augments, itens, botas e duplas vêm do agregado
            global do patch{build.data?.patch ? ` ${build.data.patch}` : ""}; ranking, tendência e OTPs vêm da
            ladder BR.
          </p>
        </StateBlock>
      </main>
    </div>
  );
}
