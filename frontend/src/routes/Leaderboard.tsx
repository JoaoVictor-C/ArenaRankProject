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
import { PlayerTagChip } from "../components/Badges";
import { PlayerAvatar, ChampIcon } from "../components/Avatar";
import { StateBlock } from "../components/StateBlock";
import { FreshnessBadge } from "../components/FreshnessBadge";
import { Mi } from "../components/Mi";
import { api } from "../lib/api";
import type {
  AvatarColors,
  LeaderboardChampion,
  LeaderboardRow,
  LeaderboardResponse,
  RecordsResponse,
  PlayerTag,
  SearchPlayer,
} from "../lib/types";
import { useApi } from "../hooks/useApi";
import { seedFrom, type SnapshotFile } from "../lib/snapshot";
import snapshotLeaderboard from "../generated/snapshot.leaderboard.json";

// Semente congelada no build (página 1 + recordes): primeira visita pinta a
// tabela sem esperar a API, e revalida em seguida (ver lib/snapshot).
const SNAP = snapshotLeaderboard as SnapshotFile;
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
  // Tons derivados SÓ do deep (--pc1) do ícone — a mesma cor-base das tags de
  // campeão. Sem bright (--pc2) nem #fff no wash: os dois clareiam sob o
  // mix-blend screen e estouram o contraste do texto branco (bright dava ~2.4:1).
  // Um único matiz do ícone, escurecido em graus → card lê como a cor do ícone
  // e o texto branco (com text-shadow) passa AA. bright fica só p/ bordas/frame.
  const tones = [
    "var(--pc1)",
    "color-mix(in srgb, var(--pc1) 78%, #000)",
    "color-mix(in srgb, var(--pc1) 60%, #000)",
    "var(--pc1)",
    "color-mix(in srgb, var(--pc1) 70%, #000)",
    "color-mix(in srgb, var(--pc1) 85%, #000)",
    "color-mix(in srgb, var(--pc1) 66%, #000)",
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
      <i className="pod-aura" />
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
        <PlayerTagChip key={i} tag={t} />
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
                <PlayerTagChip key={i} tag={t} />
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
  // O efeito interno (.pod-fx + .pod-aura) reflete o CAMPEÃO MAIS JOGADO do
  // jogador: extrai a cor dominante do ícone ddragon do main (championIconUrls[0],
  // busiest-first) com a mesma conversão das tags. Fallbacks: ícone de invocador
  // → gradiente do avatar (enquanto carrega ou se a extração falhar).
  const champIcon = row.championIconUrls?.[0] ?? row.profileIconUrl;
  const iconColors = useIconColors(champIcon);
  const pc1 = iconColors?.[0] ?? row.avatar.c1;
  const pc2 = iconColors?.[1] ?? row.avatar.c2;
  return (
    <Link
      to={`/perfil/${encodeURIComponent(row.riotId)}`}
      className="pod"
      style={
        {
          ["--pc1" as string]: pc1,
          ["--pc2" as string]: pc2,
          textDecoration: "none",
          color: "inherit",
          cursor: "pointer",
        } as CSSProperties
      }
    >
      <PodiumFx seed={pos} />

      {/* topo: avatar + nome + rank */}
      <div className="pod-top">
        <PlayerAvatar colors={{ c1: pc1, c2: pc2 }} url={row.profileIconUrl} alt={row.name} size={50} />
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
    </Link>
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
  const { data } = useApi(() => api.records(), [], seedFrom<RecordsResponse>(SNAP, "records"));
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
            <ChampIcon
              colors={r.avatar}
              url={r.profileIconUrl ?? undefined}
              alt={r.name}
              size="sm"
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
/* Rail: SEASON I — card premium da temporada. Status ao vivo + datas, e   */
/* a VAQUINHA da premiação: barra de arrecadação + botão Doar (vermelho    */
/* urgência) → seletor de valor (presets/personalizado) → checkout PIX     */
/* InfinitePay (redirect; iframe é bloqueado). Datas em BRT (-03:00).      */
/* Arrecadação viva (tabela + webhook) chega na fatia 2 — por ora o pote   */
/* base é exibido; a UI de doação já é real.                               */
/* ------------------------------------------------------------------ */

// Temporada inaugural: partidas passaram a contar 19/07 06:00 (BRT, exibido fixo
// no card); encerra 19/08 06:00 (BRT) — usado no countdown.
const SEASON_END = new Date("2026-08-19T06:00:00-03:00").getTime();

// Vaquinha: pote base (o que já foi colocado) e a meta. Em centavos.
const PRIZE_BASE_CENTS = 2_800; // R$ 28 (pote inicial)
const PRIZE_GOAL_CENTS = 100_000; // R$ 1.000 (meta)
const DONATION_PRESETS = [2, 5, 10, 15, 20]; // reais

const brl0 = (cents: number) =>
  (cents / 100).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    maximumFractionDigits: 0,
  });

