/* ============================================================
   Winrate.tsx — Página Champ Winrate (/winrate)
   Porta "Champ Winrate.html" (design staging) para React + Vite + TS.
   Dados reais via api.champions() + useApi + <StateBlock>.
   ============================================================ */
import { useState, useMemo, CSSProperties } from "react";
import "./Winrate.css";
import { StateBlock } from "../components";
import { api } from "../lib/api";
import { useApi } from "../hooks/useApi";
import type { ChampTierlistResponse, ChampRow, ChampTier } from "../lib/types";
import { timeAgo } from "../lib/format";

/* ── Tipos locais ────────────────────────────────────────────── */
type MetricKey = "top4" | "first" | "avgplace" | "pick" | "ban";
type ViewMode   = "tier" | "table";

/** Retorna o data-tier normalizado a partir do label/key da API */
function normalizeTierKey(t: ChampTier): string {
  const k = t.key.toLowerCase().replace("+", "plus");
  return k; // "splus" | "s" | "a" | "b" | "c" | "d"
}

/** Formata porcentagem pt-BR com 1 decimal (ex.: "62,1%") */
function fmtPct(n: number): string {
  return n.toFixed(1).replace(".", ",") + "%";
}

/** Formata colocação média pt-BR (ex.: "4,01") */
function fmtPlace(n: number): string {
  return n.toFixed(2).replace(".", ",");
}

/** Valor de exibição de acordo com a métrica ativa */
function metricValue(c: ChampRow, metric: MetricKey): string {
  switch (metric) {
    case "top4":     return fmtPct(c.top4);
    case "first":    return fmtPct(c.first);
    case "avgplace": return fmtPlace(c.avgPlace);
    case "pick":     return fmtPct(c.pickRate);
    case "ban":      return c.banRate < 0.01 ? "–" : fmtPct(c.banRate);
  }
}

/** Rótulo da aba de métrica */
const METRIC_LABELS: Record<MetricKey, string> = {
  top4:     "TOP 4",
  first:    "1º LUGAR",
  avgplace: "COL. MÉDIA",
  pick:     "TAXA DE ESCOLHA",
  ban:      "TAXA DE BAN",
};

/** Roles disponíveis nos chips de filtro */
const ROLES = ["TODOS", "ATIRADOR", "MAGO", "TANQUE", "LUTADOR", "ASSASSINO", "SUPORTE"];

