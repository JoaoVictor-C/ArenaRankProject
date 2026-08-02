/* ============================================================
   Sinergias.tsx — /sinergias
   Tierlist de composições: bandas S+→D, cada uma com as comps
   daquele nível. Alterna dupla (2) e trio (3) — o Arena roda 3v3,
   então o trio é o padrão.

   Dado real: api.championSynergyTierlist (winrate top-half REAL de
   subteam na ladder BR, placement-derived).
   ============================================================ */
import { useMemo, useRef, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import "./Tierlists.css";
import { api } from "../lib/api";
import { useApi } from "../hooks/useApi";
import { StateBlock, Mi, ParticleField } from "../components";
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
} from "../lib/motion";
import type { ChampionSynergyGroup, SynergyChampion } from "../lib/types";

const pctInt = (n: number) => `${Math.round(n)}%`;
const fmtPlace = (n: number) => n.toFixed(2).replace(".", ",");
const tierKey = (t: string) => t.toLowerCase().replace("+", "plus");

/** Rótulo curto de cada banda — o que aquele tier significa na prática. */
const BAND_NOTE: Record<string, string> = {
  "S+": "quebra o meta",
  S: "dominante",
  A: "forte",
  B: "sólida",
  C: "situacional",
  D: "evitar",
};

const SYNERGY_ENTRANCE: EntranceStep[] = [
  {
    selector: ".tl-head",
    from: { opacity: 0, y: 18, filter: "blur(5px)" },
    duration: 0.5,
  },
  {
    selector: ".tl-synergy-table",
    from: { opacity: 0, y: 16, clipPath: "inset(0 0 12% 0 round 12px)" },
    duration: 0.5,
    position: "-=0.2",
  },
  {
    selector: ".tl-synergy-row",
    from: { opacity: 0, x: 14 },
    duration: 0.38,
    stagger: 0.035,
    position: "-=0.28",
  },
];

const SYNERGY_INTERACTIONS: InteractionMotion[] = [
  { trigger: ".tl-synergy-row", to: { y: -2 } },
  { trigger: ".tl-synergy-row", target: ".tl-faces", to: { scale: 1.025 } },
  { trigger: ".tl-face", to: { scale: 1.07 } },
];

function Face({ c }: { c: SynergyChampion }) {
  const [failed, setFailed] = useState(false);
  return (
    <span
      className="tl-face"
      data-testid="synergy-champion-face"
      style={{ "--c1": c.colors.c1, "--c2": c.colors.c2 } as CSSProperties}
      aria-hidden="true"
    >
      {/* eager de propósito: a face É o conteúdo da tierlist e nasce acima da
          dobra. `loading="lazy"` em imagem above-the-fold só adia o LCP —
          adiar 38px não compra nada. */}
      {c.championIconUrl && !failed && (
        <img src={c.championIconUrl} alt="" draggable={false} onError={() => setFailed(true)} />
      )}
    </span>
  );
}

function CompRow({ g, rank, tier }: { g: ChampionSynergyGroup; rank: number; tier: string }) {
  const names = g.champions.map((c) => c.name);
  return (
    <Link
      to={`/campeao/${g.champions[0]?.championId ?? ""}`}
      className={`tl-synergy-row tl-synergy-tier-${tierKey(tier)}`}
      role="row"
      title={`${names.join(" · ")} — top 4 ${pctInt(g.winRate)} · 1º lugar ${pctInt(g.firstRate)} · col. média ${fmtPlace(g.avgPlace)} · ${nf(g.games)} partidas`}
    >
      <span className="tl-synergy-rank tnum" role="cell">
        {rank}
      </span>
      <span className="tl-synergy-composition" role="cell">
        <span className="tl-faces">
          {g.champions.map((c) => (
            <Face key={c.championId} c={c} />
          ))}
        </span>
        <span className="tl-comp-meta">
          <span className="tl-comp-nm">{names.join(" · ")}</span>
          <span className="tl-comp-sub tl-mobile-meta tnum">
            Col. média {fmtPlace(g.avgPlace)} · {nf(g.games)} jogos
          </span>
        </span>
      </span>
      <span className="tl-synergy-tier" role="cell">
        <b>{tier}</b>
        <span>{BAND_NOTE[tier] ?? "tier"}</span>
      </span>
      <span className="tl-synergy-top4" role="cell">
        <b className="tnum">{pctInt(g.winRate)}</b>
        <span>TOP 4</span>
      </span>
      <span className="tl-synergy-place tnum" role="cell">
        {fmtPlace(g.avgPlace)}
      </span>
      <span className="tl-synergy-games tnum" role="cell">
        {nf(g.games)}
      </span>
    </Link>
  );
}