/* ------------------------------------------------------------------ */
/* Poro mascote do card SEASON I. SVG rigado offline (scripts/rig-poro.mjs) */
/* em grupos #poro-arm / #poro-foot-l/r / #poro-lids. Injetado inline p/ o  */
/* CSS animar as partes (img não expõe o DOM interno). Máquina de estados: */
/* idle (acena+pisca) → fall (no scroll) → rise → exit (sai pela direita)  */
/* → gone → return (volta) → idle. Reduced-motion: estático, sem queda.    */
/* ------------------------------------------------------------------ */

/* Camadas do PSD (scripts/poro-layers/manifest.json, canvas 1024×1021),
   posicionadas em % (o webp em public/assets/poro/ é 0.4x; % independe da
   resolução). Braços são MARIONETE FK: a mesma imagem fatiada por clip-path
   em segmentos sobrepostos (a sobreposição some no pelo), cada um dentro de
   um pivô aninhado — ombro→cotovelo→punho(garras) — p/ follow-through real. */
const PORO_W = 1024;
const PORO_H = 1021;
const PORO_DIR = "/assets/poro/";

function poroBox(b: [number, number, number, number]) {
  return {
    left: `${((b[0] / PORO_W) * 100).toFixed(2)}%`,
    top: `${((b[1] / PORO_H) * 100).toFixed(2)}%`,
    width: `${(((b[2] - b[0]) / PORO_W) * 100).toFixed(2)}%`,
    height: `${(((b[3] - b[1]) / PORO_H) * 100).toFixed(2)}%`,
  };
}

function PoroBody() {
  const img = (slug: string, cls: string, b: [number, number, number, number]) => (
    <img className={`pr ${cls}`} style={poroBox(b)} src={`${PORO_DIR}${slug}.webp`} alt="" draggable={false} />
  );
  return (
    <div className="sc-poro-fig">
      {img("chifre-esquerdo", "", [244, 261, 444, 414])}
      {img("chifre-direito", "", [637, 264, 837, 417])}
      {img("tronco", "", [202, 303, 787, 1021])}
      {img("camada-2", "pr-foot-l", [344, 804, 507, 896])}
      {img("camada-1", "pr-foot-r", [601, 795, 737, 896])}
      {img("cinturao", "", [331, 733, 760, 825])}
      {img("olho-esquerdo", "pr-eye", [395, 387, 458, 441])}
      {img("olho-direito", "pr-eye", [582, 370, 650, 428])}

      {/* braço esquerdo (baixo): ombro → punho */}
      <div className="pr pj pj-l-sh" style={poroBox([193, 596, 361, 733])}>
        <img className="pj-seg pj-l-upper" src={`${PORO_DIR}braco-esquerdo.webp`} alt="" draggable={false} />
        <div className="pj pj-l-wr">
          <img className="pj-seg pj-l-paw" src={`${PORO_DIR}braco-esquerdo.webp`} alt="" draggable={false} />
        </div>
      </div>

      {/* braço direito (erguido, acena): ombro → cotovelo → punho c/ garras */}
      <div className="pr pj pj-r-sh" style={poroBox([724, 480, 875, 698])}>
        <img className="pj-seg pj-r-upper" src={`${PORO_DIR}braco-direito.webp`} alt="" draggable={false} />
        <div className="pj pj-r-el">
          <img className="pj-seg pj-r-fore" src={`${PORO_DIR}braco-direito.webp`} alt="" draggable={false} />
          <div className="pj pj-r-wr">
            <img className="pj-seg pj-r-paw" src={`${PORO_DIR}braco-direito.webp`} alt="" draggable={false} />
          </div>
        </div>
      </div>

      {/* coroa com inércia própria (salta na queda) */}
      <div className="pr pj pj-crown" style={poroBox([380, 116, 690, 337])}>
        <img className="pj-seg pj-full" src={`${PORO_DIR}coroa.webp`} alt="" draggable={false} />
      </div>
    </div>
  );
}

type PoroState = "idle" | "fall" | "downed" | "refall" | "rise" | "exit" | "gone" | "return";