/* ── Componente principal ────────────────────────────────────── */
export function Winrate() {
  /* --- estado de UI --- */
  const [view,       setView]       = useState<ViewMode>("tier");
  const [metric,     setMetric]     = useState<MetricKey>("top4");
  const [search,     setSearch]     = useState("");
  const [role,       setRole]       = useState("TODOS");
  const [patch,      setPatch]      = useState<string | undefined>(undefined);
  const [region,     setRegion]     = useState<string | undefined>(undefined);
  const [selected,   setSelected]   = useState<ChampRow | null>(null);

  /* --- fetch --- */
  const { data, loading, error } = useApi<ChampTierlistResponse>(
    () => api.champions({ format: "3v3", metric, patch, region }),
    [metric, patch, region],
  );

  /* --- filtro de busca + role nos campeões --- */
  const filterChamp = (c: ChampRow) => {
    const q = search.trim().toLowerCase();
    if (q && !c.name.toLowerCase().includes(q)) return false;
    if (role !== "TODOS") {
      // role vem como "Atirador", chips são "ATIRADOR" etc.
      if (c.role.toUpperCase() !== role) return false;
    }
    return true;
  };

  /* --- lista da tabela: usa data.table, filtrada e ordenada --- */
  const tableRows = useMemo(() => {
    if (!data) return [];
    return data.table.filter(filterChamp);
  }, [data, search, role]); // eslint-disable-line react-hooks/exhaustive-deps

  /* --- tiers filtrados --- */
  const filteredTiers = useMemo(() => {
    if (!data) return [];
    return data.tiers.map((t) => ({
      ...t,
      champions: t.champions.filter(filterChamp),
    })).filter((t) => t.champions.length > 0 || (search === "" && role === "TODOS"));
  }, [data, search, role]); // eslint-disable-line react-hooks/exhaustive-deps

  /* --- detalhe: abre o primeiro campeão por padrão quando os dados chegam --- */
  const detailChamp: ChampRow | null = useMemo(() => {
    if (selected) return selected;
    if (data?.tiers?.[0]?.champions?.[0]) return data.tiers[0].champions[0];
    return null;
  }, [selected, data]);

  /* --- info de tier do campeão selecionado --- */
  function tierForChamp(c: ChampRow): ChampTier | undefined {
    return data?.tiers.find((t) => t.champions.some((ch) => ch.rank === c.rank));
  }

  /* --- cor do d-tier badge no detalhe --- */
  function detailTierStyle(tierKey: string): CSSProperties {
    const colorMap: Record<string, { bg: string; color: string }> = {
      splus: { bg: "var(--wr-tier-splus)", color: "#0a0a0b" },
      s:     { bg: "var(--wr-tier-s)",     color: "#fff" },
      a:     { bg: "var(--wr-tier-a)",     color: "#fff" },
      b:     { bg: "var(--wr-tier-b)",     color: "#0a0a0b" },
      c:     { bg: "var(--wr-tier-c)",     color: "#fff" },
      d:     { bg: "var(--wr-tier-d)",     color: "#fff" },
    };
    const def = colorMap[tierKey] ?? { bg: "#444", color: "#fff" };
    return { background: def.bg, color: def.color } as CSSProperties;
  }

  /* --- rótulo do tier (S+, S, A, …) --- */
  function tierLabelFor(c: ChampRow): string {
    const t = tierForChamp(c);
    return t ? t.key : c.tier;
  }

  /* --- data-tier normalizado do ChampRow --- */
  function tierDataAttr(c: ChampRow): string {
    const t = tierForChamp(c);
    if (!t) return c.tier.toLowerCase().replace("+", "plus");
    return normalizeTierKey(t);
  }

  return (
    <div className="wr-page">
      {/* ── Conteúdo principal ── */}
      <section className="wr-main">

        {/* Título + toggle */}
        <div className="title-block">
          <h1>CHAMP WINRATE</h1>
          <div className="rule" aria-hidden="true" />
          <div className="spacer" />
          <div className="view-toggle" role="tablist" aria-label="Modo de visualização">
            <button
              type="button"
              className={view === "tier" ? "active" : ""}
              onClick={() => setView("tier")}
              aria-selected={view === "tier"}
              role="tab"
            >
              TIER LIST
            </button>
            <button
              type="button"
              className={view === "table" ? "active" : ""}
              onClick={() => setView("table")}
              aria-selected={view === "table"}
              role="tab"
            >
              TABELA
            </button>
          </div>
        </div>

        {/* Metadados */}
        <p className="wr-subtitle">
          <span className="live" title="dados em tempo real" />
          {data ? (
            <>
              <span>Atualizado {timeAgo(data.updatedAt)}</span>
              <span className="dot" aria-hidden="true" />
              <span className="meta-tag">PATCH {data.patch}</span>
              <span className="dot" aria-hidden="true" />
              <span>ARENA · {data.format.toUpperCase()}</span>
              <span className="dot" aria-hidden="true" />
              <span>{data.region.toUpperCase()}</span>
              <span className="dot" aria-hidden="true" />
              <span>{data.sampleSize.toLocaleString("pt-BR")} partidas amostradas</span>
            </>
          ) : (
            <span>Carregando metadados…</span>
          )}
        </p>

        {/* Filtros */}
        <div className="lb-filters" role="search">
          <div className="filter-search">
            <span className="icon" aria-hidden="true">⌕</span>
            <input
              type="text"
              placeholder="Procurar campeão…"
              aria-label="Procurar campeão"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          {/* Dropdown Patch */}
          <button
            type="button"
            className="filter-select"
            aria-label={`Patch: ${data?.patch ?? "carregando"}`}
            onClick={() => {
              /* Futuramente: abrir dropdown de seleção de patch */
              setPatch(undefined);
            }}
          >
            <span>Patch {data?.patch ?? "–"}</span>
            <span className="caret" aria-hidden="true">▾</span>
          </button>

          {/* Dropdown Região */}
          <button
            type="button"
            className="filter-select"
            aria-label={`Região: ${data?.region ?? "carregando"}`}
            onClick={() => {
              /* Futuramente: abrir dropdown de seleção de região */
              setRegion(undefined);
            }}
          >
            <span>{data?.region ? data.region.toUpperCase() : "Região"}</span>
            <span className="caret" aria-hidden="true">▾</span>
          </button>

          {/* Chips de role */}
          <div className="role-chips" role="group" aria-label="Classe">
            {ROLES.map((r) => (
              <button
                key={r}
                type="button"
                className={role === r ? "active" : ""}
                onClick={() => setRole(r)}
                aria-pressed={role === r}
              >
                {r}
              </button>
            ))}
          </div>

          {/* Ordenar */}
          <button type="button" className="filter-select">
            <span>Ordenar: {METRIC_LABELS[metric]}</span>
            <span className="caret" aria-hidden="true">▾</span>
          </button>
        </div>

        {/* Abas de métrica */}
        <div className="metric-tabs" role="tablist" aria-label="Métrica">
          {(Object.keys(METRIC_LABELS) as MetricKey[]).map((m) => (
            <button
              key={m}
              type="button"
              className={metric === m ? "active" : ""}
              onClick={() => setMetric(m)}
              aria-selected={metric === m}
              role="tab"
            >
              {METRIC_LABELS[m]}
            </button>
          ))}
          <div className="spacer" aria-hidden="true" />
          <div className="legend" aria-label="Legenda de cores">
            <span className="legend-item"><i className="swatch" style={{ background: "#48d9d9" }} />col. média</span>
            <span className="legend-item"><i className="swatch" style={{ background: "#4a78ff" }} />1º lugar</span>
            <span className="legend-item"><i className="swatch" style={{ background: "#ff9a3a" }} />top 4</span>
            <span className="legend-item"><i className="swatch" style={{ background: "#9b5cff" }} />escolha</span>
            <span className="legend-item"><i className="swatch" style={{ background: "#d4c43a" }} />aparições</span>
          </div>
        </div>

        {/* StateBlock cobre loading/erro/vazio */}
        <StateBlock loading={loading} error={error}>
          {data && (
            <>
              {/* ── TIER LIST ── */}
              {view === "tier" && (
                <div className="tier-list" aria-label="Tier list de campeões">
                  {filteredTiers.map((tier) => {
                    const tierKey = normalizeTierKey(tier);
                    return (
                      <div
                        key={tier.key}
                        className="tier-row"
                        data-tier={tierKey}
                      >
                        <div className="tier-band">
                          <div className="label">{tier.key}</div>
                          <div className="count">{tier.champions.length} CAMPEÕES</div>
                        </div>
                        <div className="tier-cards">
                          {tier.champions.map((c) => (
                            <article
                              key={c.rank}
                              className="champ-card"
                              data-id={c.rank}
                              style={
                                {
                                  "--c1": c.champion.c1,
                                  "--c2": c.champion.c2,
                                  "--tier-color": tier.color,
                                } as CSSProperties
                              }
                              onClick={() => setSelected(c)}
                              aria-label={c.name}
                              tabIndex={0}
                              onKeyDown={(e) => e.key === "Enter" && setSelected(c)}
                            >
                              <span className="ch-rank">#{c.rank}</span>
                              {/* placeholder gradiente — arte real é proibida pela ToS Riot */}
                              <div className="ch-avatar" aria-hidden="true" />
                              <div className="ch-name">{c.name}</div>
                              <div className="ch-stat">{metricValue(c, metric)}</div>
                              <div className="ch-sub">{METRIC_LABELS[metric]}</div>
                            </article>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* ── PAINEL DE DETALHE (só na tier list) ── */}
              {view === "tier" && detailChamp && (
                <div
                  className="panel detail"
                  style={
                    {
                      "--c1": detailChamp.champion.c1,
                      "--c2": detailChamp.champion.c2,
                    } as CSSProperties
                  }
                  aria-live="polite"
                  aria-label={`Detalhe de ${detailChamp.name}`}
                >
                  {/* Avatar grande */}
                  <div
                    className="d-av"
                    aria-hidden="true"
                    style={
                      {
                        background: `radial-gradient(circle at 30% 30%, ${detailChamp.champion.c2}, ${detailChamp.champion.c1} 70%)`,
                      } as CSSProperties
                    }
                  />

                  {/* Nome + meta */}
                  <div>
                    <h2>{detailChamp.name}</h2>
                    <div className="d-meta">
                      <span
                        className="d-tier"
                        style={detailTierStyle(tierDataAttr(detailChamp))}
                      >
                        {tierLabelFor(detailChamp)}
                      </span>
                      <span>{detailChamp.role}</span>
                    </div>
                  </div>

                  {/* Stats */}
                  <div className="d-stats">
                    <div className="d-stat">
                      <div className="v cyan">{fmtPlace(detailChamp.avgPlace)}</div>
                      <div className="l">Col. média</div>
                    </div>
                    <div className="d-stat">
                      <div className="v blue">{fmtPct(detailChamp.first)}</div>
                      <div className="l">1º lugar</div>
                    </div>
                    <div className="d-stat">
                      <div className="v orange">{fmtPct(detailChamp.top4)}</div>
                      <div className="l">Top 4</div>
                    </div>
                    <div className="d-stat">
                      <div className="v pink">{fmtPct(detailChamp.pickRate)}</div>
                      <div className="l">Escolha</div>
                    </div>
                  </div>
                </div>
              )}

              {/* ── TABELA ── */}
              {view === "table" && (
                <div className="tbl wr-table" role="table" aria-label="Tabela de campeões">
                  {/* Cabeçalho */}
                  <div className="wr-row wr-head" role="row">
                    <div role="columnheader">CLASSIFICAÇÃO</div>
                    <div role="columnheader">CAMPEÃO</div>
                    <div role="columnheader">TIER</div>
                    <div role="columnheader">COL. MÉDIA</div>
                    <div role="columnheader">1º LUGAR</div>
                    <div role="columnheader">TOP 4</div>
                    <div role="columnheader">TAXA DE ESCOLHA</div>
                    <div role="columnheader">TAXA DE BAN</div>
                    <div role="columnheader">APARIÇÕES</div>
                  </div>

                  {/* Linhas */}
                  {tableRows.map((c, i) => {
                    const tKey = tierDataAttr(c);
                    return (
                      <div
                        key={c.rank}
                        className="wr-row"
                        role="row"
                        style={
                          {
                            "--c1": c.champion.c1,
                            "--c2": c.champion.c2,
                          } as CSSProperties
                        }
                      >
                        <div className="wr-rank" role="cell">{i + 1}</div>
                        <div className="wr-champ" role="cell">
                          {/* placeholder — arte real é proibida pela ToS Riot */}
                          <div className="av" aria-hidden="true" />
                          <span>{c.name}</span>
                        </div>
                        <div role="cell">
                          <span className="tier-chip" data-tier={tKey}>
                            {tierLabelFor(c)}
                          </span>
                        </div>
                        <div role="cell">
                          <div className="wr-stat">
                            {fmtPlace(c.avgPlace)}
                            <i className="bar cyan" aria-hidden="true" />
                          </div>
                        </div>
                        <div role="cell">
                          <div className="wr-stat">
                            {fmtPct(c.first)}
                            <i className="bar blue" aria-hidden="true" />
                          </div>
                        </div>
                        <div role="cell">
                          <div className="wr-stat">
                            {fmtPct(c.top4)}
                            <i className="bar orange" aria-hidden="true" />
                          </div>
                        </div>
                        <div role="cell">
                          <div className="wr-stat">
                            {fmtPct(c.pickRate)}
                            <i className="bar purple" aria-hidden="true" />
                          </div>
                        </div>
                        <div role="cell">
                          <div className="wr-stat">
                            {c.banRate < 0.01 ? "–" : fmtPct(c.banRate)}
                          </div>
                        </div>
                        <div role="cell">
                          <div className="wr-stat">
                            {/* aparições = sampleSize * pickRate/100 arredondado */}
                            {Math.round(data.sampleSize * c.pickRate / 100).toLocaleString("pt-BR")}
                            <i className="bar yellow" aria-hidden="true" />
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </StateBlock>

      </section>

      {/* ── Sidebar (decorativa — sem dados de usuário real) ── */}
      <aside className="wr-sidebar" aria-label="Painel lateral">
        <div className="wr-side-h">Informações</div>
        <p style={{ color: "var(--text-faint,#6b6b70)", fontSize: 12, lineHeight: 1.5 }}>
          Estatísticas de campeões para o modo Arena baseadas em partidas ranqueadas reais.
          Atualizado periodicamente com os dados mais recentes.
        </p>

        {data && (
          <>
            <div className="wr-side-h">Resumo do patch</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                <span style={{ color: "var(--text-dim,#acacac)" }}>Patch</span>
                <span style={{ fontWeight: 700, color: "var(--wr-yellow,#ffe26c)" }}>{data.patch}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                <span style={{ color: "var(--text-dim,#acacac)" }}>Região</span>
                <span style={{ fontWeight: 700 }}>{data.region.toUpperCase()}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                <span style={{ color: "var(--text-dim,#acacac)" }}>Partidas</span>
                <span style={{ fontWeight: 700 }}>{data.sampleSize.toLocaleString("pt-BR")}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                <span style={{ color: "var(--text-dim,#acacac)" }}>Campeões</span>
                <span style={{ fontWeight: 700 }}>{data.table.length}</span>
              </div>
            </div>

            {/* Distribuição por tier */}
            <div className="wr-side-h">Distribuição por tier</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {data.tiers.map((t) => {
                const tKey = normalizeTierKey(t);
                const colorMap: Record<string, string> = {
                  splus: "var(--wr-tier-splus,#f1c54a)",
                  s:     "var(--wr-tier-s,#ff32d9)",
                  a:     "var(--wr-tier-a,#9b5cff)",
                  b:     "var(--wr-tier-b,#48bdff)",
                  c:     "var(--wr-tier-c,#5a8a3a)",
                  d:     "var(--wr-tier-d,#6b6b70)",
                };
                const color = colorMap[tKey] ?? "#888";
                return (
                  <div key={t.key} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{
                      width: 28,
                      height: 22,
                      borderRadius: 4,
                      background: color,
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontWeight: 800,
                      fontSize: 12,
                      color: tKey === "s" || tKey === "a" || tKey === "c" || tKey === "d" ? "#fff" : "#0a0a0b",
                      flexShrink: 0,
                    }}>
                      {t.key}
                    </span>
                    <span style={{ fontSize: 13, color: "var(--text-dim,#acacac)" }}>
                      {t.label}
                    </span>
                    <span style={{ marginLeft: "auto", fontWeight: 700, fontSize: 13 }}>
                      {t.champions.length}
                    </span>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </aside>
    </div>
  );
}
