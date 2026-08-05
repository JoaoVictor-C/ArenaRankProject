import "./Perfil.css";
import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import {
  PlayerAvatar,
  ChampIcon,
  TierBadge,
  Placement,
  Delta,
  Mi,
  StateBlock,
  PlayerTagChip,
  FreshnessBadge,
  ProfileSurfaceNav,
  BuildHoverIcon,
  type BuildHoverData,
} from "../components";
import { avatarColorVars } from "../components/Avatar";
import { useApi } from "../hooks/useApi";
import { nf, signed, pct, deltaClass, timeAgo, fmtCountdown } from "../lib/format";
import {
  STATE_SPINNER_LOOP,
  useDrawCharts,
  useGsapEntrance,
  useGsapInteractions,
  useGsapLoop,
  useGsapMatchDetail,
  type EntranceStep,
  type InteractionMotion,
  type LoopMotion,
} from "../lib/motion";
import type {
  PlayerProfile,
  FormDot,
  CrHistoryPoint,
  PlayerMatchRich,
  PlayerMatchesResponse,
  ChampStat,
  H2HRow,
  SeasonArchive,
} from "../lib/types";
import {
  loadProfileMatchDetail,
  loadProfileMatchSummary,
  type ProfileAugmentEntry,
  type ProfileLoadoutEntry,
  type ProfileMatchDetail,
  type ProfileMatchPlayer,
  type ProfileMatchSummary,
} from "./profileMatchDetail";
import { resolveChartDomain } from "./championChartGeometry";
import { useGsapNameMarkers, useGsapProfilePdl } from "./profileIdentityMotion";
import { ProfileRatingSignals } from "./profileRatingSignals";
import { useScrollFocusBand } from "./scrollFocusBand";
import {
  isTelemetryLabProfile,
  loadPlayerMatchesForRoute,
  loadProfileForRoute,
  loadTelemetryLabMatch,
  loadTelemetryLabSummary,
} from "./profileTelemetryLab";

const PROFILE_ENTRANCE_STEPS: EntranceStep[] = [
  {
    selector: ".pf-banner",
    from: { opacity: 0, clipPath: "inset(0% 0% 100% 0%)" },
    duration: 0.7,
  },
  {
    selector: ".pfb-name-cube",
    from: { scaleX: 0, transformOrigin: "0% 50%" },
    duration: 1,
    ease: "power3.out",
    position: 0.2,
  },
  {
    selector: ".pf-form",
    from: { opacity: 0, y: 10 },
    position: 0.18,
  },
  {
    selector: ".pf-main-col",
    from: { opacity: 0, y: 16 },
    position: 0.24,
  },
  {
    selector: ".pf-side > .card",
    from: { opacity: 0, y: 12 },
    stagger: 0.05,
    position: 0.3,
  },
];

const PROFILE_INTERACTIONS: InteractionMotion[] = [
  {
    trigger: ".pfb-share",
    target: ".mi",
    to: { rotation: -8, scale: 1.08 },
  },
  {
    trigger: ".hist-row-main",
    to: { x: 2 },
  },
  {
    trigger: ".cf-icon",
    to: { scale: 1.06 },
  },
];

/* Os marcadores do nick NÃO entram aqui: o percurso deles depende da largura
   medida do nome, então vivem em useGsapNameMarkers. */
const PROFILE_LOOPS: LoopMotion[] = [
  STATE_SPINNER_LOOP,
  {
    selector: ".hist-skel-row, .perf-cell.skel",
    to: { opacity: 0.45 },
    duration: 0.8,
    repeat: -1,
    yoyo: true,
    ease: "power1.inOut",
  },
];

/* ============================================================
   Helpers internos
   ============================================================ */
/** Cor de fundo do dot de forma recente — MESMO padrão dos badges/histograma
    (tokens --place-*): 1º ouro · 2–4 verde · 5+ vermelho. */
function placeColor(p: number): string {
  if (p === 1) return "var(--place-1)";
  if (p <= 4) return "var(--place-3)";
  return "var(--place-low)";
}
function placeFg(p: number): string {
  // Ouro/verde pedem tinta escura; o vermelho fundo (--place-low) pede branca.
  return p <= 4 ? "#0c0c0e" : "#fff";
}
/** Cor da barra do histograma por colocação (mesma escala dos badges). */
function histBarColor(i: number): string {
  if (i === 0) return "var(--place-1)";
  if (i === 1) return "var(--place-2)";
  if (i <= 3) return "var(--place-3)";
  return "var(--place-low)";
}
/** "18/07 21:34" — data curta pt-BR para a coluna de quando. */
function fmtShortDate(iso: string): string {
  const d = new Date(iso);
  return (
    d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) +
    " " +
    d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
  );
}

type MatchDay = {
  dateKey: string;
  label: string;
  matches: PlayerMatchRich[];
  crDelta: number;
};