function SeasonPoro() {
  const [st, setSt] = useState<PoroState>("idle");
  const stageRef = useRef<HTMLDivElement>(null);
  const visibleRef = useRef(false);
  const lastY = useRef(0);
  const reduced = useRef(false);

  // Visibilidade do palco (só cai se o card está na tela).
  useEffect(() => {
    const el = stageRef.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([e]) => {
      visibleRef.current = e.isIntersecting;
    });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  // Scroll da página derruba o poro (uma vez por ciclo; reduced-motion pula).
  useEffect(() => {
    reduced.current =
      typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced.current) return;
    lastY.current = window.scrollY;
    function onScroll() {
      const dy = Math.abs(window.scrollY - lastY.current);
      if (dy > 60) lastY.current = window.scrollY;
      if (dy <= 60 || !visibleRef.current) return;
      // idle → cai; caído se levantando → tomba de novo (re-knock)
      setSt((cur) => (cur === "idle" ? "fall" : cur === "downed" ? "refall" : cur));
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Avanço da máquina por fim de animação + retorno agendado.
  useEffect(() => {
    if (st === "gone") {
      const t = window.setTimeout(() => setSt("return"), 9000);
      return () => window.clearTimeout(t);
    }
    return undefined;
  }, [st]);

  function onAnimEnd(e: { animationName: string }) {
    // queda → luta pra levantar (downed, 2s); scroll no meio → refall → downed de novo
    if (e.animationName === "poro-fall") setSt("downed");
    else if (e.animationName === "poro-downed") setSt("rise");
    else if (e.animationName === "poro-refall") setSt("downed");
    else if (e.animationName === "poro-rise") window.setTimeout(() => setSt("exit"), 320);
    else if (e.animationName === "poro-exit") setSt("gone");
    else if (e.animationName === "poro-return") setSt("idle");
  }

  return (
    <div className="sc-poro-wrap" aria-hidden="true">
      {/* poça de sombra circular — vive FORA do palco (não é clipada), some
          radialmente e passa atrás dos spans de doação abaixo */}
      <div className="sc-poro-ground" />
      <div className="sc-poro-stage" ref={stageRef} data-state={st}>
        <div className="sc-poro-mover" onAnimationEnd={onAnimEnd}>
          {/* sombra de estúdio: o MESMO rig, achatado/enviesado atrás no ciclorama */}
          <div className="sc-poro-cast">
            <PoroBody />
          </div>
          <PoroBody />
        </div>
      </div>
    </div>
  );
}

function SeasonCard() {
  const [now, setNow] = useState(() => Date.now());
  const [picking, setPicking] = useState(false);
  const [sel, setSel] = useState<number | null>(null);
  const [custom, setCustom] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [thanks, setThanks] = useState(false);
  const customRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(t);
  }, []);

  // Volta do checkout com ?doacao=ok → agradece (sem afirmar pagamento confirmado;
  // a confirmação por webhook é fatia 2).
  useEffect(() => {
    try {
      if (new URLSearchParams(window.location.search).get("doacao") === "ok") setThanks(true);
    } catch {
      /* SSR/URL indisponível */
    }
  }, []);

  const remaining = SEASON_END - now;
  const ended = remaining <= 0;
  const days = Math.max(0, Math.floor(remaining / 86_400_000));
  const hours = Math.max(0, Math.floor((remaining % 86_400_000) / 3_600_000));

  const raised = PRIZE_BASE_CENTS;
  const fund = Math.min(1, raised / PRIZE_GOAL_CENTS);

  const amount = custom.trim() !== "" ? Number(custom.replace(",", ".")) : sel;
  const valid = amount != null && Number.isFinite(amount) && amount >= 1 && amount <= 1000;

  async function donate() {
    if (!valid || loading) return;
    setLoading(true);
    setErr(null);
    try {
      const res = await api.createDonation(Math.round((amount as number) * 100));
      // Redirect para a página hospedada do InfinitePay (iframe é bloqueado).
      window.location.href = res.checkoutUrl;
    } catch (e) {
      setErr(e instanceof Error && e.message ? e.message : "Não foi possível abrir o pagamento. Tente de novo.");
      setLoading(false);
    }
  }

  return (
    <div className="rail-card season-card">
      <div className="sc-name">
        SEASON <span className="sc-num">I</span>
      </div>
      <p className="sc-dates">
        Começou <b>19 jul, 06h</b> ·{" "}
        {ended ? (
          "temporada encerrada"
        ) : (
          <>
            termina em <b className="tnum">{days}d {hours}h</b>
          </>
        )}
      </p>

      <div className="sc-prize">
        <div className="sc-prize-head">
          <span className="sc-ph-label">
            <span className="mi fill" aria-hidden="true">
              emoji_events
            </span>
            Premiação total
          </span>
          <span className="sc-toptag">Top 3 melhores</span>
        </div>
        <div className="sc-prize-val">
          <span className="sc-cur">R$</span>
          <span className="sc-fig tnum">
            {(raised / 100).toLocaleString("pt-BR", { maximumFractionDigits: 0 })}
          </span>
        </div>

        <div
          className="sc-fund"
          role="progressbar"
          aria-valuenow={Math.round(fund * 100)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Vaquinha da premiação"
        >
          <span style={{ width: `${fund * 100}%` }} />
        </div>
        <div className="sc-fund-meta">
          <span>arrecadado</span>
          <span className="tnum">meta {brl0(PRIZE_GOAL_CENTS)}</span>
        </div>

        <p className="sc-appeal">
          Ajude a manter a comunidade ativa e engajada dando suporte à premiação!
        </p>

        <SeasonPoro />

        {thanks && (
          <div className="sc-thanks" role="status">
            <span className="mi fill" aria-hidden="true">
              favorite
            </span>
            Obrigado por apoiar a premiação!
          </div>
        )}

        {!picking ? (
          <button className="sc-donate" type="button" onClick={() => setPicking(true)}>
            <span className="mi fill" aria-hidden="true">
              volunteer_activism
            </span>
            Doar para a premiação
          </button>
        ) : (
          <div className="sc-picker">
            <div className="sc-amts">
              {DONATION_PRESETS.map((v) => (
                <button
                  key={v}
                  type="button"
                  className={`sc-amt${custom.trim() === "" && sel === v ? " on" : ""}`}
                  onClick={() => {
                    setSel(v);
                    setCustom("");
                    setErr(null);
                  }}
                >
                  R$ {v}
                </button>
              ))}
            </div>
            <label className="sc-custom" data-on={custom.trim() !== "" ? "true" : "false"}>
              <span>R$</span>
              <input
                ref={customRef}
                type="number"
                inputMode="decimal"
                min={1}
                max={1000}
                step={1}
                placeholder="outro valor"
                value={custom}
                onChange={(e) => {
                  setCustom(e.target.value);
                  setSel(null);
                  setErr(null);
                }}
              />
            </label>

            {err && (
              <div className="sc-err" role="alert">
                {err}
              </div>
            )}

            <div className="sc-picker-actions">
              <button className="sc-cancel" type="button" onClick={() => setPicking(false)}>
                Cancelar
              </button>
              <button
                className="sc-donate"
                type="button"
                disabled={!valid || loading}
                onClick={donate}
              >
                {loading
                  ? "Abrindo…"
                  : valid
                    ? `Contribuir ${brl0(Math.round((amount as number) * 100))}`
                    : "Escolha um valor"}
              </button>
            </div>
          </div>
        )}

        <p className="sc-fine">
          100% da doação vai para o Top 1, 2 e 3 na proporção 50/30/20 — descontada apenas a taxa
          da InfinitePay que processa o pagamento.
        </p>
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
  // Escopo fixo em "global": os filtros Escopo/Ordenar foram removidos da UI
  // (ocupavam espaço sem função clara). O leaderboard sempre lista por CR global.
  const scope: Scope = "global";
  const [format] = useState<Format>("3v3");
  const [season] = useState(3);
  const [page, setPage] = useState(0);
  const [softLock] = useState(false); // poderia vir de API/season info
  const navigate = useNavigate();

  const offset = page * PAGE_SIZE;
  const { data, loading, error, retry, refreshing, updatedAt } = useApi(
    () => api.leaderboard({ format, scope, season, limit: PAGE_SIZE, offset }),
    [format, scope, season, page],
    // A semente é da página 1: aplicá-la em qualquer outra pintaria a página
    // errada. Fora da primeira página, sem semente.
    page === 0 ? seedFrom<LeaderboardResponse>(SNAP, "page1") : {},
  );

  // Sempre listado por CR (Escopo/Ordenar removidos da UI): pódio = Top 3, tabela = resto.
  const allRows = data?.rows ?? [];
  const podiumRows = allRows.slice(0, 3);
  const tableRows = allRows.slice(3);
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
          <Link className="lb-otp-entry" to="/campeoes">
            <Mi name="workspace_premium" />
            OTPs por campeão
            <Mi name="arrow_forward" />
          </Link>
        </div>
        {/* A tabela pode ter vindo da semente de build (até 24h) ou do cache
            em disco: é aqui que o jogador confere a posição, então a idade
            precisa estar à vista. */}
        {data && (
          <FreshnessBadge updatedAt={updatedAt} refreshing={refreshing} onRefresh={retry} />
        )}
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

            {/* busca (Escopo/Ordenar removidos — sem função clara, ocupavam espaço) */}
            <div className="lb-filters">
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
          <SeasonCard />
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
