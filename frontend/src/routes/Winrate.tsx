/* ============================================================
   Winrate.tsx — Central de Campeões (/campeoes · aba CAMPEÕES)
   Recriação do mock "Champ Winrate" (mundo handoff): board de 3
   colunas — DETALHE do campeão selecionado (esq.) · tabela
   sortável de CAMPEÕES com chips de classe + delta 7d (centro) ·
   rail teal de AUGMENTS em alta + TOP SINERGY em trio (dir.).
   Tudo dado real (champions/mains/build/topBuild/synergyGroups),
   exceto o laboratório explícito de dev em `?mock=1`.
   ============================================================ */
import { useState, useMemo, useEffect, useRef, type CSSProperties, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import "./Winrate.css";
import { StateBlock, PlayerAvatar, Mi, ParticleField, BuildHoverIcon, type BuildHoverData } from "../components";
import { useApi } from "../hooks/useApi";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { isWinrateMockOn, winrateApi } from "./winrateMock";
import type {
  ChampTierlistResponse,
  ChampRow,
  ChampionSynergyGroup,
  ChampTopPlayer,
  BuildEntry,
  BuildTeammate,
} from "../lib/types";
import { nf } from "../lib/format";
import {
  STATE_SPINNER_LOOP,
  useFlipList,
  useGsapEntrance,
  useGsapInteractions,
  useGsapLoop,
  useGsapSwap,
  type EntranceStep,
  type InteractionMotion,
  type LoopMotion,
} from "../lib/motion";

/* ── Ordenação por coluna ─────────────────────────────────────── */
type SortKey = "winrate" | "first" | "avgplace" | "pick" | "games";
type SortState = { key: SortKey; asc: boolean };
const DEFAULT_ASC: Record<SortKey, boolean> = {
  winrate: false,
  first: false,
  avgplace: true, // colocação menor é melhor
  pick: false,
  games: false,
};

/* ── Formatadores pt-BR ───────────────────────────────────────── */
const pctInt = (n: number) => `${Math.round(n)}%`;
const fmtPlace = (n: number) => n.toFixed(2).replace(".", ",");
const fmtPick = (n: number) => n.toFixed(1).replace(".", ",") + "%";
const fmtDelta = (n: number) => (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(n).toFixed(1).replace(".", ",");

/** Normaliza tier ("S+" → "splus") p/ o data-attr de cor. */
const tierKey = (t: string) => t.toLowerCase().replace("+", "plus");

const PAGE_SIZE = 8;

/* ── Classes (chips) — filtro por role real do backend ───────── */
const CLASSES = ["Todos", "Mago", "Tanque", "Lutador", "Suporte", "Atirador", "Assassino"] as const;

/* ── Arte real do campeão (ddragon) sobre gradiente fallback ──── */
const ART_STYLE: CSSProperties = {
  position: "absolute",
  inset: 0,
  width: "100%",
  height: "100%",
  objectFit: "cover",
  borderRadius: "inherit",
};
function ChampArt({ url, alt }: { url?: string | null; alt: string }) {
  const [failed, setFailed] = useState(false);
  if (!url || failed) return null;
  return <img src={url} alt={alt} loading="lazy" draggable={false} style={ART_STYLE} onError={() => setFailed(true)} />;
}
function ChampFace({
  colors,
  url,
  alt,
  size,
  tier,
}: {
  colors: { c1: string; c2: string };
  url?: string | null;
  alt: string;
  size: "sm" | "md" | "lg" | "xl";
  tier?: string;
}) {
  return (
    <span
      className={`wr-face wr-face-${size}${tier ? ` t-${tierKey(tier)}` : ""}`}
      style={{ "--c1": colors.c1, "--c2": colors.c2 } as CSSProperties}
      aria-hidden="true"
    >
      <ChampArt url={url} alt={alt} />
    </span>
  );
}

/* ── Ícone de build (item/augment) ────────────────────────────── */
function BuildIcon({ url, kind }: { url?: string | null; kind: "item" | "augment" }) {
  const [failed, setFailed] = useState(false);
  return (
    <span className={`wr-bi wr-bi-${kind}`} aria-hidden="true">
      {url && !failed && <img src={url} alt="" loading="lazy" draggable={false} onError={() => setFailed(true)} />}
    </span>
  );
}

/** CDragon segue par _small/_large por nome. */
function largeAugUrl(url?: string | null): string | null {
  return url ? url.replace("_small.png", "_large.png") : null;
}

/** Arte grande do augment. */
function AugArt({ url, alt }: { url?: string | null; alt: string }) {
  const large = largeAugUrl(url);
  const [failedLarge, setFailedLarge] = useState(false);
  const src = failedLarge ? url : large;
  if (!src) return <span className="wr-aug-art" aria-hidden="true" />;
  return (
    <span className="wr-aug-art" aria-hidden="true">
      <img src={src} alt={alt} loading="lazy" draggable={false} onError={() => setFailedLarge(true)} />
    </span>
  );
}

/** `BuildEntry` -> dados do popup de hover (`BuildHoverIcon`). */
function buildHoverData(e: BuildEntry): BuildHoverData {
  return {
    name: e.name,
    iconUrl: e.iconUrl,
    badge: e.tier,
    badgeClassName: `tier-${tierKey(e.tier)}`,
    stats: [
      { label: "Escolha", value: fmtPick(e.pickRate) },
      { label: "1º lugar", value: pctInt(e.top1) },
      { label: "Top 4", value: pctInt(e.top4) },
      { label: "Col. média", value: fmtPlace(e.avgPlace) },
      { label: "Partidas", value: nf(e.games) },
    ],
  };
}

function teammateHint(e: BuildTeammate) {
  return `1º ${e.top1}% · winrate ${e.top4}% · col. média ${fmtPlace(e.avgPlace)} · escolha ${fmtPick(e.pickRate)} · ${nf(e.games)} jogos`;
}

/* ── Chip de main (jogador → /perfil) ─────────────────────────── */
function PlayerRef({ p, tabbable = true }: { p: ChampTopPlayer; tabbable?: boolean }) {
  const inner = (
    <>
      <PlayerAvatar colors={p.avatar} url={p.profileIconUrl ?? undefined} alt={p.name} size={30} />
      <span className="wr-ref-id">
        <span className="wr-ref-name">{p.name}</span>
      </span>
      <span className="wr-ref-wr tnum" title="Winrate (top-half) no campeão">
        {pctInt(p.winrate)}
      </span>
    </>
  );
  if (!p.handle) return <span className="wr-ref">{inner}</span>;
  return (
    <Link
      to={`/perfil/${encodeURIComponent(`${p.name}${p.handle}`)}`}
      className="wr-ref wr-ref-link"
      tabIndex={tabbable ? undefined : -1}
      onClick={(e) => e.stopPropagation()}
      aria-label={`Perfil de ${p.name}`}
    >
      {inner}
    </Link>
  );
}

/* ────────────────────────────────────────────────────────────── */
/* Build categorizada (agregado global do patch, placement-derived) */
/* ────────────────────────────────────────────────────────────── */
function BuildStrip({ title, entries, kind, max }: { title: string; entries: BuildEntry[]; kind: "item" | "augment"; max: number }) {
  if (entries.length === 0) return null;
  return (
    <div className="wr-bstrip">
      <span className="wr-bstrip-h">{title}</span>
      <div className="wr-bstrip-row">
        {entries.slice(0, max).map((e) => (
          <BuildHoverIcon className="wr-bchip" key={e.id} data={buildHoverData(e)}>
            <BuildIcon url={e.iconUrl} kind={kind} />
            <span className={`wr-tier wr-tier-sm t-${tierKey(e.tier)}`}>{e.tier}</span>
          </BuildHoverIcon>
        ))}
      </div>
    </div>
  );
}
function BuildTeammateStrip({ entries, max }: { entries: BuildTeammate[]; max: number }) {
  if (entries.length === 0) return null;
  return (
    <div className="wr-bstrip">
      <span className="wr-bstrip-h">Parceiros</span>
      <div className="wr-bstrip-row">
        {entries.slice(0, max).map((e) => (
          <span className="wr-bchip" key={e.championId} title={`${e.name} — ${teammateHint(e)}`}>
            <ChampFace colors={e.colors} url={e.championIconUrl} alt={e.name} size="sm" />
            <span className={`wr-tier wr-tier-sm t-${tierKey(e.tier)}`}>{e.tier}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function BuildBlock({ championId, championName }: { championId: number; championName: string }) {
  const mockMode = isWinrateMockOn();
  const { data, loading, error, retry } = useApi(
    () => winrateApi.championBuild(championId),
    [championId, mockMode],
  );
  const has = !!data && data.games > 0;
  return (
    <div className="wr-block">
      <div className="wr-block-h wr-build-h">
        <span className="wr-block-h-l">
          <Mi name="construction" />
          Build recomendada
        </span>
        <Link
          to={`/campeao/${championId}`}
          className="wr-build-expand"
          aria-label={`Abrir build completa de ${championName}`}
          title="Build completa, augments e sinergias"
        >
          <span>Expandir</span>
          <Mi name="arrow_forward" />
        </Link>
      </div>
      {error ? (
        <p className="wr-empty-sm">
          Não deu para carregar a build.{" "}
          <button type="button" className="wr-retry-sm" onClick={retry}>
            Tentar de novo
          </button>
        </p>
      ) : loading ? (
        <p className="wr-empty-sm">Carregando build…</p>
      ) : has && data ? (
        <>
          <p className="wr-build-meta">
            Patch {data.patch || "atual"} · <span className="tnum">{nf(data.games)}</span> partidas · winrate{" "}
            <span className="tnum">{pctInt(data.top4)}</span>
          </p>
          <div className="wr-bstrips">
            <BuildStrip title="Prismático" entries={data.augments.prismatic} kind="augment" max={4} />
            <BuildStrip title="Ouro" entries={data.augments.gold} kind="augment" max={4} />
            <BuildStrip title="Prata" entries={data.augments.silver} kind="augment" max={4} />
            <BuildStrip title="Itens" entries={data.items} kind="item" max={6} />
            <BuildStrip title="Botas" entries={data.boots} kind="item" max={3} />
            <BuildTeammateStrip entries={data.teammates} max={4} />
          </div>
          <p className="wr-build-note">
            Força de item e augment = tier · mín. {data.minGames} jogos por escolha. Agregado global, não é a
            ladder BR.
          </p>
        </>
      ) : (
        <p className="wr-empty-sm">Sem dados de referência para {championName} neste patch ainda.</p>
      )}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────── */
/* Coluna esquerda — DETALHE do campeão selecionado                 */
/* ────────────────────────────────────────────────────────────── */
function ChampionDetail({ row }: { row: ChampRow }) {
  const mockMode = isWinrateMockOn();
  const { data: mains } = useApi(
    () => winrateApi.championMains(row.championId, { limit: 5 }),
    [row.championId, mockMode],
  );
  const d = row.winrateDelta;
  const dcls = d > 0 ? "up" : d < 0 ? "dn" : "flat";

  return (
    <div className="wr-detail-inner">
      {/* Hero do campeão selecionado */}
      <div className="wr-hero" data-t={tierKey(row.tier)}>
        <ChampFace colors={row.champion} url={row.championIconUrl} alt={row.name} size="xl" tier={row.tier} />
        <div className="wr-hero-id">
          <div className="wr-hero-role">{row.role || "Arena"}</div>
          <h2 className="wr-hero-name">{row.name}</h2>
          <div className="wr-hero-sub tnum">
            #{row.rank} · {nf(row.games)} partidas
          </div>
        </div>
        <div className="wr-hero-tier" data-t={tierKey(row.tier)}>
          <b>{row.tier}</b>
          <span>TIER</span>
        </div>
      </div>

      {/* 4 stats reais */}
      <div className="wr-hero-stats">
        <div className="wr-hs">
          <div className="wr-hs-v tnum">
            {pctInt(row.top4)}
            {d !== 0 && (
              <span className={`wr-hs-delta ${dcls}`} title="Variação 7d">
                <Mi name={d > 0 ? "arrow_drop_up" : "arrow_drop_down"} />
                {fmtDelta(d)}
              </span>
            )}
          </div>
          <div className="wr-hs-l">Winrate</div>
        </div>
        <div className="wr-hs">
          <div className="wr-hs-v tnum gold">{pctInt(row.first)}</div>
          <div className="wr-hs-l">1º Lugar</div>
        </div>
        <div className="wr-hs">
          <div className="wr-hs-v tnum">{fmtPlace(row.avgPlace)}</div>
          <div className="wr-hs-l">Col. média</div>
        </div>
        <div className="wr-hs">
          <div className="wr-hs-v tnum">{fmtPick(row.pickRate)}</div>
          <div className="wr-hs-l">Escolha</div>
        </div>
      </div>

      {/* Mains de referência */}
      <div className="wr-block">
        <div className="wr-block-h">
          <Mi name="military_tech" />
          Mains de referência
        </div>
        {mains && mains.players.length > 0 ? (
          <div className="wr-mains">
            {mains.players.map((p, i) => (
              <div className="wr-main-row" key={p.handle + i}>
                <span className={`wr-main-pos tnum${i === 0 ? " gold" : ""}`}>{i + 1}</span>
                <PlayerRef p={p} />
                <span className="wr-main-games tnum">{nf(p.games)} jogos</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="wr-empty-sm">Sem partidas suficientes neste campeão ainda.</p>
        )}
      </div>

      {/* Build categorizada */}
      <BuildBlock championId={row.championId} championName={row.name} />
    </div>
  );
}

/* ────────────────────────────────────────────────────────────── */
/* Rail direito — AUGMENTS em alta + TOP SINERGY (trio)             */
/* ────────────────────────────────────────────────────────────── */
function FeaturedAug({ e, rank }: { e: BuildEntry; rank: number }) {
  const prism = rank === 0; // o top vira moldura prismática
  const inner = (
    <>
      {/* Fundo: a MESMA arte grande do primeiro plano, coberta e rebaixada. A _small
          (~64px) esticada para os 96px da camada sairia borrada. */}
      <div className="wr-fcard-art" aria-hidden="true">
        {largeAugUrl(e.iconUrl) && (
          <img
            className="wr-fcard-art-image"
            src={largeAugUrl(e.iconUrl) ?? undefined}
            alt=""
            loading="lazy"
            draggable={false}
          />
        )}
      </div>
      <AugArt url={e.iconUrl} alt="" />
      <span className="wr-fcard-shade" />
      <span className={`wr-fcard-tb t-${tierKey(e.tier)}`}>{e.tier}</span>
      <div className="wr-fcard-cap">
        <div className="wr-fcard-nm">{e.name}</div>
        <div className="wr-fcard-wr tnum">
          {fmtPick(e.pickRate)}
          <sub>ESCOLHA</sub>
        </div>
      </div>
    </>
  );
  return prism ? (
    <BuildHoverIcon as="article" className="wr-fcard prism" data={buildHoverData(e)}>
      <div className="wr-fcard-inner">{inner}</div>
    </BuildHoverIcon>
  ) : (
    <BuildHoverIcon as="article" className="wr-fcard" data={buildHoverData(e)}>
      {inner}
    </BuildHoverIcon>
  );
}

function AugmentsRail() {
  const mockMode = isWinrateMockOn();
  const top = useApi(() => winrateApi.topBuild(), [mockMode]);
  const syn = useApi(
    () => winrateApi.championSynergyGroups({ size: 3, limit: 4 }),
    [mockMode],
  );
  const t = top.data;
  const hasTop = !!t && t.games > 0;

  return (
    <div className="wr-rail">
      {/* Augments em alta */}
      <section aria-labelledby="wr-aug-h">
        <div className="wr-rail-h">
          <Mi name="auto_awesome" />
          <h2 id="wr-aug-h">Augments em alta</h2>
          <span className="wr-rail-s">Meta{t?.patch ? ` ${t.patch}` : ""}</span>
        </div>
        {top.error ? (
          <p className="wr-empty-sm">
            Não deu para carregar o top do patch.{" "}
            <button type="button" className="wr-retry-sm" onClick={top.retry}>
              Tentar de novo
            </button>
          </p>
        ) : top.loading ? (
          <p className="wr-empty-sm">Carregando meta…</p>
        ) : hasTop && t ? (
          <>
            <div className="wr-feat">
              {t.augments.slice(0, 3).map((e, i) => (
                <FeaturedAug key={e.id} e={e} rank={i} />
              ))}
            </div>
            {t.augments.length > 3 && (
              <>
                <div className="wr-rail-h wr-rail-h-sub">
                  <Mi name="grid_view" />
                  <h2>Pick rate · Augments</h2>
                </div>
                <div className="wr-agrid">
                  {t.augments.slice(3, 17).map((e) => (
                  <BuildHoverIcon
                    className={`wr-acell t-${tierKey(e.tier)}`}
                    key={e.id}
                    data={buildHoverData(e)}
                  >
                      <span className="wr-atile" data-t={tierKey(e.tier)}>
                        <BuildIcon url={e.iconUrl} kind="augment" />
                        <span className="wr-atile-b">{e.tier}</span>
                      </span>
                      <span className="wr-acell-pr tnum">{fmtPick(e.pickRate)}</span>
                    </BuildHoverIcon>
                  ))}
                </div>
              </>
            )}
          </>
        ) : (
          <p className="wr-empty-sm">Sem dados de meta neste patch ainda.</p>
        )}
      </section>

      {/* Top sinergias — trios */}
      <section aria-labelledby="wr-syn-h">
        <div className="wr-rail-h wr-rail-h-sub">
          <Mi name="diversity_2" />
          <h2 id="wr-syn-h">Top sinergias</h2>
          <span className="wr-rail-s">Trios · taxa de top 4</span>
        </div>
        {syn.error ? (
          <p className="wr-empty-sm">
            Não deu para carregar as sinergias.{" "}
            <button type="button" className="wr-retry-sm" onClick={syn.retry}>
              Tentar de novo
            </button>
          </p>
        ) : syn.loading ? (
          <p className="wr-empty-sm">Carregando comps…</p>
        ) : syn.data && syn.data.groups.length > 0 ? (
          <div className="wr-synlist">
            {syn.data.groups.map((g, i) => (
              <TrioRow key={i} g={g} />
            ))}
            <Link to="/sinergias" className="wr-synmore">
              Ver comps
              <Mi name="arrow_forward" />
            </Link>
          </div>
        ) : (
          <p className="wr-empty-sm">Sem trios com partidas suficientes ainda.</p>
        )}
      </section>
    </div>
  );
}

function TrioRow({ g }: { g: ChampionSynergyGroup }) {
  const names = g.champions.map((c) => c.name).join(" · ");
  return (
    <article className="wr-synrow" title={names} aria-label={names}>
      <div className="wr-syntrio">
        {g.champions.map((c) => (
          <ChampFace key={c.championId} colors={c.colors} url={c.championIconUrl} alt={c.name} size="sm" />
        ))}
      </div>
      <div className="wr-synmeta">
        <div className="wr-synmeta-nm">{names}</div>
        <div className="wr-synmeta-tag tnum">
          {nf(g.games)} partidas · col. média {fmtPlace(g.avgPlace)}
        </div>
      </div>
      <div className="wr-synpct">
        <b className="tnum">{pctInt(g.winRate)}</b>
        <span>TOP 4</span>
      </div>
    </article>
  );
}

/* ────────────────────────────────────────────────────────────── */
/* Página                                                          */
/* ────────────────────────────────────────────────────────────── */
const COLS: { key: SortKey; label: string; hint: string }[] = [
  { key: "avgplace", label: "Col. média", hint: "Colocação média (menor é melhor)" },
  { key: "winrate", label: "Winrate", hint: "Taxa de top-half (vitória no Arena)" },
  { key: "pick", label: "Escolha", hint: "Taxa de escolha" },
  { key: "games", label: "Jogos", hint: "Partidas amostradas" },
];

const WINRATE_ENTRANCE: EntranceStep[] = [
  {
    selector: ".wr-col-table",
    from: {
      opacity: 0,
      y: 18,
      clipPath: "inset(0 0 12% 0 round 12px)",
      filter: "blur(5px)",
    },
    duration: 0.58,
    clearProps: "opacity,transform,clipPath,filter",
  },
  {
    selector: ".wr-col-detail",
    from: { opacity: 0, x: -28 },
    duration: 0.48,
    position: "-=0.3",
  },
  {
    selector: ".wr-col-rail",
    from: { opacity: 0, x: 28 },
    duration: 0.48,
    position: "<0.06",
  },
];

const WINRATE_INTERACTIONS: InteractionMotion[] = [
  { trigger: ".wr-row:not(.wr-thead)", to: { y: -1 } },
  { trigger: ".wr-row:not(.wr-thead)", target: ".wr-face", to: { scale: 1.05 } },
  { trigger: ".wr-synrow", to: { y: -2 } },
  { trigger: ".wr-build-expand", target: ".mi", to: { x: 3 } },
  { trigger: ".wr-synmore", target: ".mi", to: { x: 3 } },
  { trigger: ".wr-pager-btn", to: { scale: 1.04 } },
];

const WINRATE_LOOPS: LoopMotion[] = [STATE_SPINNER_LOOP];

export function Winrate() {
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<string>("Todos");
  const [sort, setSort] = useState<SortState>({ key: "winrate", asc: false });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [page, setPage] = useState(0);
  const narrow = useMediaQuery("(max-width: 1080px)");
  const [sheetOpen, setSheetOpen] = useState(false);
  const sheetCloseRef = useRef<HTMLButtonElement | null>(null);
  const sheetRef = useRef<HTMLDivElement | null>(null);

  const select = (championId: number) => {
    setSelectedId(championId);
    setSheetOpen(true); // só afeta o layout estreito
  };
  const closeSheet = () => {
    setSheetOpen(false);
    document.querySelector<HTMLElement>(".wr-row.sel")?.focus();
  };

  const mockMode = isWinrateMockOn();
  const { data, loading, error, retry } = useApi<ChampTierlistResponse>(
    () => winrateApi.champions({ format: "3v3", metric: "top4" }),
    [mockMode],
  );

  const cell = (c: ChampRow, k: SortKey): number =>
    k === "winrate" ? c.top4 : k === "first" ? c.first : k === "avgplace" ? c.avgPlace : k === "pick" ? c.pickRate : c.games;

  const rows = useMemo(() => {
    if (!data) return [];
    const q = search.trim().toLowerCase();
    const list = data.table.filter(
      (c) => (roleFilter === "Todos" || c.role === roleFilter) && (!q || c.name.toLowerCase().includes(q)),
    );
    return [...list].sort((a, b) => {
      const d = cell(a, sort.key) - cell(b, sort.key);
      return sort.asc ? d : -d;
    });
  }, [data, search, roleFilter, sort]);

  /* Ordenar/filtrar move cada linha da posição antiga para a nova, em vez
     de a tabela piscar — dá para seguir um campeão com os olhos. */
  const pageRef = useRef<HTMLDivElement>(null);
  useGsapEntrance(pageRef, { steps: WINRATE_ENTRANCE, deps: [Boolean(data)] });
  const rowFlip = useFlipList(
    pageRef,
    ".wr-row:not(.wr-thead)",
    `${sort.key}|${sort.asc}|${roleFilter}|${search}|${page}`,
  );
  useGsapSwap(pageRef, ".wr-detail-inner", selectedId, {
    from: { opacity: 0, x: selectedId == null ? 0 : 12 },
  });
  useGsapInteractions(pageRef, WINRATE_INTERACTIONS);
  useGsapLoop(pageRef, WINRATE_LOOPS, [Boolean(data)]);

  const toggleSort = (key: SortKey) => {
    rowFlip.capture();
    setPage(0);
    setSort((s) => (s.key === key ? { key, asc: !s.asc } : { key, asc: DEFAULT_ASC[key] }));
  };

  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const safePage = Math.min(page, pages - 1);
  const visible = useMemo(() => rows.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE), [rows, safePage]);
  const rangeStart = rows.length ? safePage * PAGE_SIZE + 1 : 0;
  const rangeEnd = Math.min((safePage + 1) * PAGE_SIZE, rows.length);

  // Roving tabindex: a tabela é UM tab stop; setas movem, Enter/Espaço seleciona.
  const tabbableId =
    selectedId != null && visible.some((c) => c.championId === selectedId) ? selectedId : visible[0]?.championId;

  const onRowKeyDown = (e: KeyboardEvent<HTMLDivElement>, championId: number) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      select(championId);
      return;
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Home" && e.key !== "End") return;
    e.preventDefault();
    const row = e.currentTarget;
    const all = Array.from(row.parentElement?.querySelectorAll<HTMLElement>(".wr-row:not(.wr-thead)") ?? []);
    const i = all.indexOf(row);
    const next =
      e.key === "ArrowDown" ? all[i + 1] : e.key === "ArrowUp" ? all[i - 1] : e.key === "Home" ? all[0] : all[all.length - 1];
    next?.focus();
  };

  // Seleciona o líder por winrate quando os dados chegam.
  useEffect(() => {
    if (selectedId == null && data && data.table.length) {
      const lead = [...data.table].sort((a, b) => b.top4 - a.top4)[0];
      setSelectedId(lead.championId);
    }
  }, [data, selectedId]);

  const selected = useMemo(() => data?.table.find((c) => c.championId === selectedId) ?? null, [data, selectedId]);

  const sheetVisible = narrow && sheetOpen && selected != null;
  useGsapSwap(pageRef, ".wr-sheet", sheetVisible, {
    from: { opacity: 0, y: 56 },
    duration: 0.32,
  });

  // Sheet: foco no fechar, Esc fecha, Tab preso, corpo trava scroll.
  useEffect(() => {
    if (!sheetVisible) return;
    sheetCloseRef.current?.focus();
    document.body.style.overflow = "hidden";
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        closeSheet();
        return;
      }
      if (e.key !== "Tab") return;
      const sheet = sheetRef.current;
      if (!sheet) return;
      const f = sheet.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input, [tabindex]:not([tabindex="-1"])');
      if (f.length === 0) return;
      const first = f[0];
      const last = f[f.length - 1];
      const active = document.activeElement;
      if (!sheet.contains(active)) {
        e.preventDefault();
        first.focus();
      } else if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [sheetVisible]);

  return (
    <div className="wr-page" ref={pageRef} data-gsap-scope>
      <div className="wr-amb" aria-hidden="true" />
      <ParticleField variant="route" />

      <div className="wr-board">
        {/* ESQUERDA — detalhe do selecionado (desktop) */}
        {!narrow && (
          <aside className="wr-col-detail" aria-label="Detalhe do campeão selecionado">
            <div className="wr-panel wr-side">
              {selected ? (
                <ChampionDetail row={selected} />
              ) : (
                <div className="wr-detail-empty">Selecione um campeão para ver o detalhe.</div>
              )}
            </div>
          </aside>
        )}

        {/* CENTRO — tabela */}
        <section className="wr-col-table" aria-label="Ranking de campeões">
          <div className="wr-toolbar">
            <h1 className="wr-title">
              Campeões <span>· Arena</span>
            </h1>
            <div className="wr-search">
              <Mi name="search" />
              <input
                type="text"
                placeholder="Procurar campeão…"
                aria-label="Procurar campeão"
                value={search}
                onChange={(e) => {
                  rowFlip.capture();
                  setPage(0);
                  setSearch(e.target.value);
                }}
              />
            </div>
          </div>

          <div className="wr-chips-row">
            <div className="wr-chips" role="group" aria-label="Classe">
              {CLASSES.map((k) => (
                <button
                  key={k}
                  type="button"
                  className={roleFilter === k ? "on" : ""}
                  aria-pressed={roleFilter === k}
                  onClick={() => {
                    rowFlip.capture();
                    setPage(0);
                    setRoleFilter(k);
                  }}
                >
                  {k}
                </button>
              ))}
            </div>
            {data && (
              <span className="wr-patch tnum">
                Patch {data.patch || "atual"} · {data.region.toUpperCase()} · {nf(data.sampleSize)} escolhas de campeão
              </span>
            )}
          </div>

          <StateBlock loading={loading} error={error} onRetry={retry}>
            {data && (
              <div className="wr-tbl">
                <div className="wr-row wr-thead" role="row">
                  <div className="wr-c-rank" role="columnheader">
                    #
                  </div>
                  <div className="wr-c-champ" role="columnheader">
                    Campeão
                  </div>
                  <div className="wr-c-tier" role="columnheader">
                    Tier
                  </div>
                  {COLS.map((col) => {
                    const on = sort.key === col.key;
                    return (
                      <div
                        key={col.key}
                        className={`wr-c-num${col.key === "games" ? " end" : ""}`}
                        role="columnheader"
                        aria-sort={on ? (sort.asc ? "ascending" : "descending") : "none"}
                      >
                        <button
                          type="button"
                          className={`wr-sort${on ? " on" : ""}`}
                          onClick={() => toggleSort(col.key)}
                          title={col.hint}
                          aria-label={`Ordenar por ${col.label}`}
                        >
                          {col.label}
                          <Mi name={on ? (sort.asc ? "arrow_drop_up" : "arrow_drop_down") : "unfold_more"} />
                        </button>
                      </div>
                    );
                  })}
                </div>

                <div className="wr-rows-body" role="rowgroup" key={safePage}>
                  {visible.map((c) => {
                    const d = c.winrateDelta;
                    const dcls = d > 0 ? "up" : d < 0 ? "dn" : "flat";
                    return (
                      <div
                        key={c.championId}
                        className={`wr-row${c.championId === selectedId ? " sel" : ""}`}
                        role="row"
                        tabIndex={c.championId === tabbableId ? 0 : -1}
                        aria-current={c.championId === selectedId ? "true" : undefined}
                        onClick={() => select(c.championId)}
                        onKeyDown={(e) => onRowKeyDown(e, c.championId)}
                      >
                        <div className="wr-c-rank tnum" role="cell">
                          {c.rank}
                        </div>
                        <div className="wr-c-champ" role="cell">
                          <ChampFace colors={c.champion} url={c.championIconUrl} alt={c.name} size="md" tier={c.tier} />
                          <span className="wr-champ-meta">
                            <Link
                              to={`/campeao/${c.championId}`}
                              className="wr-champ-name"
                              onClick={(e) => e.stopPropagation()}
                            >
                              {c.name}
                            </Link>
                            <span className="wr-champ-role">{c.role}</span>
                          </span>
                        </div>
                        <div className="wr-c-tier" role="cell">
                          <span className={`wr-tier t-${tierKey(c.tier)}`}>{c.tier}</span>
                        </div>
                        <div className="wr-c-num tnum" role="cell">
                          {fmtPlace(c.avgPlace)}
                        </div>
                        <div className="wr-c-num" role="cell">
                          <span className="wr-wr">
                            <b className="tnum">{pctInt(c.top4)}</b>
                            {d !== 0 && (
                              <small className={`tnum ${dcls}`}>
                                <Mi name={d > 0 ? "arrow_drop_up" : "arrow_drop_down"} />
                                {fmtDelta(d)}
                              </small>
                            )}
                          </span>
                        </div>
                        <div className="wr-c-num tnum" role="cell">
                          {fmtPick(c.pickRate)}
                        </div>
                        <div className="wr-c-num end tnum" role="cell">
                          {nf(c.games)}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {pages > 1 && (
                  <nav className="wr-pager" aria-label="Paginação dos campeões">
                    <button
                      type="button"
                      className="wr-pager-btn"
                      onClick={() => {
                        rowFlip.capture();
                        setPage((current) => Math.max(0, current - 1));
                      }}
                      disabled={safePage === 0}
                      aria-label="Campeões anteriores"
                    >
                      <Mi name="arrow_back" />
                    </button>
                    <span className="wr-pager-range tnum" aria-live="polite">
                      {rangeStart}–{rangeEnd} de {rows.length}
                    </span>
                    <button
                      type="button"
                      className="wr-pager-btn"
                      onClick={() => {
                        rowFlip.capture();
                        setPage((current) => Math.min(pages - 1, current + 1));
                      }}
                      disabled={safePage === pages - 1}
                      aria-label="Próximos campeões"
                    >
                      <Mi name="arrow_forward" />
                    </button>
                  </nav>
                )}
                {rows.length === 0 && <p className="wr-empty">Nenhum campeão encontrado.</p>}
              </div>
            )}
          </StateBlock>
        </section>

        {/* DIREITA — rail de augments + sinergia */}
        <aside className="wr-col-rail" aria-label="Meta global do patch">
          <div className="wr-panel wr-rail-panel">
            <AugmentsRail />
          </div>
        </aside>
      </div>

      {sheetVisible && selected && (
        <div ref={sheetRef} className="wr-sheet" role="dialog" aria-modal="true" aria-label={`Detalhe de ${selected.name}`}>
          <div className="wr-sheet-head">
            <span className="wr-sheet-title">Detalhe do campeão</span>
            <button ref={sheetCloseRef} type="button" className="wr-sheet-close" onClick={closeSheet} aria-label="Fechar detalhe">
              <Mi name="close" />
            </button>
          </div>
          <ChampionDetail row={selected} />
        </div>
      )}
    </div>
  );
}