function localDateKey(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function matchDayLabel(date: Date): string {
  const day = String(date.getDate()).padStart(2, "0");
  const month = date
    .toLocaleDateString("pt-BR", { month: "short" })
    .replace(".", "")
    .toUpperCase();
  return `${day} ${month}`;
}

function groupMatchesByDay(matches: PlayerMatchRich[]): MatchDay[] {
  const days: MatchDay[] = [];
  const indexByDate = new Map<string, number>();

  matches.forEach((match) => {
    const date = new Date(match.ts);
    const dateKey = localDateKey(date);
    const existingIndex = indexByDate.get(dateKey);

    if (existingIndex === undefined) {
      indexByDate.set(dateKey, days.length);
      days.push({
        dateKey,
        label: matchDayLabel(date),
        matches: [match],
        crDelta: match.crDelta,
      });
      return;
    }

    days[existingIndex].matches.push(match);
    days[existingIndex].crDelta += match.crDelta;
  });

  return days;
}

/* ============================================================
   Gráfico de evolução do PDL — SVG com eixos, escala e marcadores
   ============================================================ */

/** "22/07" — data curta para os ticks do eixo X. */
function fmtDay(iso: string): string {
  return new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

/** Largura real do container (ResizeObserver) — desenhamos o SVG em px 1:1
    (viewBox == pixels), sem `preserveAspectRatio="none"`, p/ não distorcer
    traço, marcador nem inclinação em nenhuma largura. */
function useMeasuredWidth<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      setWidth(entries[0]?.contentRect.width ?? 0);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

function CrTrend({ history }: { history: CrHistoryPoint[] }) {
  const [wrapRef, width] = useMeasuredWidth<HTMLDivElement>();
  const H = 132;
  const padL = 38;
  const padR = 16;
  const padT = 14;
  const padB = 20;

  const chart = useMemo(() => {
    if (width <= 0 || history.length < 2) return null;

    const vals = history.map((p) => p.cr);
    // Ancorado na média em vez de min-máx: uma temporada estável oscilando 15
    // PDL não deve desenhar o mesmo despenhadeiro de uma que oscilou 400.
    //
    // ATENÇÃO: minV/maxV são o DOMÍNIO DO EIXO, não valores da série — o teto
    // quase nunca coincide com um ponto real. Quem precisa do pico de verdade
    // (o marcador e o rótulo acessível) usa peakV.
    const { min: minV, max: maxV } = resolveChartDomain(vals);
    const peakV = Math.max(...vals);
    const span = maxV - minV || 1;
    const times = history.map((p) => new Date(p.ts).getTime());
    const tMin = times[0];
    const tMax = times[times.length - 1];
    const tSpan = tMax - tMin || 1;
    const useTime = tMax > tMin; // série com timestamps válidos → espaça por tempo real

    const plotW = width - padL - padR;
    const plotH = H - padT - padB;
    const baseY = H - padB;
    const n = history.length;
    const xAt = (i: number) =>
      useTime ? padL + ((times[i] - tMin) / tSpan) * plotW : padL + (plotW * i) / (n - 1);
    const Y = (v: number) => padT + (1 - (v - minV) / span) * plotH;

    const pts = history.map((p, i) => ({ x: xAt(i), y: Y(p.cr) }));
    const line = pts.map((p, i) => (i === 0 ? "M" : "L") + p.x.toFixed(1) + " " + p.y.toFixed(1)).join(" ");
    const area = `${line} L${pts[n - 1].x.toFixed(1)} ${baseY} L${pts[0].x.toFixed(1)} ${baseY} Z`;

    const yTicks = maxV === minV ? [maxV] : [maxV, (minV + maxV) / 2, minV];

    const xTicks: { label: string; anchor: "start" | "middle" | "end"; x: number }[] = [
      { label: fmtDay(history[0].ts), anchor: "start", x: padL },
    ];
    if (n >= 3 && plotW > 150) {
      const midT = tMin + tSpan / 2;
      let nearest = history[0];
      let best = Infinity;
      for (let i = 0; i < n; i++) {
        const d = Math.abs(times[i] - midT);
        if (d < best) { best = d; nearest = history[i]; }
      }
      xTicks.push({ label: fmtDay(nearest.ts), anchor: "middle", x: padL + plotW / 2 });
    }
    xTicks.push({ label: fmtDay(history[n - 1].ts), anchor: "end", x: width - padR });

    const lastIdx = n - 1;
    const peakIdx = vals.indexOf(peakV);
    return {
      maxV: peakV, line, area, yTicks, xTicks, Y,
      cur: pts[lastIdx], peak: pts[peakIdx], peakIdx, lastIdx,
      firstCr: history[0].cr, lastCr: history[lastIdx].cr, delta: history[lastIdx].cr - history[0].cr,
    };
  }, [history, width]);

  const ariaLabel = chart
    ? `Evolução do PDL em 30 dias: de ${nf(chart.firstCr)} a ${nf(chart.lastCr)} PDL, ${signed(chart.delta)} no período; pico ${nf(chart.maxV)}.`
    : "Evolução do PDL — 30 dias";

  return (
    <div className="trend-wrap" ref={wrapRef} style={{ height: H }}>
      {chart && (
        <svg
          className="trend-chart"
          width="100%"
          height={H}
          viewBox={`0 0 ${width} ${H}`}
          role="img"
          aria-label={ariaLabel}
        >
          <title>{ariaLabel}</title>
          <defs>
            <linearGradient id="crtrend-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--gold)" stopOpacity="0.16" />
              <stop offset="100%" stopColor="var(--gold)" stopOpacity="0" />
            </linearGradient>
          </defs>

          {/* Grade + rótulos do eixo Y (valores de PDL) */}
          {chart.yTicks.map((v, i) => {
            const y = chart.Y(v);
            return (
              <g key={`y${i}`}>
                <line className="trend-grid" x1={padL} y1={y.toFixed(1)} x2={width - padR} y2={y.toFixed(1)} />
                <text className="trend-ylabel" x={padL - 8} y={y.toFixed(1)} dominantBaseline="middle" textAnchor="end">
                  {nf(Math.round(v))}
                </text>
              </g>
            );
          })}

          {/* Rótulos do eixo X (datas) */}
          {chart.xTicks.map((t, i) => (
            <text key={`x${i}`} className="trend-xlabel" x={t.x} y={H - 6} textAnchor={t.anchor}>
              {t.label}
            </text>
          ))}

          {/* Área + linha do PDL */}
          <path data-chart-area d={chart.area} fill="url(#crtrend-fill)" />
          <path data-chart-line className="trend-line" d={chart.line} />

          {/* Pico (só quando não é o ponto atual) */}
          {chart.peakIdx !== chart.lastIdx && (
            <circle
              data-chart-mark
              className="trend-peak"
              cx={chart.peak.x}
              cy={chart.peak.y}
              r={3}
            />
          )}

          {/* Ponto atual + rótulo direto do valor */}
          <circle
            data-chart-mark
            className="trend-cur"
            cx={chart.cur.x}
            cy={chart.cur.y}
            r={4}
          />
          <text
            data-chart-mark
            className="trend-curlabel"
            x={chart.cur.x}
            y={Math.max(chart.cur.y - 9, padT + 4)}
            textAnchor="end"
          >
            {nf(chart.lastCr)}
          </text>
        </svg>
      )}
    </div>
  );
}

type ShareState = "idle" | "copied" | "shared" | "fallback";

function ShareProfileButton({ playerName }: { playerName: string }) {
  const [state, setState] = useState<ShareState>("idle");

  const shareProfile = useCallback(async () => {
    const url = window.location.href;

    try {
      if (typeof navigator.share === "function") {
        await navigator.share({
          title: `Perfil de ${playerName} no ArenaRank`,
          url,
        });
        setState("shared");
        return;
      }

      if (!navigator.clipboard?.writeText) throw new Error("clipboard indisponível");
      await navigator.clipboard.writeText(url);
      setState("copied");
    } catch (shareError) {
      if (shareError instanceof DOMException && shareError.name === "AbortError") return;
      setState("fallback");
    }
  }, [playerName]);

  const label =
    state === "copied"
      ? "Link copiado"
      : state === "shared"
        ? "Compartilhado"
        : state === "fallback"
          ? "Copie o endereço do navegador"
          : "Compartilhar";

  return (
    <button
      className="btn ghost pfb-share"
      type="button"
      aria-label="Compartilhar perfil"
      onClick={shareProfile}
    >
      <Mi name={state === "copied" || state === "shared" ? "check" : "ios_share"} />
      <span aria-live="polite">{label}</span>
    </button>
  );
}

/* ============================================================
   Banner de identidade + PDL — "Pôster do Gladiador"
   Splash do campeão mais jogado como capa cinematográfica (scrim escuro p/
   legibilidade) + identidade, tags e PDL de ouro sobrepostos.
   ============================================================ */

/** Splash centralizado no rosto (CommunityDragon) — fallback quando a splash
    ddragon oficial não resolve. Precisa só do championId numérico. */
function cdragonCentered(championId?: number | null): string | null {
  return championId
    ? `https://cdn.communitydragon.org/latest/champion/${championId}/splash-art/centered/skin/0`
    : null;
}

/** Camada de arte do banner: tenta a splash ddragon (oficial), degrada p/ o
    recorte centralizado do CommunityDragon e, se ambos falharem, some (banner
    tonal). Decorativa — o campeão já é nomeado no crédito e nas tags. */
function BannerArt({
  splashUrl,
  championId,
}: {
  splashUrl?: string | null;
  championId?: number | null;
}) {
  const sources = useMemo(
    () => [splashUrl, cdragonCentered(championId)].filter(Boolean) as string[],
    [splashUrl, championId]
  );
  const [i, setI] = useState(0);
  const src = sources[i];
  if (!src) return null;
  return (
    <img
      key={src}
      className="pfb-art"
      src={src}
      alt=""
      aria-hidden="true"
      decoding="async"
      onError={() => setI((n) => n + 1)}
    />
  );
}

function IdentityBanner({
  data,
  firstRate,
  cover,
  fictional,
}: {
  data: PlayerProfile;
  /** Taxa de 1º lugar (placement==1) do histórico completo — mesma fonte do card Desempenho.
      `null` enquanto o summary de partidas ainda não carregou. */
  firstRate: number | null;
  /** Campeão mais jogado — fonte da capa. `null` sem histórico de campeões. */
  cover: ChampStat | null;
  fictional: boolean;
}) {
  const total = data.wins + data.losses;
  const hasArt = Boolean(cover?.championSplashUrl || cover?.championId);

  return (
    <section className={`pf-banner${hasArt ? " has-art" : ""}`}>
      <BannerArt splashUrl={cover?.championSplashUrl} championId={cover?.championId} />
      <div className="pfb-scrim" aria-hidden="true" />

      <div className="pfb-inner">
        <div className="pfb-top">
          {/* Identidade */}
          <div className="pfb-id" style={avatarColorVars(data.avatar)}>
            <PlayerAvatar colors={data.avatar} url={data.profileIconUrl} alt={data.name} size={84} />
            <div className="pfb-idtxt">
              <div className="pfb-name-cube">
                <h1 className="pfb-name pfb-name-cube__plate">
                  <span data-profile-nick>{data.name}</span>
                  <span className="pfb-tag">{data.handle}</span>
                </h1>
                <span
                  className="pfb-name-cube__marker is-top"
                  aria-hidden="true"
                />
                <span
                  className="pfb-name-cube__marker is-bottom"
                  aria-hidden="true"
                />
              </div>
              <div className="pfb-meta">
                <span className="pfb-region">
                  <span className="flag-br" aria-hidden="true" />
                  {data.region.toUpperCase()}
                </span>
                <TierBadge tier={data.tier} />
                {data.provisional && <span className="badge provisional">Provisório</span>}
                {fictional && (
                  <span className="badge profile-mock-badge">
                    Perfil fictício · Dados mockados
                  </span>
                )}
                {data.tags.map((tag, i) => (
                  <PlayerTagChip key={i} tag={tag} />
                ))}
              </div>
            </div>
          </div>

          {/* PDL — âncora de ouro */}
          <div className="pfb-cr">
            <div
              className="pfb-cr-num tnum"
              data-profile-pdl
              aria-label={`${nf(data.cr)} PDL`}
              aria-live="off"
            >
              {nf(data.cr)}
            </div>
            <div className="pfb-cr-lbl">PDL · Pontos de Liga</div>
            <div className="pfb-cr-sub">
              <b className="tnum" style={{ color: "var(--primary-bright)" }}>#{nf(data.rank)}</b>
              <Delta value={data.delta7d} />
            </div>
          </div>
        </div>

        {/* Strip editorial de stats */}
        <div className="pfb-kvs">
          <div className="pfb-kv">
            <b className="tnum">{nf(total)}</b>
            <span>Partidas</span>
          </div>
          <div className="pfb-kv">
            <b className="tnum" style={{ color: "var(--primary-bright)" }}>
              {firstRate === null ? "—" : pct(firstRate)}
            </b>
            <span>1º lugar</span>
          </div>
          <div className="pfb-kv">
            <b className="tnum" style={{ color: "var(--green)" }}>{pct(data.top4)}</b>
            <span>Top metade</span>
          </div>
          <div className="pfb-kv">
            <b className="tnum">
              {data.avgPlace.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}
            </b>
            <span>Col. média</span>
          </div>
          {cover && (
            <div className="pfb-kv pfb-kv-champ">
              <b>{cover.name}</b>
              <span>Mais jogado · {nf(cover.games)}</span>
            </div>
          )}
        </div>

        {/* Ação secundária, ancorada no canto — fora da coluna de identidade
            para que o nick alinhe com o avatar. */}
        <div className="pfb-actions">
          <ShareProfileButton playerName={data.name} />
        </div>
      </div>
    </section>
  );
}

/* ============================================================
   Faixa de forma recente
   ============================================================ */
function FormStrip({ form }: { form: FormDot[] }) {
  return (
    <div className="pf-form panel">
      <span className="pf-form-lbl">Forma recente · últimas {form.length} colocações</span>
      <div className="form-row">
        {form.map((dot, i) => (
          <span
            key={i}
            className="form-dot"
            style={{ background: placeColor(dot.place), color: placeFg(dot.place) }}
          >
            {dot.place}
          </span>
        ))}
      </div>
    </div>
  );
}

/* ============================================================
   Sidebar — Card: PDL (30 dias)
   ============================================================ */
function TrendCard({ data }: { data: PlayerProfile }) {
  // Delta do período derivado da MESMA série do gráfico (último − primeiro),
  // p/ o número do header casar com a curva e com o rótulo "30 dias"
  // (data.delta7d é 7 dias — divergia do título).
  const h = data.crHistory;
  const windowDelta = h.length >= 2 ? h[h.length - 1].cr - h[0].cr : data.delta7d;
  return (
    <div className="panel card">
      <div className="card-h">
        <span>PDL — 30 dias</span>
        <Delta value={windowDelta} />
      </div>
      {data.crHistory.length >= 2 ? (
        <CrTrend history={data.crHistory} />
      ) : (
        <div className="card-empty">Sem histórico suficiente para o gráfico.</div>
      )}
    </div>
  );
}

/* ============================================================
   Coluna principal — Desempenho recente (reage ao filtro do histórico)
   ============================================================ */
function RecentPerformance({
  resp,
  loading,
  filtered,
}: {
  resp: PlayerMatchesResponse | null;
  loading: boolean;
  filtered: boolean;
}) {
  if (loading && !resp) {
    return (
      <section
        className="panel recent-performance"
        role="region"
        aria-label="Desempenho recente"
      >
        <div className="perf-head">
          <div>
            <span className="perf-kicker">Leitura da amostra atual</span>
            <h2>Desempenho recente</h2>
          </div>
        </div>
        <div className="perf-grid">
          {Array.from({ length: 4 }, (_, i) => (
            <div className="perf-cell skel" key={i} />
          ))}
        </div>
      </section>
    );
  }
  if (!resp) return null;

  const s = resp.summary;
  const places = s.placements;
  const barCount = places[6] > 0 || places[7] > 0 ? 8 : 6;
  const maxCount = Math.max(1, ...places);

  return (
    <section
      className="panel recent-performance"
      role="region"
      aria-label="Desempenho recente"
    >
      <div className="perf-head">
        <div>
          <span className="perf-kicker">
            {filtered ? "Filtros aplicados" : "Leitura da amostra atual"}
          </span>
          <h2>Desempenho recente</h2>
        </div>
        <span className="perf-sample tnum">
          {nf(s.games)} {s.games === 1 ? "partida" : "partidas"}
        </span>
      </div>

      <div className="perf-layout">
        <div className="perf-grid">
          <div className="perf-cell">
            <b className="tnum" style={{ color: "var(--primary-bright)" }}>
              {pct(s.firstRate)}
            </b>
            <span>1º lugar</span>
          </div>
          <div className="perf-cell">
            <b className="tnum" style={{ color: "var(--green)" }}>{pct(s.top4)}</b>
            <span>Top metade</span>
          </div>
          <div className="perf-cell">
            <b className="tnum">
              {s.avgPlace.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}
            </b>
            <span>Col. média</span>
          </div>
          <div className="perf-cell">
            <b className={`tnum delta ${deltaClass(s.crSum)}`}>{signed(s.crSum)}</b>
            <span>Δ PDL</span>
          </div>
        </div>

        <div className="perf-dist" role="img" aria-label="Distribuição de colocações">
          {places.slice(0, barCount).map((count, i) => (
            <div className="pd-col" key={i} title={`${i + 1}º lugar — ${count}×`}>
              <div className="pd-bar-wrap">
                <div
                  className="pd-bar"
                  style={{
                    height: `${Math.round((count / maxCount) * 100)}%`,
                    background: histBarColor(i),
                  }}
                />
              </div>
              <span className="pd-x">{i + 1}º</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ============================================================
   Sidebar — Card: Campeões (informativo, ordenável, expansível)
   ============================================================ */
type ChampSort = "games" | "firstRate" | "crImpact";
const CHAMP_SORTS: [ChampSort, string][] = [
  ["games", "Jogos"],
  ["firstRate", "1º%"],
  ["crImpact", "Δ PDL"],
];

function ChampionsCard({ champions }: { champions: ChampStat[] }) {
  const [sort, setSort] = useState<ChampSort>("games");
  const [expanded, setExpanded] = useState(false);

  const sorted = useMemo(
    () => [...champions].sort((a, b) => b[sort] - a[sort]),
    [champions, sort]
  );
  if (champions.length === 0) return null;
  const shown = expanded ? sorted : sorted.slice(0, 5);

  return (
    <div className="panel card" id="campeoes">
      <div className="card-h">
        <span>Campeões</span>
        <div className="mini-tabs" role="group" aria-label="Ordenar campeões">
          {CHAMP_SORTS.map(([k, label]) => (
            <button
              key={k}
              type="button"
              className="mt-btn"
              data-active={sort === k}
              onClick={() => setSort(k)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="champ-list">
        {shown.map((ch) => (
          <div key={ch.name} className="champ-row">
            <ChampIcon colors={ch.champion} url={ch.championIconUrl} alt={ch.name} size="sm" />
            <div className="champ-mid">
              <div className="champ-nm">
                <b>{ch.name}</b>
                <span className="champ-g tnum">{ch.games} jogos</span>
              </div>
              <div className="champ-bar">
                <i style={{ width: `${Math.min(100, ch.top4)}%` }} />
              </div>
            </div>
            <div className="champ-right">
              <div className="champ-wr tnum">{pct(ch.firstRate)}</div>
              <div className={`champ-imp tnum delta ${deltaClass(ch.crImpact)}`}>
                {signed(ch.crImpact)}
              </div>
            </div>
          </div>
        ))}
      </div>

      {champions.length > 5 && (
        <button className="card-more" type="button" onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Ver menos" : `Ver todos (${champions.length})`}
        </button>
      )}
    </div>
  );
}

/* ============================================================
   Sidebar — Card: Duplas & rivais
   ============================================================ */
function DuosCard({ h2h }: { h2h: H2HRow[] }) {
  // Ignora pares sem partidas registradas — evita "0% · 0 jogos" no card.
  const duos = useMemo(() => h2h.filter((r) => r.synergy === "duo" && r.games > 0), [h2h]);
  const rivals = useMemo(() => h2h.filter((r) => r.synergy === "rival" && r.games > 0), [h2h]);
  const [tab, setTab] = useState<"duo" | "rival">(duos.length > 0 ? "duo" : "rival");
  if (h2h.length === 0) return null;

  const rows = (tab === "duo" ? duos : rivals).slice(0, 6);

  return (
    <div className="panel card">
      <div className="card-h">
        <span>Duplas &amp; rivais</span>
        <div className="mini-tabs" role="group" aria-label="Alternar duplas ou rivais">
          <button type="button" className="mt-btn" data-active={tab === "duo"} onClick={() => setTab("duo")}>
            Duplas {duos.length > 0 && <i className="mt-n">{duos.length}</i>}
          </button>
          <button type="button" className="mt-btn" data-active={tab === "rival"} onClick={() => setTab("rival")}>
            Rivais {rivals.length > 0 && <i className="mt-n">{rivals.length}</i>}
          </button>
        </div>
      </div>

      {rows.length > 0 ? (
        <div className="duo-list">
          {rows.map((r) => (
            <div key={r.player.name + r.player.handle} className="duo-row">
              <PlayerAvatar colors={r.player.avatar} size={30} />
              <div className="duo-mid">
                <div className="duo-nm">{r.player.name}</div>
                <div className="duo-tag">{r.player.handle}</div>
              </div>
              <div className="duo-right">
                <b className="tnum" style={{ color: "var(--green)" }}>{pct(r.winrate)}</b>
                <span className="tnum">{r.games} jogos</span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="card-empty">
          {tab === "duo" ? "Nenhuma dupla frequente registrada." : "Nenhum rival direto registrado."}
        </div>
      )}
    </div>
  );
}

/* ============================================================
   Sidebar — Card: Temporadas arquivadas
   ============================================================ */
function SeasonsCard({ seasons }: { seasons: SeasonArchive[] }) {
  if (seasons.length === 0) return null;
  return (
    <div className="panel card">
      <div className="card-h"><span>Temporadas</span></div>
      <div className="season-list">
        {seasons.map((s) => (
          <div key={s.season} className="season-row">
            <div className="sr-head">
              <span className="sr-name">Temporada {s.season}</span>
              <TierBadge tier={s.tier} />
            </div>
            <div className="sr-stats">
              <div>
                <b className="tnum" style={{ color: "var(--gold)" }}>{nf(s.peakCr)}</b>
                <span>PDL final</span>
              </div>
              <div>
                <b className="tnum" style={{ color: "var(--primary-bright)" }}>#{nf(s.finalRank)}</b>
                <span>Rank</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ============================================================
   Histórico — linha de partida (expansível)
   ============================================================ */
function compactTelemetry(value: number): string {
  if (Math.abs(value) < 1000) return nf(value);
  return `${(value / 1000).toLocaleString("pt-BR", {
    maximumFractionDigits: 1,
  })} mil`;
}

function playerKda(player: ProfileMatchPlayer | ProfileMatchSummary): number | null {
  if (
    player.kills === undefined ||
    player.deaths === undefined ||
    player.assists === undefined
  ) {
    return null;
  }
  return (player.kills + player.assists) / Math.max(1, player.deaths);
}

function hasCombatTelemetry(
  player: ProfileMatchPlayer | ProfileMatchSummary | null,
): player is ProfileMatchPlayer | ProfileMatchSummary {
  return !!player &&
    player.kills !== undefined &&
    player.deaths !== undefined &&
    player.assists !== undefined;
}

const LOADOUT_RARITY_LABEL: Record<string, string> = {
  prismatic: "Prismático",
  gold: "Ouro",
  silver: "Prata",
};

function LoadoutIcon({
  entry,
  augment,
}: {
  entry: ProfileLoadoutEntry | ProfileAugmentEntry;
  augment?: boolean;
}) {
  const rarity =
    augment && "rarity" in entry ? entry.rarity : undefined;
  const hoverData: BuildHoverData = {
    name: entry.name,
    iconUrl: entry.iconUrl,
    badge: rarity ? LOADOUT_RARITY_LABEL[rarity] : undefined,
    badgeClassName: rarity ? `rarity-${rarity}` : undefined,
    description: entry.description,
    // Só itens têm custo de compra — augments são escolha de draft, sem preço.
    stats: entry.gold ? [{ label: "Custo", value: `${nf(entry.gold)} de ouro` }] : undefined,
  };

  return (
    <BuildHoverIcon
      data={hoverData}
      className={`match-loadout-icon${augment ? " is-augment" : ""}`}
      data-rarity={rarity}
      data-match-item={augment ? undefined : ""}
      data-match-augment={augment ? "" : undefined}
    >
      {entry.iconUrl ? (
        <img src={entry.iconUrl} alt={entry.name} loading="lazy" decoding="async" />
      ) : (
        <span className="match-loadout-fallback" aria-label={entry.name}>
          {augment ? "A" : "I"}
        </span>
      )}
    </BuildHoverIcon>
  );
}

function MatchLoadout({
  items,
  augments,
  mocked = false,
  compact = false,
}: {
  items?: ProfileLoadoutEntry[];
  augments?: ProfileAugmentEntry[];
  mocked?: boolean;
  compact?: boolean;
}) {
  return (
    <span className={`match-loadout${compact ? " is-compact" : ""}`}>
      <span className="match-loadout-group">
        <span className="match-loadout-label">Itens</span>
        {items?.length ? (
          <span className="match-loadout-slots" aria-label="Itens da partida">
            {items.slice(0, 7).map((item, index) => (
              <LoadoutIcon entry={item} key={`${item.id}-${index}`} />
            ))}
          </span>
        ) : (
          <span className="match-ingestion">Itens aguardando ingestão</span>
        )}
      </span>
      <span className="match-loadout-group">
        <span className="match-loadout-label">Augments</span>
        {augments?.length ? (
          <span className="match-loadout-slots" aria-label="Augments da partida">
            {augments.slice(0, 6).map((augment, index) => (
              <LoadoutIcon
                augment
                entry={augment}
                key={`${augment.id}-${index}`}
              />
            ))}
          </span>
        ) : (
          <span className="match-ingestion">Augments aguardando ingestão</span>
        )}
      </span>
      {mocked && <span className="match-mock-flag">Dados mockados</span>}
    </span>
  );
}

function MatchPlayerTelemetry({
  player,
}: {
  player: ProfileMatchPlayer | ProfileMatchSummary | null;
}) {
  if (!hasCombatTelemetry(player)) {
    return <span className="match-ingestion">Estatísticas aguardando ingestão</span>;
  }

  const kda = playerKda(player);
  return (
    <span className="match-telemetry">
      <b className="tnum">
        {player.kills}/{player.deaths}/{player.assists}
      </b>
      <span className="tnum">{kda?.toLocaleString("pt-BR", {
        maximumFractionDigits: 1,
      })} KDA</span>
      {player.killParticipation !== undefined && (
        <span className="tnum">{nf(player.killParticipation)}% part.</span>
      )}
      {player.damagePerMinute !== undefined && (
        <span className="tnum">{nf(player.damagePerMinute)} dano/min</span>
      )}
    </span>
  );
}

function teamTotal(
  players: ProfileMatchPlayer[],
  key: "kills" | "deaths" | "assists" | "damageToChampions",
): number | null {
  if (players.some((player) => player[key] === undefined)) return null;
  return players.reduce((sum, player) => sum + (player[key] ?? 0), 0);
}

function MatchScoreboard({
  detail,
  profileRiotId,
}: {
  detail: ProfileMatchDetail;
  profileRiotId: string;
}) {
  const normalizedProfileId = profileRiotId.toLocaleLowerCase();
  const teams = [...detail.subteams].sort((a, b) => a.placement - b.placement);
  const mocked = detail.mockedFields.length > 0;

  return (
    <div className="match-lab">
      <div className="match-lab-head">
        <div>
          <span className="match-lab-kicker">Telemetria completa</span>
          <h3 data-match-title>Raio-X da partida</h3>
        </div>
        <div className="match-lab-meta">
          <span>{detail.queueLabel || `Arena ${detail.format}`}</span>
          <span className="tnum">{fmtCountdown(detail.durationSec)}</span>
          <span className="tnum">{teams.length} times</span>
          {mocked && <span className="match-mock-flag">Combate e loadout mockados</span>}
        </div>
      </div>

      <div className="match-team-list">
        {teams.map((team) => {
          const ownTeam = team.players.some(
            (player) => player.riotId.toLocaleLowerCase() === normalizedProfileId,
          );
          const kills = teamTotal(team.players, "kills");
          const deaths = teamTotal(team.players, "deaths");
          const assists = teamTotal(team.players, "assists");
          const damage = teamTotal(team.players, "damageToChampions");

          return (
            <section
              className={`match-team${ownTeam ? " is-profile-team" : ""}`}
              data-match-team
              key={`${team.placement}-${team.players.map((player) => player.riotId).join("-")}`}
              aria-label={`${team.placement}º lugar`}
            >
              <header className="match-team-head">
                <span className="match-team-place">
                  <b className="tnum">{team.placement}º</b>
                  <small>{ownTeam ? "Seu time" : "Time adversário"}</small>
                </span>
                {kills !== null && deaths !== null && assists !== null ? (
                  <span className="match-team-total tnum">
                    {kills}/{deaths}/{assists}
                  </span>
                ) : (
                  <span className="match-ingestion">Totais aguardando ingestão</span>
                )}
                {damage !== null && (
                  <span className="match-team-damage tnum">
                    {compactTelemetry(damage)} dano
                  </span>
                )}
              </header>

              <div className="match-player-list">
                {team.players.map((player) => {
                  const isProfile =
                    player.riotId.toLocaleLowerCase() === normalizedProfileId;
                  return (
                    <article
                      className={`match-player${isProfile ? " is-profile" : ""}`}
                      data-match-player
                      key={player.riotId}
                    >
                      <div className="match-player-id">
                        <ChampIcon
                          colors={player.champion}
                          url={player.championIconUrl}
                          alt={player.championName}
                          size="lg"
                        />
                        <span>
                          <b title={player.riotId}>{player.riotId}</b>
                          <small>
                            {player.championName}
                            {player.level !== undefined && <> · Nv. {player.level}</>}
                          </small>
                          <small>{player.rankLabel ?? `${nf(player.crAfter)} PDL`}</small>
                        </span>
                      </div>

                      <MatchPlayerTelemetry player={player} />

                      <div className="match-player-damage">
                        {player.damageToChampions !== undefined ? (
                          <>
                            <b className="tnum">
                              {compactTelemetry(player.damageToChampions)}
                            </b>
                            <span>Dano a campeões</span>
                            {player.damagePerMinute !== undefined && (
                              <small className="tnum">
                                {nf(player.damagePerMinute)}/min
                              </small>
                            )}
                          </>
                        ) : (
                          <span className="match-ingestion">
                            Dano aguardando ingestão
                          </span>
                        )}
                      </div>

                      <MatchLoadout
                        items={player.items}
                        augments={player.augments}
                        mocked={mocked}
                        compact
                      />
                    </article>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}

function HistRow({
  match,
  profileRiotId,
}: {
  match: PlayerMatchRich;
  profileRiotId: string;
}) {
  const rowRef = useRef<HTMLElement>(null);
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<ProfileMatchDetail | null>(null);
  const [summary, setSummary] = useState<ProfileMatchSummary | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<Error | null>(null);
  const requestActive = useRef(false);
  const detailId = `match-detail-${match.matchId.replace(/[^a-zA-Z0-9_-]/g, "-")}`;

  useEffect(() => {
    let alive = true;
    void loadTelemetryLabSummary(match.matchId)
      .then((telemetrySummary) =>
        telemetrySummary ?? loadProfileMatchSummary(match),
      )
      .then((nextSummary) => {
        if (alive) setSummary(nextSummary);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [match]);

  const loadDetail = useCallback(() => {
    if (detail || requestActive.current) return;
    requestActive.current = true;
    setDetailLoading(true);
    setDetailError(null);
    void loadTelemetryLabMatch(match.matchId)
      .then((telemetryDetail) =>
        telemetryDetail ??
        loadProfileMatchDetail(match.matchId, profileRiotId),
      )
      .then((nextDetail) => setDetail(nextDetail))
      .catch((nextError: unknown) => {
        requestActive.current = false;
        setDetailError(
          nextError instanceof Error
            ? nextError
            : new Error("Não foi possível carregar a partida."),
        );
      })
      .finally(() => setDetailLoading(false));
  }, [detail, match.matchId, profileRiotId]);

  const toggleDetail = useCallback(() => {
    setOpen((current) => {
      const next = !current;
      if (next) loadDetail();
      return next;
    });
  }, [loadDetail]);

  useGsapMatchDetail(rowRef, open, detail !== null);

  const detailProfile = detail?.subteams
    .flatMap((team) => team.players)
    .find(
      (player) =>
        player.riotId.toLocaleLowerCase() === profileRiotId.toLocaleLowerCase(),
    );
  const closedTelemetry = detailProfile ?? summary;
  const closedMocked =
    (detail?.mockedFields.length ?? 0) > 0 || summary?.mocked === true;

  // Cor por RESULTADO de PDL, não por colocação (um 4º pode ganhar ou perder
  // pontos): 1º sempre ouro; senão ganhou=verde, perdeu=vermelho, zerado=cinza.
  // Casa com a cor do delta de PDL exibido na própria linha (.hr-cr).
  const tone =
    match.place === 1
      ? "first"
      : match.crDelta > 0
        ? "win"
        : match.crDelta < 0
          ? "loss"
          : "flat";

  return (
    <article
      className={`hist-row ${tone}`}
      data-open={open ? "true" : "false"}
      ref={rowRef}
    >
      <button
        type="button"
        className="hist-row-main"
        onClick={toggleDetail}
        aria-expanded={open}
        aria-controls={detailId}
      >
        <span className="hr-place">
          <Placement place={match.place} />
          <span className="of">de {match.teamCount}</span>
        </span>

        <span className="hr-champ">
          <ChampIcon
            colors={match.champion}
            url={match.championIconUrl ?? undefined}
            alt={match.championName}
            size="lg"
          />
          <span className="hr-champ-txt">
            <b>{match.championName}</b>
            <small>
              Arena {match.format}
              {match.durationSec > 0 && <> · {fmtCountdown(match.durationSec)}</>}
              {match.premade && <> · premade</>}
            </small>
          </span>
        </span>

        <span className="hr-combat">
          <MatchPlayerTelemetry player={closedTelemetry} />
        </span>

        <span className="hr-cr">
          <b className={`delta ${deltaClass(match.crDelta)} tnum`}>{signed(match.crDelta)} PDL</b>
          <small className="tnum">
            {nf(match.crBefore)} → {nf(match.crAfter)}
          </small>
        </span>

        <span className="hr-when">
          <b>{timeAgo(match.ts)}</b>
          <small>{fmtShortDate(match.ts)}</small>
        </span>

        <span className="hr-caret">
          <Mi name="expand_more" />
        </span>

        <span className="hr-kit">
          <MatchLoadout
            items={closedTelemetry?.items}
            augments={closedTelemetry?.augments}
            mocked={closedMocked}
            compact
          />
        </span>
      </button>

      <div
        className="hist-detail"
        id={detailId}
        aria-live="polite"
        {...(open ? {} : { inert: "" })}
      >
        <div className="hist-detail-inner">
          {detailLoading && !detail && (
            <div className="match-detail-state">
              <span className="state-spinner" aria-hidden="true" />
              <b>Carregando placar e adversários…</b>
            </div>
          )}
          {detailError && !detail && (
            <div className="match-detail-state is-error">
              <Mi name="sync_problem" />
              <div>
                <b>O detalhe desta partida não carregou.</b>
                <span>{detailError.message}</span>
              </div>
              <button className="btn ghost" type="button" onClick={loadDetail}>
                Tentar novamente
              </button>
            </div>
          )}
          {detail && (
            <MatchScoreboard detail={detail} profileRiotId={profileRiotId} />
          )}

          {open && (
            <ProfileRatingSignals
              modifiers={match.modifiers}
              placement={match.place}
              premade={match.premade}
              crDelta={match.crDelta}
              matchId={match.matchId}
              riotId={profileRiotId}
            />
          )}

          <div className="mod-foot">
            <span>O detalhe completo permanece disponível em sua própria rota.</span>
            <Link className="btn ghost" to={`/partida/${match.matchId}`}>
              Ver partida completa →
            </Link>
          </div>
        </div>
      </div>
    </article>
  );
}

/* ============================================================
   Histórico — fetch paginado (state levantado p/ a sidebar consumir summary)
   ============================================================ */
const HIST_PAGE = 20;
type ResultFilter = "" | "first" | "top" | "bottom";

const RESULT_CHIPS: { key: ResultFilter; label: string }[] = [
  { key: "", label: "Tudo" },
  { key: "first", label: "1º lugar" },
  { key: "top", label: "Top metade" },
  { key: "bottom", label: "Metade de baixo" },
];

function usePlayerMatches(riotId: string) {
  const [result, setResult] = useState<ResultFilter>("");
  const [champion, setChampion] = useState<number | null>(null);
  const [items, setItems] = useState<PlayerMatchRich[]>([]);
  const [resp, setResp] = useState<PlayerMatchesResponse | null>(null);
  /** Taxa de 1º lugar do histórico COMPLETO (sem filtro) — congela o valor do banner
      para não oscilar quando o usuário filtra o histórico. */
  const [lifetimeFirstRate, setLifetimeFirstRate] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!riotId) return;
    let alive = true;
    setLoading(true);
    setError(null);
    loadPlayerMatchesForRoute(riotId, {
        limit: HIST_PAGE,
        offset: 0,
        result: result || undefined,
        champion: champion ?? undefined,
      })
      .then((r) => {
        if (!alive) return;
        setResp(r);
        setItems(r.matches);
        // Só o conjunto sem filtro representa o lifetime do jogador.
        if (result === "" && champion === null) setLifetimeFirstRate(r.summary.firstRate);
      })
      .catch((e: Error) => alive && setError(e))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [riotId, result, champion]);

  const loadMore = useCallback(() => {
    setLoadingMore(true);
    loadPlayerMatchesForRoute(riotId, {
        limit: HIST_PAGE,
        offset: items.length,
        result: result || undefined,
        champion: champion ?? undefined,
      })
      .then((r) => {
        setResp(r);
        setItems((prev) => [...prev, ...r.matches]);
      })
      .catch(() => undefined) /* falha silenciosa: o botão continua disponível */
      .finally(() => setLoadingMore(false));
  }, [riotId, items.length, result, champion]);

  const total = resp?.total ?? 0;
  const hasMore = resp !== null && items.length < total;

  return {
    result,
    setResult,
    champion,
    setChampion,
    items,
    resp,
    lifetimeFirstRate,
    loading,
    loadingMore,
    error,
    loadMore,
    total,
    hasMore,
  };
}

type MatchesState = ReturnType<typeof usePlayerMatches>;

/* ============================================================
   Histórico — coluna principal (a estrela)
   ============================================================ */
function MatchHistory({
  m,
  profileRiotId,
}: {
  m: MatchesState;
  profileRiotId: string;
}) {
  const {
    result,
    setResult,
    champion,
    setChampion,
    items,
    resp,
    loading,
    loadingMore,
    error,
    loadMore,
    total,
    hasMore,
  } = m;

  const hasFilter = result !== "" || champion !== null;
  const facet = resp?.championsFacet ?? [];
  const days = useMemo(() => groupMatchesByDay(items), [items]);

  const clearFilters = useCallback(() => {
    setResult("");
    setChampion(null);
  }, [setResult, setChampion]);

  return (
    <section
      id="partidas"
      className="hist-main"
      role="region"
      aria-label="Histórico de partidas"
    >
      <div className="hist-head">
        <h2 className="hist-title">Histórico de partidas</h2>
        <span className="hist-count tnum">
          {loading ? "…" : `${nf(items.length)} de ${nf(total)}`}
        </span>
      </div>

      {/* Filtros */}
      <div className="hist-filterbar">
        <div className="hfb-top">
          <div className="chips" role="group" aria-label="Filtrar por resultado">
            {RESULT_CHIPS.map((chip) => (
              <button
                key={chip.key}
                type="button"
                className="chip"
                data-active={result === chip.key ? "true" : "false"}
                onClick={() => setResult(chip.key)}
              >
                {chip.label}
              </button>
            ))}
          </div>
          {hasFilter && (
            <button type="button" className="hfb-clear" onClick={clearFilters}>
              <Mi name="filter_alt_off" /> Limpar
            </button>
          )}
        </div>

        {facet.length > 0 && (
          <div className="champ-filter" role="group" aria-label="Filtrar por campeão">
            {facet.slice(0, 14).map((f) => {
              const active = champion === f.championId;
              return (
                <button
                  key={f.championId}
                  type="button"
                  className="cf-icon"
                  data-active={active ? "true" : "false"}
                  aria-pressed={active}
                  title={`${f.name} — ${f.games} jogos`}
                  onClick={() => setChampion(active ? null : f.championId)}
                >
                  <ChampIcon
                    colors={f.champion}
                    url={f.championIconUrl ?? undefined}
                    alt={f.name}
                    size="sm"
                  />
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Lista / estados */}
      {loading ? (
        <div className="hist-skel" aria-hidden="true">
          {Array.from({ length: 6 }, (_, i) => (
            <div className="hist-skel-row" key={i} />
          ))}
        </div>
      ) : error ? (
        <StateBlock error={error} />
      ) : items.length === 0 ? (
        <div className="hist-empty">
          <Mi
            name={hasFilter ? "filter_alt_off" : "history"}
            style={{ fontSize: 34, color: "var(--text-faint)" }}
          />
          {hasFilter ? (
            <>
              <b>Nenhuma partida com esse filtro.</b>
              <button type="button" className="btn ghost" onClick={clearFilters}>
                Limpar filtros
              </button>
            </>
          ) : (
            <>
              <b>Nenhuma partida registrada ainda.</b>
              <span className="faint" style={{ fontSize: 13 }}>
                Jogue Arena ranqueada — o ArenaRank processa as partidas automaticamente.
              </span>
            </>
          )}
        </div>
      ) : (
        <>
          {days.map((day) => (
            <section
              className="hist-day"
              key={day.dateKey}
              aria-label={`Partidas de ${day.label}`}
            >
              <div className="hist-day-head">
                <time dateTime={day.dateKey}>{day.label}</time>
                <span>
                  {nf(day.matches.length)} {day.matches.length === 1 ? "partida" : "partidas"}
                </span>
                <b className={`tnum delta ${deltaClass(day.crDelta)}`}>
                  {signed(day.crDelta)} PDL
                </b>
              </div>
              <div className="hist-day-list">
                {day.matches.map((match) => (
                  <HistRow
                    key={match.matchId}
                    match={match}
                    profileRiotId={profileRiotId}
                  />
                ))}
              </div>
            </section>
          ))}
          {hasMore && (
            <button
              type="button"
              className="btn ghost hist-more"
              onClick={loadMore}
              disabled={loadingMore}
            >
              {loadingMore ? "Carregando…" : `Carregar mais (${nf(total - items.length)} restantes)`}
            </button>
          )}
        </>
      )}
    </section>
  );
}

/* ============================================================
   Componente principal: Perfil (página única, sem sub-abas)
   ============================================================ */
export function Perfil() {
  const scopeRef = useRef<HTMLDivElement>(null);
  const { riotId = "" } = useParams<{ riotId: string }>();
  const decodedId = decodeURIComponent(riotId);

  const { data, loading, error, retry, refreshing, updatedAt } = useApi(
    () => loadProfileForRoute(decodedId),
    [decodedId]
  );
  const matches = usePlayerMatches(decodedId);
  const filtered = matches.result !== "" || matches.champion !== null;
  const fictional = isTelemetryLabProfile(decodedId);

  // Campeão-capa = mais jogado (por partidas). Fonte da splash do banner.
  const cover = useMemo<ChampStat | null>(
    () => (data?.champions.length ? [...data.champions].sort((a, b) => b.games - a.games)[0] : null),
    [data]
  );

  useGsapEntrance(scopeRef, {
    steps: PROFILE_ENTRANCE_STEPS,
    deps: [data?.riotId],
  });
  useGsapProfilePdl(scopeRef, data?.cr ?? null, data?.riotId);
  useGsapNameMarkers(scopeRef, data?.riotId);
  useScrollFocusBand(scopeRef, ".hist-row");
  useDrawCharts(scopeRef, [data?.riotId, data?.crHistory.length]);
  useGsapInteractions(scopeRef, PROFILE_INTERACTIONS);
  useGsapLoop(scopeRef, PROFILE_LOOPS, [loading, matches.loading]);

  return (
    <div className="shell profile-dossier" ref={scopeRef} data-gsap-scope>
      <div className="breadcrumb">
        <Link to="/">Início</Link>
        <span className="sep">›</span>
        <Link to="/leaderboard">Jogadores</Link>
        <span className="sep">›</span>
        <span>{decodedId || "Perfil"}</span>
        {data && (
          <FreshnessBadge updatedAt={updatedAt} refreshing={refreshing} onRefresh={retry} />
        )}
      </div>

      <StateBlock loading={loading} error={error}>
        {data && (
          <>
            <IdentityBanner
              data={data}
              firstRate={matches.lifetimeFirstRate}
              cover={cover}
              fictional={fictional}
            />
            <ProfileSurfaceNav riotId={decodedId} active="profile" />
            {data.form.length > 0 && <FormStrip form={data.form} />}

            <div className="pf-body">
              <div className="pf-main-col">
                <RecentPerformance
                  resp={matches.resp}
                  loading={matches.loading}
                  filtered={filtered}
                />
                <MatchHistory m={matches} profileRiotId={decodedId} />
              </div>

              <aside className="pf-side">
                <TrendCard data={data} />
                <ChampionsCard champions={data.champions} />
                <DuosCard h2h={data.h2h} />
                <SeasonsCard seasons={data.seasons} />
              </aside>
            </div>
          </>
        )}
      </StateBlock>
    </div>
  );
}
