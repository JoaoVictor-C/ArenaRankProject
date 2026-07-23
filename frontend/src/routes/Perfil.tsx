import "./Perfil.css";
import { useState, useMemo, useCallback, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import {
  PlayerAvatar,
  ChampIcon,
  TierBadge,
  Placement,
  Delta,
  Mi,
  StateBlock,
} from "../components";
import { useApi } from "../hooks/useApi";
import { api } from "../lib/api";
import { nf, signed, pct, deltaClass, tierLabel, timeAgo, fmtCountdown } from "../lib/format";
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

/* ============================================================
   Helpers internos
   ============================================================ */
function placeColor(p: number): string {
  if (p === 1) return "var(--primary-bright)";
  if (p <= 4) return "var(--green)";
  return "var(--red)";
}
function placeFg(p: number): string {
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

/* ============================================================
   Gráfico mini de evolução do PDL (SVG com faixa gradiente)
   ============================================================ */
function CrTrend({ history }: { history: CrHistoryPoint[] }) {
  if (history.length < 2) return null;
  const width = 300;
  const height = 92;
  const pad = 8;
  const vals = history.map((p) => p.cr);
  const minV = Math.min(...vals);
  const maxV = Math.max(...vals);
  const span = maxV - minV || 1;
  const step = (width - pad * 2) / (history.length - 1);
  const X = (i: number) => pad + i * step;
  const Y = (v: number) => height - pad - ((v - minV) / span) * (height - pad * 2);

  const line = history
    .map((pt, i) => (i === 0 ? "M" : "L") + X(i).toFixed(1) + " " + Y(pt.cr).toFixed(1))
    .join(" ");
  const lastIdx = history.length - 1;
  const areaPath =
    line +
    ` L${X(lastIdx).toFixed(1)} ${height.toFixed(1)} L${pad.toFixed(1)} ${height.toFixed(1)} Z`;

  return (
    <svg className="trend-chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      <defs>
        <linearGradient id="crtrend-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--gold)" stopOpacity="0.32" />
          <stop offset="100%" stopColor="var(--gold)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill="url(#crtrend-fill)" />
      <path
        d={line}
        fill="none"
        stroke="var(--gold)"
        strokeWidth="2.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle
        cx={X(lastIdx)}
        cy={Y(history[lastIdx].cr)}
        r={3.5}
        fill="var(--gold)"
        stroke="#0e0e10"
        strokeWidth={2}
      />
    </svg>
  );
}

/* ============================================================
   Banner de identidade + PDL (topo, largura total)
   ============================================================ */
function IdentityBanner({ data }: { data: PlayerProfile }) {
  const total = data.wins + data.losses;
  const firstRate = total > 0 ? Math.round((data.wins / total) * 100) : 0;

  return (
    <section className="pf-banner">
      {/* Identidade */}
      <div className="pfb-id">
        <PlayerAvatar colors={data.avatar} url={data.profileIconUrl} alt={data.name} size={76} />
        <div className="pfb-idtxt">
          <h1 className="pfb-name">
            {data.name}
            <span className="pfb-tag">{data.handle}</span>
          </h1>
          <div className="pfb-meta">
            <span className="pfb-region">
              <span className="flag-br" aria-hidden="true" />
              {data.region.toUpperCase()}
            </span>
            <TierBadge tier={data.tier} />
            {data.provisional && <span className="badge provisional">Provisório</span>}
            {data.tags.map((tag) => (
              <span key={tag.kind} className="badge neutral">
                <Mi name={tag.icon} /> {tag.label}
              </span>
            ))}
          </div>
          <div className="pfb-actions">
            <button className="btn ghost" type="button">
              <Mi name="person_add" /> Seguir
            </button>
            <button className="btn ghost" type="button">
              <Mi name="ios_share" /> Compartilhar
            </button>
          </div>
        </div>
      </div>

      {/* PDL + rank */}
      <div className="pfb-cr">
        <div className="pfb-cr-main">
          <div className="pfb-cr-num tnum">{nf(data.cr)}</div>
          <div className="pfb-cr-side">
            <div className="pfb-cr-lbl">PDL · Pontos de Liga</div>
            {data.tier !== "none" && <div className="pfb-cr-tier">{tierLabel(data.tier)}</div>}
          </div>
        </div>
        <div className="pfb-kvs">
          <div className="pfb-kv">
            <b className="tnum" style={{ color: "var(--primary-bright)" }}>#{nf(data.rank)}</b>
            <span>Rank global</span>
          </div>
          <div className="pfb-kv">
            <Delta value={data.delta7d} />
            <span>7 dias</span>
          </div>
          <div className="pfb-kv">
            <b className="tnum">{nf(total)}</b>
            <span>Partidas</span>
          </div>
          <div className="pfb-kv">
            <b className="tnum" style={{ color: "var(--primary-bright)" }}>{pct(firstRate)}</b>
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
  return (
    <div className="panel card">
      <div className="card-h">
        <span>PDL — 30 dias</span>
        <Delta value={data.delta7d} />
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
   Sidebar — Card: Desempenho (reage ao filtro do histórico)
   ============================================================ */
function PerformanceCard({
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
      <div className="panel card">
        <div className="card-h"><span>Desempenho</span></div>
        <div className="perf-grid">
          {Array.from({ length: 4 }, (_, i) => (
            <div className="perf-cell skel" key={i} />
          ))}
        </div>
      </div>
    );
  }
  if (!resp) return null;

  const s = resp.summary;
  const places = s.placements;
  const barCount = places[6] > 0 || places[7] > 0 ? 8 : 6;
  const maxCount = Math.max(1, ...places);

  return (
    <div className="panel card">
      <div className="card-h">
        <span>Desempenho</span>
        <span className="card-h-n tnum">{nf(s.games)} partidas</span>
      </div>
      {filtered && <div className="card-note">Métricas do filtro atual</div>}

      <div className="perf-grid">
        <div className="perf-cell">
          <b className="tnum" style={{ color: "var(--primary-bright)" }}>{pct(s.firstRate)}</b>
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
    <div className="panel card">
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
  const duos = useMemo(() => h2h.filter((r) => r.synergy === "duo"), [h2h]);
  const rivals = useMemo(() => h2h.filter((r) => r.synergy === "rival"), [h2h]);
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
function HistRow({ match }: { match: PlayerMatchRich }) {
  const [open, setOpen] = useState(false);
  const topHalf = match.place * 2 <= match.teamCount;
  const tone = match.place === 1 ? "first" : topHalf ? "top" : "low";

  return (
    <article className={`hist-row ${tone}`} data-open={open ? "true" : "false"}>
      <button
        type="button"
        className="hist-row-main"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
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

        <span className="hr-mods" aria-hidden="true">
          {match.modifiers
            .filter((mod) => mod.value !== 0)
            .slice(0, 3)
            .map((mod) => (
              <span
                key={mod.kind}
                className={`hm-dot ${mod.value > 0 ? "up" : "down"}`}
                title={`${mod.label}: ${signed(mod.value)}`}
              >
                <Mi name={mod.icon} />
              </span>
            ))}
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
      </button>

      <div className="hist-detail">
        <div className="hist-detail-inner">
          <div className="hd-label">Detalhamento de modificadores</div>
          {match.modifiers.length > 0 ? (
            <div className="mod-grid">
              {match.modifiers.map((mod) => (
                <div key={mod.kind} className="mod-row">
                  <span className="ml">
                    <span className="ic mi"><Mi name={mod.icon} /></span>
                    {mod.label}
                  </span>
                  <span
                    className={`mv tnum ${mod.value > 0 ? "delta up" : mod.value < 0 ? "delta down" : ""}`}
                  >
                    {mod.value === 0 ? "—" : signed(mod.value)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="faint" style={{ fontSize: 12 }}>Sem modificadores detalhados.</p>
          )}
          <div className="mod-foot">
            <div />
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
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!riotId) return;
    let alive = true;
    setLoading(true);
    setError(null);
    api
      .playerMatches(riotId, {
        limit: HIST_PAGE,
        offset: 0,
        result: result || undefined,
        champion: champion ?? undefined,
      })
      .then((r) => {
        if (!alive) return;
        setResp(r);
        setItems(r.matches);
      })
      .catch((e: Error) => alive && setError(e))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [riotId, result, champion]);

  const loadMore = useCallback(() => {
    setLoadingMore(true);
    api
      .playerMatches(riotId, {
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
function MatchHistory({ m }: { m: MatchesState }) {
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

  const clearFilters = useCallback(() => {
    setResult("");
    setChampion(null);
  }, [setResult, setChampion]);

  return (
    <div className="hist-main">
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
          {items.map((match) => (
            <HistRow key={match.matchId} match={match} />
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
    </div>
  );
}

/* ============================================================
   Componente principal: Perfil (página única, sem sub-abas)
   ============================================================ */
export function Perfil() {
  const { riotId = "" } = useParams<{ riotId: string }>();
  const decodedId = decodeURIComponent(riotId);

  const { data, loading, error } = useApi(() => api.player(decodedId), [decodedId]);
  const matches = usePlayerMatches(decodedId);
  const filtered = matches.result !== "" || matches.champion !== null;

  return (
    <div className="shell">
      <div className="breadcrumb">
        <Link to="/">Início</Link>
        <span className="sep">›</span>
        <Link to="/leaderboard">Jogadores</Link>
        <span className="sep">›</span>
        <span>{decodedId || "Perfil"}</span>
      </div>

      <StateBlock loading={loading} error={error}>
        {data && (
          <>
            <IdentityBanner data={data} />
            {data.form.length > 0 && <FormStrip form={data.form} />}

            <div className="pf-body">
              <aside className="pf-side">
                <TrendCard data={data} />
                <PerformanceCard resp={matches.resp} loading={matches.loading} filtered={filtered} />
                <ChampionsCard champions={data.champions} />
                <DuosCard h2h={data.h2h} />
                <SeasonsCard seasons={data.seasons} />
              </aside>

              <main className="pf-main-col">
                <MatchHistory m={matches} />
              </main>
            </div>
          </>
        )}
      </StateBlock>
    </div>
  );
}
