/* ============================================================
   Admin.tsx — Painel Administrativo do ArenaRank
   Porta Admin.html + admin.js para React + Vite + TS.
   Dados: api.adminOverview() via useApi + <StateBlock>.
   ============================================================ */
import "./Admin.css";
import React, { useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { Mi, StateBlock } from "../components";
import { api } from "../lib/api";
import { useApi } from "../hooks/useApi";
import type { AdminOverview, TournamentCreate } from "../lib/types";
import { timeAgo } from "../lib/format";

/* ─── Ícones por métrica (chave → nome Material Symbol) ─── */
const METRIC_ICONS: Record<string, string> = {
  crs_matches_processed_total:    "memory",
  crs_queue_depth:                "layers",
  crs_worker_active_count:        "bolt",
  "5xx rate":                     "warning",
  crs_processing_duration_seconds:"timer",
  crs_leaderboard_update_latency: "schedule",
};

type SecId = "health" | "seasons" | "tournaments" | "integrity" | "players" | "dlq";

/* ─── Gráfico SVG de profundidade de fila (estático de design) ─── */
function QueueChart() {
  const std = [320, 410, 560, 720, 640, 520, 460, 380, 340, 300, 290, 280];
  const pri = [60,  90,  140, 210, 180, 150, 130, 110,  95,  85,  82,  80];
  const w = 560, h = 150, pad = 8, max = 760;
  const step = (w - pad * 2) / (std.length - 1);
  const Y = (v: number) => h - pad - (v / max) * (h - pad * 2);
  const path = (arr: number[]) =>
    arr.map((v, i) => `${i ? "L" : "M"}${(pad + i * step).toFixed(1)} ${Y(v).toFixed(1)}`).join(" ");
  const thr = Y(500);

  return (
    <svg className="qchart" viewBox="0 0 560 150" preserveAspectRatio="none">
      <line
        x1={pad} y1={thr} x2={w - pad} y2={thr}
        stroke="rgba(255,195,0,0.5)" strokeWidth="1" strokeDasharray="4 4"
      />
      <text x={w - pad - 4} y={thr - 5} fill="#ffc300" fontSize="9" textAnchor="end"
        fontFamily="Plus Jakarta Sans">
        limiar KEDA 500
      </text>
      <path
        d={`${path(std)} L${w - pad} ${h - pad} L${pad} ${h - pad} Z`}
        fill="rgba(76,182,236,0.12)"
      />
      <path d={path(std)} fill="none" stroke="#4cb6ec" strokeWidth="2.5" strokeLinejoin="round" />
      <path d={path(pri)} fill="none" stroke="#4fd17a" strokeWidth="2.5" strokeLinejoin="round" />
    </svg>
  );
}

/* ─── Seção: Saúde do Sistema ─── */
function SectionHealth({ data }: { data: AdminOverview }) {
  return (
    <section className="a-sec" data-active="true">
      {/* Cabeçalho */}
      <div className="admin-h">
        <div>
          <h1>Saúde do Sistema</h1>
          <div className="desc">Métricas em tempo real · Prometheus + Grafana · temporada ativa</div>
        </div>
        <div className="live-indicator">
          <span className="live-dot" />
          TODOS OS SERVIÇOS OPERANTES
        </div>
      </div>

      {/* Cards de métricas */}
      <div className="metrics">
        {data.metrics.map((m) => (
          <div className="metric" key={m.key}>
            <div className="k">
              <Mi name={METRIC_ICONS[m.key] ?? "monitoring"} style={{ fontSize: 15, color: "var(--primary-bright)" }} />
              {m.label}
            </div>
            <div className="v tnum">{m.value}</div>
            {m.trend !== undefined && (
              <div className="sub">
                <span className={`delta ${m.trend >= 0 ? "up" : "down"}`}>
                  {m.trend >= 0 ? "▲" : "▼"} {Math.abs(m.trend)}%
                </span>
              </div>
            )}
            <div className="mono-id">{m.key}</div>
          </div>
        ))}
      </div>

      {/* Fila + Alertas */}
      <div className="panel-2col">
        <div className="card">
          <h3>Profundidade da fila — últimas 2h</h3>
          <p className="hint">crs_queue_depth · prioritária vs. padrão · KEDA escala 2→20 workers acima de 500</p>
          <QueueChart />
          <div className="trend-legend">
            <span>
              <i className="line-swatch" style={{ background: "#4cb6ec" }} />
              Padrão
            </span>
            <span>
              <i className="line-swatch" style={{ background: "#4fd17a" }} />
              Prioritária
            </span>
          </div>
        </div>

        <div className="card">
          <h3>Alertas ativos</h3>
          <p className="hint">AlertManager · regras de severidade</p>
          <div className="alerts">
            {/* Alertas de workers com warn/down */}
            {data.workers.filter((w) => w.status !== "ok").map((w) => (
              <div className="alert warning" key={w.name}>
                <span className="sev">Warning</span>
                <div className="msg">
                  {w.name}
                  <small>Carga {Math.round(w.load * 100)}% · status {w.status}</small>
                </div>
                <span className="t">agora</span>
              </div>
            ))}
            {/* Alertas de Riot API com warn */}
            {data.riotApi.filter((r) => r.status !== "ok").map((r) => (
              <div className="alert warning" key={r.name}>
                <span className="sev">Warning</span>
                <div className="msg">
                  {r.name}
                  <small>{r.usage}</small>
                </div>
                <span className="t">agora</span>
              </div>
            ))}
            {/* Sem alertas críticos */}
            <div className="alert ok-alert">
              <span className="sev">OK</span>
              <div className="msg">
                Sem alertas críticos
                <small>Processamento ativo · replicação DB &lt; 1s · Redis 58% memória</small>
              </div>
              <span className="t">agora</span>
            </div>
          </div>
        </div>
      </div>

      {/* Workers + Riot API */}
      <div className="panel-2col" style={{ marginTop: 16 }}>
        <div className="card">
          <h3>Pools de workers</h3>
          <p className="hint">Kubernetes · namespace processing · auto-escala independente</p>
          <div className="tbl wtable">
            <div className="head">
              <div>Pool / Pod</div>
              <div>Status</div>
              <div>Carga</div>
              <div>Jobs/min</div>
              <div>—</div>
            </div>
            {data.workers.map((w) => (
              <div className="row" key={w.name}>
                <div className="mono" style={{ fontFamily: "ui-monospace, Menlo, monospace", fontSize: 11 }}>
                  {w.name}
                </div>
                <div>
                  <span className="status-dot">
                    <span className={`d ${w.status === "ok" ? "ok" : w.status === "warn" ? "warn" : "err"}`} />
                    {w.status === "ok" ? "Operante" : w.status === "warn" ? "Alta carga" : "Indisponível"}
                  </span>
                </div>
                <div>{Math.round(w.load * 100)}%</div>
                <div>—</div>
                <div>—</div>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <h3>Riot API</h3>
          <p className="hint">riot-client · token bucket + circuit breaker</p>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {data.riotApi.map((r) => (
              <div className="proc-row" key={r.name}>
                <span className="faint">{r.name}</span>
                <b style={{ color: r.status === "ok" ? "var(--green)" : "var(--amber)" }}>
                  {r.usage}
                </b>
              </div>
            ))}
            <div className="pbar" style={{ marginTop: 4 }}>
              <span style={{ width: "64%" }} />
            </div>
            <div className="faint" style={{ font: "500 11px/1 'Plus Jakarta Sans', sans-serif" }}>
              Token bucket: 64% · refil em 12s
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ─── Seção: Gestão de Temporada ─── */
const LIFECYCLE_STEPS = [
  { key: "active",    label: "Active",     sub: "em andamento" },
  { key: "soft_lock", label: "Soft Lock",  sub: "últimos 7 dias" },
  { key: "ended",     label: "Ended",      sub: "snapshot S3" },
  { key: "off_season",label: "Off-Season", sub: "aguardando" },
];

/* Histórico estático de temporadas (DTO sample; backend retornará dados reais futuramente) */
const SEASON_HIST = [
  { name: "Temporada 2 · Vanguarda", period: "Nov 2025 — Fev 2026", players: "6.204", status: "ENDED" },
  { name: "Temporada 1 · Gênese",    period: "Jul 2025 — Out 2025", players: "3.918", status: "ENDED" },
  { name: "Pré-temporada · Beta",    period: "Mai 2025 — Jun 2025", players: "1.142", status: "OFF-SEASON" },
];

function SectionSeasons({ data }: { data: AdminOverview }) {
  const { season } = data;
  const currentStepIndex = LIFECYCLE_STEPS.findIndex(
    (s) => s.key === season.state || s.label.toLowerCase() === season.state.toLowerCase()
  );
  const activeSuffix = currentStepIndex === -1 ? 0 : currentStepIndex;

  return (
    <section className="a-sec" data-active="true">
      <div className="admin-h">
        <div>
          <h1>Gestão de Temporada</h1>
          <div className="desc">Máquina de estados do ciclo de vida · soft-reset e snapshots</div>
        </div>
        <button className="btn primary" type="button">+ Nova temporada</button>
      </div>

      {/* Temporada atual */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3>Temporada {season.current} · Arena Open</h3>
        <p className="hint">queue_id 1700 · iniciada em {timeAgo(season.startedAt)} · encerra em 31 mai 2026</p>

        {/* Ciclo de vida */}
        <div className="lifecycle">
          {LIFECYCLE_STEPS.map((step, i) => {
            const isCurrent = i === activeSuffix;
            const isDone = i < activeSuffix;
            const cls = `lc-step${isCurrent ? " current" : isDone ? " done" : ""}`;
            return (
              <React.Fragment key={step.key}>
                {i > 0 && <div className={`lc-line${isDone ? " done" : ""}`} />}
                <div className={cls}>
                  <div className="dot">{isCurrent ? "●" : i + 1}</div>
                  <div className="lbl">{step.label}</div>
                  <div className="st">{step.sub}</div>
                </div>
              </React.Fragment>
            );
          })}
        </div>

        {/* Config da temporada */}
        <div className="cfg-grid">
          {Object.entries(season.config).map(([k, v]) => (
            <div className="cfg" key={k}>
              <div className="k">{k}</div>
              <div className="v">{v}</div>
            </div>
          ))}
          {/* Fallback com valores fixos do design quando config estiver vazia */}
          {Object.keys(season.config).length === 0 && (
            <>
              <div className="cfg"><div className="k">Placement matches</div><div className="v">10 <small>· amplificação 2,0×</small></div></div>
              <div className="cfg"><div className="k">Fator de soft-reset</div><div className="v">0,5 <small>· new = 1000 + (prev−1000)·0,5</small></div></div>
              <div className="cfg"><div className="k">Soft cap</div><div className="v">5.000 <small>· retornos decrescentes acima</small></div></div>
              <div className="cfg"><div className="k">Reset de σ</div><div className="v">×1,5 <small>· teto 350</small></div></div>
            </>
          )}
        </div>

        <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
          <button className="btn" type="button">Editar configuração</button>
          <button className="btn" type="button" style={{ borderColor: "rgba(255,195,0,0.4)", color: "var(--gold)" }}>
            → Transicionar para Soft Lock
          </button>
          <button className="btn" type="button" style={{ borderColor: "rgba(255,74,74,0.4)", color: "var(--red)" }}>
            Encerrar temporada
          </button>
        </div>
      </div>

      {/* Histórico */}
      <div className="card">
        <h3>Histórico de temporadas</h3>
        <p className="hint">Snapshots finais arquivados em S3 (Parquet)</p>
        <div className="tbl" style={{ border: "1px solid var(--line)", borderRadius: 8, overflow: "hidden" }}>
          <div className="head" style={{ gridTemplateColumns: "1.4fr 1fr 110px 130px 120px" }}>
            <div>Temporada</div>
            <div>Período</div>
            <div>Jogadores</div>
            <div>Status</div>
            <div>Snapshot</div>
          </div>
          {SEASON_HIST.map((s) => (
            <div className="row" key={s.name}
              style={{ gridTemplateColumns: "1.4fr 1fr 110px 130px 120px", padding: "13px 16px", font: "600 13px/1.3 'Plus Jakarta Sans', sans-serif" }}>
              <div><b>{s.name}</b></div>
              <div className="faint">{s.period}</div>
              <div className="tnum">{s.players}</div>
              <div><span className="sev-tag ended">{s.status}</span></div>
              <div style={{ color: "var(--green)", fontSize: 12 }}>✓ arquivado</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── Seção: Integridade ─── */
type IntegFilter = "all" | "critical" | "warn" | "info";

function SectionIntegrity({ data }: { data: AdminOverview }) {
  const [filter, setFilter] = useState<IntegFilter>("all");
  const rows = filter === "all" ? data.integrity : data.integrity.filter((r) => r.severity === filter);

  return (
    <section className="a-sec" data-active="true">
      <div className="admin-h">
        <div>
          <h1>Fila de Integridade</h1>
          <div className="desc">Partidas sinalizadas para revisão · aplicar overrides manuais · sistema não pune automaticamente</div>
        </div>
      </div>

      <div className="lb-filters" style={{ display: "flex", gap: 14, marginBottom: 14 }}>
        <div className="chips">
          {(["all", "critical", "warn", "info"] as IntegFilter[]).map((f) => (
            <div
              key={f}
              className="chip"
              data-active={filter === f ? "true" : "false"}
              onClick={() => setFilter(f)}
              style={{ cursor: "pointer" }}
            >
              {f === "all" ? "Todas" : f.toUpperCase()}
            </div>
          ))}
        </div>
      </div>

      <div className="panel" style={{ overflow: "hidden" }}>
        <div className="tbl iq">
          <div className="head">
            <div>Partida</div>
            <div>Tipo de flag</div>
            <div>Sev.</div>
            <div>Jogador</div>
            <div>Detectada</div>
            <div>Ação</div>
          </div>
          {rows.length === 0 && (
            <div className="row" style={{ gridColumn: "1/-1", justifyContent: "center", color: "var(--text-faint)", padding: "20px 16px" }}>
              Nenhum item encontrado.
            </div>
          )}
          {rows.map((r) => (
            <div className="row" key={r.id}>
              <div className="mono">{r.id}</div>
              <div>
                <b>{r.reason}</b>
              </div>
              <div><span className={`sev-tag ${r.severity}`}>{r.severity}</span></div>
              <div className="faint">{r.player || "—"}</div>
              <div className="faint">{timeAgo(r.ts)}</div>
              <div className="row-actions">
                <button className="mini-btn primary" type="button">Revisar</button>
                <button className="mini-btn" type="button">Override</button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── Seção: Flags de Jogador ─── */
function SectionPlayers({ data }: { data: AdminOverview }) {
  return (
    <section className="a-sec" data-active="true">
      <div className="admin-h">
        <div>
          <h1>Flags de Jogador</h1>
          <div className="desc">Flags de moderação a nível de conta · adicionar notas · revisão humana</div>
        </div>
      </div>

      <div className="panel" style={{ overflow: "hidden" }}>
        <div className="tbl pf">
          <div className="head">
            <div>Jogador</div>
            <div>Flag</div>
            <div>Sev.</div>
            <div>Notas do moderador</div>
            <div>Ação</div>
          </div>
          {data.flags.length === 0 && (
            <div className="row" style={{ gridColumn: "1/-1", justifyContent: "center", color: "var(--text-faint)", padding: "20px 16px" }}>
              Nenhuma flag registrada.
            </div>
          )}
          {data.flags.map((f) => (
            <div className="row" key={f.id}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span className="pavatar" style={{ width: 32, height: 32 } as React.CSSProperties} />
                <b>{f.player}</b>
              </div>
              <div>{f.flag}</div>
              <div><span className={`sev-tag ${f.severity}`}>{f.severity}</span></div>
              <div className="faint" style={{ fontWeight: 500 }}>—</div>
              <div className="row-actions">
                <button className="mini-btn" type="button">+ Nota</button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── Seção: DLQ ─── */
function SectionDlq({ data }: { data: AdminOverview }) {
  const total = data.dlq.length;

  return (
    <section className="a-sec" data-active="true">
      <div className="admin-h">
        <div>
          <h1>Revisão de DLQ</h1>
          <div className="desc">Partidas que falharam após 3 tentativas · reprocessamento idempotente manual</div>
        </div>
        <button className="btn" type="button">Reprocessar tudo</button>
      </div>

      {/* Métricas resumidas */}
      <div className="metrics" style={{ gridTemplateColumns: "repeat(3,1fr)", marginBottom: 16 }}>
        <div className="metric">
          <div className="k">Intake DLQ (5min)</div>
          <div className="v" style={{ color: "var(--gold)" }}>{total}</div>
          <div className="sub faint">{total > 0 ? "aguardando revisão" : "fila limpa"}</div>
        </div>
        <div className="metric">
          <div className="k">Total na DLQ</div>
          <div className="v">{total}</div>
          <div className="sub faint">aguardando revisão</div>
        </div>
        <div className="metric">
          <div className="k">Reprocessadas (24h)</div>
          <div className="v" style={{ color: "var(--green)" }}>—</div>
          <div className="sub faint">dados históricos</div>
        </div>
      </div>

      <div className="panel" style={{ overflow: "hidden" }}>
        <div className="tbl dlq">
          <div className="head">
            <div>Match ID</div>
            <div>Erro</div>
            <div>Tent.</div>
            <div>Última tentativa</div>
            <div>Ação</div>
          </div>
          {data.dlq.length === 0 && (
            <div className="row" style={{ gridColumn: "1/-1", justifyContent: "center", color: "var(--text-faint)", padding: "20px 16px" }}>
              DLQ vazia.
            </div>
          )}
          {data.dlq.map((d) => (
            <div className="row" key={d.matchId}>
              <div className="mono" style={{ fontFamily: "ui-monospace, Menlo, monospace", fontSize: 11 }}>
                {d.matchId}
              </div>
              <div className="err-txt">{d.reason}</div>
              <div><span className="sev-tag critical">{d.attempts}×</span></div>
              <div className="faint">{timeAgo(d.ts)}</div>
              <div className="row-actions">
                <button className="mini-btn primary" type="button">Reprocessar</button>
                <button className="mini-btn" type="button">Inspecionar</button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── Componente principal ─── */
/* ─── Seção: Campeonatos (provisionar + listar) ─── */
const EMPTY_FORM = {
  title: "",
  format: "3v3",
  numTeams: 6,
  numMatches: 3,
  prizeRp: 5000,
  startsAt: "",
  bannerTone: "b1",
  tag: "ABERTO",
};

function SectionTournaments() {
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [submitting, setSubmitting] = useState(false);
  const [created, setCreated] = useState<{ id: string; title: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const { data: list } = useApi(useCallback(() => api.tournaments(), []), [reload]);

  function set<K extends keyof typeof form>(k: K, v: (typeof form)[K]) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setErr(null);
    setCreated(null);
    try {
      const body: TournamentCreate = {
        title: form.title.trim(),
        format: form.format as "3v3" | "2v2",
        numTeams: Number(form.numTeams),
        numMatches: Number(form.numMatches),
        prizeRp: Number(form.prizeRp),
        bannerTone: form.bannerTone as "b1" | "b2" | "b3" | "b4",
        tag: form.tag.trim() || "ABERTO",
        ...(form.startsAt ? { startsAt: new Date(form.startsAt).toISOString() } : {}),
      };
      const t = await api.createTournament(body);
      setCreated({ id: t.id, title: t.title });
      setForm({ ...EMPTY_FORM });
      setReload((r) => r + 1);
    } catch (ex) {
      setErr((ex as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  const tournaments = list ?? [];

  return (
    <section className="a-sec" data-active="true">
      <div className="admin-h">
        <div>
          <h1>Campeonatos</h1>
          <div className="desc">Provisione um campeonato · gera chave, inscritos e classificação · publica em /campeonatos2</div>
        </div>
      </div>

      <div className="panel-2col">
        {/* Formulário de provisionamento */}
        <div className="card">
          <h3>Configurar campeonato</h3>
          <p className="hint">O backend provisiona o torneio (status “em breve”, classificação zerada) e o expõe na read-API.</p>
          <form className="tourn-form" onSubmit={submit}>
            <label className="tf-field tf-full">
              <span>Título</span>
              <input
                type="text"
                value={form.title}
                onChange={(e) => set("title", e.target.value)}
                placeholder="Copa ArenaRank #1"
                required
                minLength={2}
                maxLength={80}
              />
            </label>

            <label className="tf-field">
              <span>Formato</span>
              <select value={form.format} onChange={(e) => set("format", e.target.value)}>
                <option value="3v3">Trios (3v3)</option>
                <option value="2v2">Duos (2v2)</option>
              </select>
            </label>

            <label className="tf-field">
              <span>Equipes</span>
              <input type="number" min={2} max={16} value={form.numTeams}
                onChange={(e) => set("numTeams", Number(e.target.value))} />
            </label>

            <label className="tf-field">
              <span>Partidas</span>
              <input type="number" min={1} max={10} value={form.numMatches}
                onChange={(e) => set("numMatches", Number(e.target.value))} />
            </label>

            <label className="tf-field">
              <span>Premiação (RP)</span>
              <input type="number" min={0} step={500} value={form.prizeRp}
                onChange={(e) => set("prizeRp", Number(e.target.value))} />
            </label>

            <label className="tf-field">
              <span>Início</span>
              <input type="datetime-local" value={form.startsAt}
                onChange={(e) => set("startsAt", e.target.value)} />
            </label>

            <label className="tf-field">
              <span>Banner</span>
              <select value={form.bannerTone} onChange={(e) => set("bannerTone", e.target.value)}>
                <option value="b1">Azul</option>
                <option value="b2">Verde</option>
                <option value="b3">Roxo</option>
                <option value="b4">Ciano</option>
              </select>
            </label>

            <label className="tf-field">
              <span>Tag</span>
              <input type="text" maxLength={24} value={form.tag}
                onChange={(e) => set("tag", e.target.value)} placeholder="ABERTO" />
            </label>

            <div className="tf-actions tf-full">
              <button className="btn primary" type="submit" disabled={submitting}>
                <Mi name="add_circle" style={{ fontSize: 16, marginRight: 6 }} />
                {submitting ? "Provisionando…" : "Provisionar campeonato"}
              </button>
            </div>
          </form>

          {created && (
            <div className="tf-ok">
              <Mi name="check_circle" style={{ fontSize: 16, color: "var(--green)" }} />
              <span>
                <b>{created.title}</b> provisionado. <Link to={`/campeonatos2/${encodeURIComponent(created.id)}`}>Ver em /campeonatos2 →</Link>
                <small className="mono">{created.id}</small>
              </span>
            </div>
          )}
          {err && (
            <div className="tf-err">
              <Mi name="error" style={{ fontSize: 16 }} />
              {err}
            </div>
          )}
        </div>

        {/* Lista de provisionados */}
        <div className="card">
          <h3>Provisionados ({tournaments.length})</h3>
          <p className="hint">Torneios persistidos na read-API. Clique para abrir a prévia.</p>
          <div className="tourn-list">
            {tournaments.length === 0 && <div className="faint" style={{ fontSize: 13 }}>Nenhum ainda.</div>}
            {tournaments.map((t) => (
              <Link key={t.id} className="tourn-item" to={`/campeonatos2/${encodeURIComponent(t.id)}`}>
                <span className={`badge ${t.bannerTone === "b1" ? "tier-top50" : "neutral"}`}>{t.tag}</span>
                <div className="ti-main">
                  <div className="ti-title">{t.title}</div>
                  <div className="ti-sub">{t.format} · {t.teams} equipes · {t.amountLabel}</div>
                </div>
                <span className="ti-when">{t.whenLabel}</span>
                <Mi name="chevron_right" style={{ color: "var(--text-faint)" }} />
              </Link>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

type NavItem = { sec: SecId; label: string; icon: string; grp?: string; pill?: (d: AdminOverview) => number };

const NAV_ITEMS: NavItem[] = [
  { sec: "health",      label: "Saúde do Sistema",    icon: "monitoring",     grp: "Operação" },
  { sec: "seasons",     label: "Gestão de Temporada", icon: "calendar_month" },
  { sec: "tournaments", label: "Campeonatos",         icon: "emoji_events" },
  { sec: "integrity",   label: "Fila de Integridade", icon: "balance",        grp: "Moderação",
    pill: (d) => d.integrity.length },
  { sec: "players",   label: "Flags de Jogador",    icon: "flag" },
  { sec: "dlq",       label: "Revisão de DLQ",      icon: "report",
    pill: (d) => d.dlq.length },
];

export function Admin() {
  const [activeSec, setActiveSec] = useState<SecId>("health");
  const { data, loading, error } = useApi(useCallback(() => api.adminOverview(), []), []);

  return (
    <div className="shell">
      {/* Faixa admin */}
      <div className="admin-strip">
        <span>
          <Mi name="lock" style={{ fontSize: 15, verticalAlign: -3, marginRight: 5 }} />
          PAINEL ADMINISTRATIVO
        </span>
        <span className="role">ROLE: ADMIN</span>
        <span style={{ color: "var(--text-dim)", fontWeight: 500 }}>
          Autenticado via Google Workspace SSO + RBAC
        </span>
        <span className="who">admin@arenarank.gg</span>
      </div>

      <div className="admin-shell">
        {/* Navegação lateral */}
        <aside className="admin-nav">
          {NAV_ITEMS.map((item, i) => {
            const prevGrp = i > 0 ? NAV_ITEMS[i - 1].grp ?? "" : "";
            const showGrp = item.grp && item.grp !== prevGrp;
            const pillCount = data && item.pill ? item.pill(data) : 0;
            return (
              <div key={item.sec}>
                {showGrp && <div className="grp-lbl">{item.grp}</div>}
                <a
                  data-active={activeSec === item.sec ? "true" : "false"}
                  onClick={() => setActiveSec(item.sec)}
                >
                  <span className="ic">
                    <Mi name={item.icon} />
                  </span>
                  {item.label}
                  {pillCount > 0 && <span className="pill">{pillCount}</span>}
                </a>
              </div>
            );
          })}
        </aside>

        {/* Conteúdo principal */}
        <main className="admin-main">
          <StateBlock loading={loading} error={error}>
            {data && (
              <>
                {/* Cada seção é montada mas exibida via CSS data-active */}
                <div data-active={activeSec === "health" ? "true" : "false"} className="a-sec">
                  <SectionHealth data={data} />
                </div>
                <div data-active={activeSec === "seasons" ? "true" : "false"} className="a-sec">
                  <SectionSeasons data={data} />
                </div>
                <div data-active={activeSec === "tournaments" ? "true" : "false"} className="a-sec">
                  <SectionTournaments />
                </div>
                <div data-active={activeSec === "integrity" ? "true" : "false"} className="a-sec">
                  <SectionIntegrity data={data} />
                </div>
                <div data-active={activeSec === "players" ? "true" : "false"} className="a-sec">
                  <SectionPlayers data={data} />
                </div>
                <div data-active={activeSec === "dlq" ? "true" : "false"} className="a-sec">
                  <SectionDlq data={data} />
                </div>
              </>
            )}
          </StateBlock>
        </main>
      </div>
    </div>
  );
}
