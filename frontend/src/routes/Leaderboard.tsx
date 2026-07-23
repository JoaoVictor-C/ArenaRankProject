/* ============================================================
   ArenaRank — Leaderboard Global
   Porta fiel do design em _design_staging/.../Leaderboard.html + leaderboard.js
   ============================================================ */
import "./Leaderboard.css";
import {
  useState,
  useEffect,
  useRef,
  useMemo,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { Mi } from "../components/Mi";
import { PlayerAvatar, ChampIcon } from "../components/Avatar";
import { StateBlock } from "../components/StateBlock";
import { api } from "../lib/api";
import type {
  AvatarColors,
  LeaderboardChampion,
  LeaderboardRow,
  PlayerTag,
  SearchPlayer,
} from "../lib/types";
import { useApi } from "../hooks/useApi";
import { useIconColors } from "../hooks/useIconColors";
import { Link, useNavigate, type NavigateFunction } from "react-router-dom";
import { nf, pct, winrateBand } from "../lib/format";

/* ------------------------------------------------------------------ */
/* Busca global de jogadores ("Pular para jogador") — autocomplete     */
/* ------------------------------------------------------------------ */

/** Tier → rótulo curto PT-BR exibido no resultado da busca. */
const TIER_LABEL: Record<SearchPlayer["tier"], string> = {
  top1: "#1",
  top10: "Top 10",
  top50: "Top 50",
  top100: "Top 100",
  top500: "Top 500",
  none: "",
};

/**
 * Campo de busca global com dropdown de resultados. Diferente do filtro local
 * antigo (que só varria as 50 linhas da página atual), este consulta
 * `GET /players/search` e encontra QUALQUER jogador da temporada ativa.
 *
 * UX: digita (debounce ~250ms, mín. 2 chars) → dropdown sob o input;
 * clique navega para /perfil/{riotId}; Enter seleciona o 1º; Esc/blur fecha;
 * ↑/↓ percorrem os resultados.
 */
function PlayerSearch({
  format,
  navigate,
}: {
  format: Format;
  navigate: NavigateFunction;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchPlayer[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0); // índice destacado (teclado)
  const [loading, setLoading] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const blurTimer = useRef<number | undefined>(undefined);
  const reqId = useRef(0); // descarta respostas fora de ordem

  // Busca com debounce de 250ms; mínimo 2 caracteres.
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setResults([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const myId = ++reqId.current;
    const t = window.setTimeout(() => {
      api
        .searchPlayers({ q, format, limit: 8 })
        .then((rows) => {
          if (myId !== reqId.current) return; // resposta obsoleta
          setResults(rows);
          setActive(0);
          setOpen(true);
          setLoading(false);
        })
        .catch(() => {
          if (myId !== reqId.current) return;
          setResults([]);
          setLoading(false);
        });
    }, 250);
    return () => window.clearTimeout(t);
  }, [query, format]);

  // Fecha ao clicar fora.
  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  useEffect(() => () => window.clearTimeout(blurTimer.current), []);

  function go(p: SearchPlayer) {
    setOpen(false);
    setQuery("");
    setResults([]);
    navigate(`/perfil/${encodeURIComponent(p.riotId)}`);
  }

  function onKeyDown(e: ReactKeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      setOpen(false);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (results.length) {
        setOpen(true);
        setActive((i) => Math.min(results.length - 1, i + 1));
      }
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(0, i - 1));
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      // Seleciona o resultado destacado (ou o 1º). Sem resultados, mas com um
      // "Nome#TAG" digitado, abre o perfil direto por esse Riot ID.
      const pick = results[active] ?? results[0];
      if (pick) {
        go(pick);
      } else if (query.includes("#")) {
        navigate(`/perfil/${encodeURIComponent(query.trim())}`);
      }
    }
  }

  const showPanel = open && query.trim().length >= 2;

  return (
    <div className="lb-search" ref={boxRef}>
      <input
        type="text"
        placeholder="Pular para jogador (Nome#TAG)…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => {
          if (results.length) setOpen(true);
        }}
        onKeyDown={onKeyDown}
        role="combobox"
        aria-expanded={showPanel}
        aria-autocomplete="list"
        aria-controls="lb-search-list"
      />
      {showPanel && (
        <div className="lb-search-pop" id="lb-search-list" role="listbox">
          {results.length === 0 ? (
            <div className="lb-search-empty">
              {loading ? "Buscando…" : "Nenhum jogador encontrado"}
            </div>
          ) : (
            results.map((p, i) => (
              <button
                key={p.riotId}
                type="button"
                className={`lb-search-item${i === active ? " is-active" : ""}`}
                role="option"
                aria-selected={i === active}
                onMouseEnter={() => setActive(i)}
                // mousedown (não click) p/ disparar antes do blur do input
                onMouseDown={(e) => {
                  e.preventDefault();
                  go(p);
                }}
              >
                <PlayerAvatar
                  colors={p.avatar}
                  url={p.profileIconUrl}
                  alt={p.name}
                  size={34}
                />
                <div className="lb-search-id">
                  <div className="nm">
                    {p.name} <span className="phandle">{p.handle}</span>
                  </div>
                  <div className="meta">
                    #{p.rank}
                    {TIER_LABEL[p.tier] ? ` · ${TIER_LABEL[p.tier]}` : ""}
                  </div>
                </div>
                <div className="lb-search-cr">
                  {nf(p.cr)}
                  <span className="unit">PDL</span>
                </div>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Helpers locais                                                        */
/* ------------------------------------------------------------------ */

/** Sheen SVG varrendo da direita para esquerda dentro do badge PDL. */
const SHEEN_SVG = (
  <svg
    className="sheen"
    viewBox="0 0 60 24"
    preserveAspectRatio="none"
    aria-hidden="true"
  >
    <polygon points="34,-4 46,-4 26,28 14,28" />
  </svg>
);

/** Gerador de blobs da lava-lamp com semente determinística por card.
 *  Usa Math.random() real — OK no browser, re-executa apenas ao montar. */
function buildFluidBlobs(seed: number): Array<{ style: CSSProperties }> {
  // LCG simples (mesma lógica do leaderboard.js original)
  let r = ((seed * 2654435761 + 40503) >>> 0) >>> 0;
  const rnd = () => {
    r = ((r * 1664525 + 1013904223) >>> 0) >>> 0;
    return r / 4294967296;
  };
  const tones = [
    "var(--pc2)",
    "color-mix(in srgb, var(--pc2) 72%, #fff)",
    "color-mix(in srgb, var(--pc1) 52%, var(--pc2))",
    "color-mix(in srgb, var(--pc2) 64%, #000)",
    "color-mix(in srgb, var(--pc1) 70%, #fff)",
    "var(--pc1)",
    "color-mix(in srgb, var(--pc2) 50%, var(--pc1))",
  ];
  const anims = ["ar-fl-a", "ar-fl-b", "ar-fl-c", "ar-fl-d"];
  const blobs: Array<{ style: CSSProperties }> = [];
  for (let k = 0; k < 7; k++) {
    const c = tones[k % tones.length];
    const x = (10 + rnd() * 80).toFixed(0) + "%";
    const y = (8 + rnd() * 84).toFixed(0) + "%";
    const sz = (44 + rnd() * 26).toFixed(0) + "%";
    const anim = anims[Math.floor(rnd() * 4)];
    const d = (17 + rnd() * 16).toFixed(1) + "s";
    const dl = (-rnd() * 24).toFixed(1) + "s";
    blobs.push({
      style: {
        ["--c" as string]: c,
        ["--x" as string]: x,
        ["--y" as string]: y,
        ["--sz" as string]: sz,
        ["--anim" as string]: anim,
        ["--d" as string]: d,
        ["--dl" as string]: dl,
      } as CSSProperties,
    });
  }
  return blobs;
}

/** Camada lava-lamp do card do pódio (7 blobs com cores do avatar). */
function PodiumFx({ seed }: { seed: number }) {
  // useMemo p/ blobs não mudarem num re-render (mas mantidos constantes por seed)
  const blobs = useMemo(() => buildFluidBlobs(seed), [seed]);
  return (
    <div className="pod-fx" aria-hidden="true">
      {blobs.map((b, i) => (
        <b key={i} style={b.style} />
      ))}
    </div>
  );
}

/** Tags em linha (máx `max` visíveis + "+N" se houver mais). */
function TagRow({
  tags,
  max = 2,
}: {
  tags: PlayerTag[];
  max?: number;
}) {
  const [open, setOpen] = useState(false);
  const shown = tags.slice(0, max);
  const rest = tags.slice(max);
  return (
    <>
      {shown.map((t, i) => (
        <span key={i} className={`ptag ptag-${t.kind}`}>
          <Mi name={t.icon} />
          {t.label}
        </span>
      ))}
      {rest.length > 0 && (
        <span
          className="ptag-more"
          style={{ position: "relative", cursor: "default" }}
          onMouseEnter={() => setOpen(true)}
          onMouseLeave={() => setOpen(false)}
          onClick={(e) => e.preventDefault()}
        >
          +{rest.length}
          {open && (
            <span
              style={{
                position: "absolute",
                bottom: "calc(100% + 6px)",
                left: 0,
                zIndex: 60,
                display: "flex",
                flexDirection: "column",
                gap: 4,
                padding: 8,
                background: "var(--surface-2, #191c24)",
                border: "1px solid var(--border, #2a2f3a)",
                borderRadius: 8,
                boxShadow: "0 8px 24px rgba(0,0,0,.45)",
                whiteSpace: "nowrap",
              }}
            >
              {rest.map((t, i) => (
                <span key={i} className={`ptag ptag-${t.kind}`}>
                  <Mi name={t.icon} />
                  {t.label}
                </span>
              ))}
            </span>
          )}
        </span>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Campeão do pódio com card de stats no hover                           */
/* ------------------------------------------------------------------ */

function ChampHover({
  colors,
  url,
  stat,
}: {
  colors: AvatarColors;
  url?: string;
  stat?: LeaderboardChampion;
}) {
  const [open, setOpen] = useState(false);
  // Sem stats (jogador sem jogos elegíveis com o campeão) → só o ícone.
  if (!stat) return <ChampIcon colors={colors} url={url} />;
  return (
    <span
      className="champ-hover"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <ChampIcon colors={colors} url={url} alt={stat.name} />
      {open && (
        <span className="champ-pop" role="tooltip">
          <span className="cp-head">
            <ChampIcon colors={colors} url={url} alt={stat.name} size="sm" />
            <span className="cp-name">{stat.name}</span>
          </span>
          <span className="cp-grid">
            <span className="cp-row">
              <span className="cp-k">Partidas</span>
              <span className="cp-v">{nf(stat.games)}</span>
            </span>
            <span className="cp-row">
              <span className="cp-k">Winrate</span>
              <span className="cp-v">{pct(stat.winrate)}</span>
            </span>
            <span className="cp-row">
              <span className="cp-k">Top-half</span>
              <span className="cp-v">{pct(stat.topHalf)}</span>
            </span>
            <span className="cp-row">
              <span className="cp-k">Coloc. média</span>
              <span className="cp-v">{stat.avgPlace.toFixed(1)}</span>
            </span>
          </span>
        </span>
      )}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Pódio (Top 3)                                                         */
/* ------------------------------------------------------------------ */

function PodiumCard({
  row,
  pos,
}: {
  row: LeaderboardRow;
  pos: 1 | 2 | 3;
}) {
  const band = winrateBand(row.winrate);
  const d7Up = row.delta7d >= 0;
  // O efeito interno (.pod-fx) varia conforme o ÍCONE DE INVOCADOR: extrai a cor
  // dominante do ícone ddragon; cai no gradiente do avatar enquanto carrega ou
  // se a extração falhar.
  const iconColors = useIconColors(row.profileIconUrl);
  const pc1 = iconColors?.[0] ?? row.avatar.c1;
  const pc2 = iconColors?.[1] ?? row.avatar.c2;
  return (
    <div
      className="pod"
      style={
        {
          ["--pc1" as string]: pc1,
          ["--pc2" as string]: pc2,
        } as CSSProperties
      }
    >
      <PodiumFx seed={pos} />

      {/* topo: avatar + nome + rank */}
      <div className="pod-top">
        <PlayerAvatar colors={row.avatar} url={row.profileIconUrl} alt={row.name} size={50} />
        <div className="pod-id">
          <div className="nm">{row.name}</div>
          <div className="phandle">{row.handle}</div>
        </div>
        <span className={`pod-rank m${pos}`}>#{pos}</span>
      </div>

      {/* tags */}
      <div className="tagrow">
        <TagRow tags={row.tags} max={2} />
        {row.inGame && (
          <span className="pod-ingame">
            <span className="pulse" />
            Em partida
          </span>
        )}
      </div>

      {/* CR + PDL badge */}
      <div className="pod-cr-block">
        <div className="v">
          <span>{nf(row.cr)}</span>
          <span className="punit">
            PDL
            {SHEEN_SVG}
          </span>
        </div>
        <div className="wl">
          {row.wins}V – {row.losses}D
        </div>
      </div>

      {/* campeões mains (hover → card de stats do jogador com o campeão) */}
      <div className="pod-champs">
        {row.champions.slice(0, 4).map((c, i) => (
          <ChampHover
            key={i}
            colors={c}
            url={row.championIconUrls?.[i] ?? undefined}
            stat={row.championsStats?.[i]}
          />
        ))}
      </div>

      {/* rodapé: delta + winrate */}
      <div className="pod-foot">
        <div className="pf-item">
          <span className={`pod-delta ${d7Up ? "up" : "down"}`}>
            {d7Up ? "+" : "−"}
            {nf(Math.abs(row.delta7d))}
          </span>
          <span className="cap">Últimos 7 dias</span>
        </div>
        <div className="pf-item right">
          <span className={`pod-wr ${band}`}>{pct(row.winrate)}</span>
          <span className="cap">Winrate</span>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Linha da tabela                                                       */
/* ------------------------------------------------------------------ */

function LbRow({ row, isYou = false }: { row: LeaderboardRow; isYou?: boolean }) {
  const band = winrateBand(row.winrate);
  const d7 = row.delta7d;
  const d7Class = d7 > 0 ? "up" : d7 < 0 ? "down" : "flat";
  const d7Label =
    d7 !== 0
      ? `${d7 > 0 ? "+" : "−"}${nf(Math.abs(d7))}`
      : "—";
  // "On fire": 3+ vitórias seguidas em 1º (placement==1) a partir da última
  // partida → a linha INTEIRA da tabela ganha o fundo quente animado + o chip 🔥.
  // (NÃO afeta os cards do pódio 1/2/3 — só as linhas da `.tbl`.)
  const onFire = (row.top1Streak ?? 0) >= 3;

  return (
    <Link
      to={`/perfil/${encodeURIComponent(row.riotId)}`}
      className={`row${isYou ? " lb-row-you" : ""}${onFire ? " on-fire" : ""}`}
      style={{ textDecoration: "none", color: "inherit", cursor: "pointer" }}
    >
      {/* # rank */}
      <div className="lb-rank">{row.rank}</div>

      {/* Jogador */}
      <div className="lb-player">
        <PlayerAvatar colors={row.avatar} url={row.profileIconUrl} alt={row.name} size={42} />
        <div className="info">
          <div className="nm">
            {isYou && "▸ "}
            {row.name}{" "}
            <span className="phandle">{row.handle}</span>
            {onFire && (
              <span
                className="fire-chip"
                title={`${row.top1Streak} vitórias seguidas em 1º lugar`}
              >
                🔥 {row.top1Streak}
              </span>
            )}
          </div>
          <div className="tagrow">
            <TagRow tags={row.tags} max={2} />
          </div>
        </div>
      </div>

      {/* Pontos (CR) + delta */}
      <div className="lb-cr-cell">
        <div className="lb-cr">
          {nf(row.cr)}
          <span className="unit">PDL</span>
        </div>
        <span className={`lb-d7 ${d7Class}`}>{d7Label}</span>
      </div>

      {/* Partidas: V-D + winrate badge */}
      <div className="lb-record">
        <span className="rec">
          {row.wins}
          <em>V</em> – {row.losses}
          <em>D</em>
        </span>
        <span className={`lb-wr ${band}`}>{pct(row.winrate)}</span>
      </div>

      {/* Top 4 */}
      <div className="lb-top4">{pct(row.top4)}</div>
    </Link>
  );
}

/* ------------------------------------------------------------------ */
/* Rail: Recordes ao vivo (estatísticas rotativas) — porta fiel do       */
/* leaderboard.js do design (dados de destaque mockados por enquanto).   */
/* ------------------------------------------------------------------ */

const REC_DUR = 3800;

function LiveRecordsCard() {
  // Recordes reais da temporada (/meta/records), rotativos.
  const { data } = useApi(() => api.records(), []);
  const records = data?.records ?? [];
  const [idx, setIdx] = useState(0);
  const dotsRef = useRef<(HTMLElement | null)[]>([]);

  useEffect(() => {
    if (records.length === 0) return;
    const t = setInterval(() => setIdx((i) => (i + 1) % records.length), REC_DUR);
    return () => clearInterval(t);
  }, [records.length]);

  // Barras de progresso: concluídas cheias, a atual "carrega" em REC_DUR, futuras vazias.
  useEffect(() => {
    dotsRef.current.forEach((b, di) => {
      if (!b) return;
      if (di < idx) {
        b.style.transition = "none";
        b.style.width = "100%";
      } else if (di === idx) {
        b.style.transition = "none";
        b.style.width = "0%";
        void b.offsetWidth;
        b.style.transition = `width ${REC_DUR}ms linear`;
        b.style.width = "100%";
      } else {
        b.style.transition = "none";
        b.style.width = "0%";
      }
    });
  }, [idx, records.length]);

  // Sem recordes ainda (temporada recém-começada) → não renderiza o card.
  if (records.length === 0) return null;
  const r = records[Math.min(idx, records.length - 1)];

  return (
    <div className="rail-card" id="liveRecords">
      <h3>Recordes ao vivo</h3>
      <p className="note">
        <span className="live">
          <span className="pulse" />
          Atualizando
        </span>{" "}
        · destaques da temporada
      </p>
      <div className="rec" id="recStage">
        {/* key={idx} força remontagem → a animação de entrada (rec-in) toca a cada troca */}
        <div className="rec-item" key={idx}>
          <div className="rec-val" style={{ color: r.accent }}>
            {r.value}
          </div>
          <div className="rec-label">{r.label}</div>
          <div className="rec-who">
            <span
              className="ch-icon sm"
              style={{ "--c1": r.avatar.c1, "--c2": r.avatar.c2 } as CSSProperties}
            />
            {r.name} <span>{r.handle}</span>
          </div>
        </div>
      </div>
      <div className="rec-dots" id="recDots">
        {records.map((_, i) => (
          <i key={i}>
            <b
              ref={(el) => {
                dotsRef.current[i] = el;
              }}
            />
          </i>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Rail: Atividade da temporada — barras renderizadas no React (usa as    */
/* classes .ar-chart/.ar-col do anim.css). Auto-contido: não depende do   */
/* animEngine encontrar o elemento (que não roda em rotas lazy). O        */
/* data-static faz o engine ignorar este chart (não sobrescrever o React).*/
/* ------------------------------------------------------------------ */

function ActivityChart() {
  // Partidas ranqueadas processadas por dia — dados reais (/meta/activity).
  const { data } = useApi(() => api.activity({ days: 14 }), []);
  const days = data?.days ?? [];
  const max = data?.max || 1;
  return (
    <div className="rail-card">
      <h3>Atividade da temporada</h3>
      <p className="note" style={{ marginBottom: 14 }}>
        Partidas ranqueadas processadas por dia
      </p>
      <div className="ar-chart ar-shown" data-static="1">
        {days.map((d, i) => {
          const pct = Math.max(4, Math.round((d.count / max) * 100));
          return (
            <div className={"ar-col" + (d.count === max ? " hi" : "")} key={i}>
              <div className="ar-bar-track">
                <div className="ar-bar" style={{ height: `${pct}%` }}>
                  <span className="ar-val">{d.count.toLocaleString("pt-BR")}</span>
                </div>
              </div>
              <div className="ar-xlbl">{d.label}</div>
            </div>
          );
        })}
        {days.length === 0 && (
          <div style={{ opacity: 0.6, padding: 12, fontSize: 13 }}>Sem dados ainda.</div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Componente principal                                                   */
/* ------------------------------------------------------------------ */

type Scope = "global" | "br" | "friends";
type Format = "3v3" | "2v2";
// Season data (kept for future archive selector)
// const SEASONS = [
//   { n: 3, label: "Temporada 3", status: "active" },
//   { n: 2, label: "Temporada 2", status: "ended" },
//   { n: 1, label: "Temporada 1", status: "ended" },
// ];
const PAGE_SIZE = 50;

export function Leaderboard() {
  const [scope, setScope] = useState<Scope>("global");
  const [format] = useState<Format>("3v3");
  const [season] = useState(3);
  const [page, setPage] = useState(0);
  const [softLock] = useState(false); // poderia vir de API/season info
  const navigate = useNavigate();

  const offset = page * PAGE_SIZE;
  const { data, loading, error } = useApi(
    () => api.leaderboard({ format, scope, season, limit: PAGE_SIZE, offset }),
    [format, scope, season, page],
  );

  // Ordenação da página (client-side sobre as 50 linhas da página atual).
  // "cr" mantém o pódio Top 3; os demais critérios viram tabela plana ordenada.
  const [sortBy, setSortBy] = useState<"cr" | "games" | "top1" | "top3">("cr");
  const allRows = data?.rows ?? [];
  const sortedRows =
    sortBy === "cr"
      ? allRows
      : [...allRows].sort((a, b) => {
          const key = (r: LeaderboardRow) =>
            sortBy === "games" ? r.wins + r.losses : sortBy === "top1" ? r.top1 : r.winrate;
          return key(b) - key(a);
        });
  const podiumRows = sortBy === "cr" ? sortedRows.slice(0, 3) : [];
  const tableRows = sortBy === "cr" ? sortedRows.slice(3) : sortedRows;
  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 1;

  // paginação visível (máx 5 páginas + setas)
  const visiblePages = useMemo(() => {
    const total = totalPages;
    if (total <= 7) return Array.from({ length: total }, (_, i) => i);
    // slide window ao redor da página atual
    const start = Math.max(0, Math.min(page - 2, total - 5));
    return Array.from({ length: 5 }, (_, i) => start + i);
  }, [page, totalPages]);

  return (
    <div className={`shell lb-page${softLock ? " lb-page--lock" : ""}`} data-lock={softLock ? "on" : "off"}>
      <div className="breadcrumb">
        <a href="/">Início</a>
        <span className="sep">›</span>
        <span>Leaderboard Global</span>
      </div>

      {/* cabeçalho + seletor de temporada */}
      <div className="lb-top">
        <div className="lb-title">
          <h1>Leaderboard Global</h1>
          <div className="sub">
            Ranking por <b>Casual Rating (CR)</b> · Arena{" "}
            {format === "3v3" ? "Trios" : "Duos"} ·{" "}
            {data ? nf(data.total) : "…"} jogadores ranqueados nesta temporada
          </div>
        </div>
      </div>

      {/* layout 2 colunas: conteúdo + rail direito */}
      <div className="lb-layout">
        {/* coluna principal */}
        <div>
          <StateBlock loading={loading} error={error} empty={!loading && !error && !data}>
            {/* pódio top 3 */}
            {podiumRows.length >= 3 && (
              <div className="podium">
                {(podiumRows.slice(0, 3) as [LeaderboardRow, LeaderboardRow, LeaderboardRow]).map(
                  (r, i) => (
                    <PodiumCard
                      key={r.riotId}
                      row={r}
                      pos={(i + 1) as 1 | 2 | 3}
                    />
                  ),
                )}
              </div>
            )}

            {/* filtros */}
            <div className="lb-filters">
              <div className="grp">
                <span className="lbl">Escopo</span>
                <div className="chips">
                  {(["global", "br"] as Scope[]).map((s) => (
                    <div
                      key={s}
                      className="chip"
                      data-active={scope === s ? "true" : "false"}
                      onClick={() => { setScope(s); setPage(0); }}
                    >
                      {s === "global" ? "Global" : "Brasil"}
                    </div>
                  ))}
                </div>
              </div>
              <div className="grp">
                <span className="lbl">Ordenar</span>
                <div className="chips">
                  {([
                    ["cr", "Padrão"],
                    ["games", "Partidas"],
                    ["top1", "Top 1"],
                    ["top3", "Top 3"],
                  ] as const).map(([k, lbl]) => (
                    <div
                      key={k}
                      className="chip"
                      data-active={sortBy === k ? "true" : "false"}
                      onClick={() => setSortBy(k)}
                    >
                      {lbl}
                    </div>
                  ))}
                </div>
              </div>
              <PlayerSearch format={format} navigate={navigate} />
            </div>

            {/* tabela */}
            <div style={{ marginTop: 2 }}>
              <div className="tbl lb-table">
                <div className="head">
                  <div>#</div>
                  <div>Jogador</div>
                  <div>Pontos</div>
                  <div>Partidas</div>
                  <div className="lb-top4">Top 4</div>
                </div>
                {tableRows.map((r) => (
                  <LbRow key={r.riotId} row={r} />
                ))}
              </div>
            </div>

            {/* paginação */}
            <div className="pager">
              <button
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
              >
                ‹
              </button>
              {visiblePages.map((p) => (
                <button
                  key={p}
                  data-active={page === p ? "true" : "false"}
                  onClick={() => setPage(p)}
                >
                  {p + 1}
                </button>
              ))}
              {totalPages > 7 && <button disabled>…</button>}
              {totalPages > 7 && (
                <button onClick={() => setPage(totalPages - 1)}>
                  {totalPages}
                </button>
              )}
              <button
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
              >
                ›
              </button>
            </div>

            <p className="lb-note">
              Tabela virtualizada · paginação de 50 em 50 · atualização do Top
              1000 em menos de 5 minutos via faixa de processamento prioritário.
            </p>
          </StateBlock>
        </div>

        {/* rail direito (fiel ao Leaderboard.html do design) */}
        <aside className="rail">
          <LiveRecordsCard />
          <ActivityChart />
          <div className="rail-card sponsor">
            <h3 style={{ marginBottom: 12 }}>Temporada patrocinada</h3>
            <div className="logo-slot">SEU LOGO AQUI</div>
            <p className="note" style={{ margin: 0 }}>
              Marcas do ecossistema gamer podem patrocinar temporadas — com selo
              de marca no leaderboard e na badge da temporada.
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}