export function Sinergias() {
  const [size, setSize] = useState<2 | 3>(3);
  const [query, setQuery] = useState("");
  const { data, loading, error, retry, refreshing } = useApi(
    () => api.championSynergyTierlist({ size }),
    [size],
  );
  const replacingSize = Boolean(refreshing && data && data.size !== size);

  const q = query.trim().toLowerCase();
  const bands = useMemo(() => {
    return (data?.tiers ?? []).map((t) => ({
      ...t,
      comps: q ? t.comps.filter((c) => c.champions.some((ch) => ch.name.toLowerCase().includes(q))) : t.comps,
    }));
  }, [data, q]);

  const total = bands.reduce((n, b) => n + b.comps.length, 0);
  const rows = bands.flatMap((tier) =>
    tier.comps.map((composition) => ({
      tier: tier.key,
      composition,
    })),
  );

  const pageRef = useRef<HTMLDivElement>(null);
  useGsapEntrance(pageRef, { steps: SYNERGY_ENTRANCE, deps: [Boolean(data)] });
  useGsapLoop(pageRef, [STATE_SPINNER_LOOP]);
  /* Filtrar reordena os cards dentro das bandas: cada um viaja da posição
     antiga em vez de a lista piscar. `capture()` roda ANTES do setState. */
  const flip = useFlipList(pageRef, ".tl-synergy-row", q);
  useGsapSwap(
    pageRef,
    ".tl-synergy-table",
    `${size}|${data?.size ?? "loading"}|${data?.sampleSize ?? 0}`,
    { from: { opacity: 0, x: size === 3 ? 16 : -16 }, duration: 0.32 },
  );
  useGsapInteractions(pageRef, SYNERGY_INTERACTIONS);

  return (
    <div className="tl-page tl-page-synergies" ref={pageRef} data-gsap-scope>
      <div className="tl-amb" aria-hidden="true" />
      <ParticleField variant="route" />

      <div className="tl-wrap">
        <header className="tl-head">
          <div className="tl-title">
            <div className="tl-eyebrow">
              <Mi name="hub" />
              Arena {size === 3 ? "3v3" : "duplas"} · Ladder BR
            </div>
            <h1 className="tl-h1">Sinergias</h1>
            <p className="tl-sub">
              As composições que mais fecham top 4 juntas. Winrate é a taxa de metade superior do subteam —
              partida de verdade da ladder, não simulação.
            </p>
            {data && (
              <div className="tl-context" aria-label="Contexto do ranking">
                <span>Temporada {data.season}</span>
                <span className="tnum">{nf(data.sampleSize)} partidas analisadas</span>
                <span className="tnum">Piso de {nf(data.minGames)} por composição</span>
                {replacingSize && (
                  <span className="tl-refresh-status" role="status">
                    Atualizando para {size === 2 ? "duplas" : "trios"}…
                  </span>
                )}
              </div>
            )}
          </div>
          <div className="tl-tools">
            <div className="tl-tabs" role="group" aria-label="Tamanho do subteam">
              <button
                type="button"
                className={size === 3 ? "on" : ""}
                aria-pressed={size === 3}
                onClick={() => setSize(3)}
              >
                Trio
              </button>
              <button
                type="button"
                className={size === 2 ? "on" : ""}
                aria-pressed={size === 2}
                onClick={() => setSize(2)}
              >
                Dupla
              </button>
            </div>
            <label className="tl-search">
              <Mi name="search" />
              <input
                type="text"
                value={query}
                onChange={(e) => {
                  flip.capture();
                  setQuery(e.target.value);
                }}
                placeholder="Filtrar por campeão"
                aria-label="Filtrar composições por campeão"
              />
            </label>
          </div>
        </header>

        <StateBlock loading={loading} error={error} onRetry={retry} empty={!loading && !bands.length}>
          {q && total === 0 ? (
            <p className="tl-filter-empty">Nenhuma composição com esse campeão.</p>
          ) : (
            <div
              className="tl-synergy-table"
              role="table"
              aria-label="Ranking de sinergias"
              aria-colcount={6}
              aria-rowcount={rows.length + 1}
              aria-busy={replacingSize}
            >
              <div className="tl-synergy-head" role="row">
                <span role="columnheader">Rank</span>
                <span role="columnheader">Composição</span>
                <span role="columnheader">Tier</span>
                <span role="columnheader">Top 4</span>
                <span role="columnheader">Col. média</span>
                <span role="columnheader">Jogos</span>
              </div>
              <div role="rowgroup">
                {rows.map(({ tier, composition }, index) => (
                  <CompRow
                    key={composition.champions.map((champion) => champion.championId).join("-")}
                    g={composition}
                    rank={index + 1}
                    tier={tier}
                  />
                ))}
              </div>
            </div>
          )}

          {data && (
            <p className="tl-foot">
              <Mi name="info" />
              Temporada {data.season} · {nf(data.sampleSize)} partidas amostradas · piso de {nf(data.minGames)}{" "}
              partidas por composição. Top 4 = metade superior do lobby; composições abaixo do
              piso ficam de fora em vez de aparecer com número instável.
            </p>
          )}
        </StateBlock>
      </div>
    </div>
  );
}
