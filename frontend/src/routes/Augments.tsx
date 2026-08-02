/* ============================================================
   Augments.tsx — /augments
   Catálogo do Arena organizado pela raridade real do draft.

   A referência visual define apenas a composição do catálogo. Shell,
   marca, textos e dados continuam pertencendo ao ArenaRank.
   ============================================================ */
import { useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import "./Augments.css";
import { useApi } from "../hooks/useApi";
import { StateBlock, Mi, BuildHoverIcon } from "../components";
import {
  STATE_SPINNER_LOOP,
  useFlipList,
  useGsapEntrance,
  useGsapInteractions,
  useGsapLoop,
  useReveal,
  type EntranceStep,
  type InteractionMotion,
} from "../lib/motion";
import {
  fetchAugmentCatalog,
  type AugmentCatalogEntry,
  type CatalogChampion,
  type CatalogRarity,
} from "./augmentCatalog";
import { useAugmentsHorizontalGallery } from "./augmentGalleryMotion";

const championIcon = (championId: number) =>
  `https://cdn.communitydragon.org/latest/champion/${championId}/square`;

type RarityFilter = "all" | Exclude<CatalogRarity, "unknown">;

const RARITY_ORDER: CatalogRarity[] = [
  "prismatic",
  "gold",
  "silver",
  "unique",
  "unknown",
];

const RARITY_LABEL: Record<CatalogRarity, string> = {
  unique: "Único",
  prismatic: "Prismático",
  gold: "Ouro",
  silver: "Prata",
  unknown: "Raridade não informada",
};

const SECTION_COPY: Record<
  CatalogRarity,
  { title: string; description: string }
> = {
  unique: {
    title: "Augments únicos",
    description:
      "Escolhas especiais que mudam as regras da partida de Arena.",
  },
  prismatic: {
    title: "Augments prismáticos",
    description:
      "As escolhas mais transformadoras do draft, com impacto decisivo na composição.",
  },
  gold: {
    title: "Augments de ouro",
    description:
      "Ferramentas versáteis que consolidam o plano de jogo da equipe.",
  },
  silver: {
    title: "Augments de prata",
    description:
      "Ajustes eficientes que completam sinergias e cobrem pontos fracos.",
  },
  unknown: {
    title: "Raridade não informada",
    description:
      "O agregado atual ainda não separa estas escolhas pela raridade do draft.",
  },
};

const FILTERS: { key: RarityFilter; label: string }[] = [
  { key: "all", label: "Todos" },
  { key: "unique", label: "Único" },
  { key: "prismatic", label: "Prismático" },
  { key: "gold", label: "Ouro" },
  { key: "silver", label: "Prata" },
];

const AUGMENTS_ENTRANCE: EntranceStep[] = [
  {
    selector: ".augments-header",
    from: { opacity: 0, y: 16, filter: "blur(5px)" },
    duration: 0.5,
  },
  {
    selector: ".augments-toolbar",
    from: { opacity: 0, y: 12 },
    duration: 0.38,
    position: "-=0.22",
  },
];

const AUGMENTS_INTERACTIONS: InteractionMotion[] = [
  { trigger: ".augment-champion", to: { scale: 1.12 } },
];

function AugmentArt({
  url,
  className,
}: {
  url?: string | null;
  className: string;
}) {
  const large = url?.replace("_small.png", "_large.png") ?? null;
  const [failedLarge, setFailedLarge] = useState(false);
  const [failedFallback, setFailedFallback] = useState(false);
  const src = failedLarge ? url : large;

  if (!src || failedFallback) {
    return (
      <span className={`${className} augment-art-fallback`} aria-hidden="true">
        <Mi name="auto_awesome" />
      </span>
    );
  }

  return (
    <img
      className={className}
      src={src}
      alt=""
      loading="lazy"
      decoding="async"
      draggable={false}
      onError={() => {
        if (!failedLarge && url && src !== url) setFailedLarge(true);
        else setFailedFallback(true);
      }}
    />
  );
}

function ChampionRecommendation({
  champion,
}: {
  champion: CatalogChampion;
}) {
  const [failed, setFailed] = useState(false);
  return (
    <Link
      className="augment-champion"
      to={`/campeao/${champion.championId}`}
      aria-label={champion.name}
      title={champion.name}
    >
      {failed ? (
        <span aria-hidden="true">{champion.name.slice(0, 1)}</span>
      ) : (
        <img
          src={championIcon(champion.championId)}
          alt=""
          loading="lazy"
          decoding="async"
          draggable={false}
          onError={() => setFailed(true)}
        />
      )}
    </Link>
  );
}

function AugmentCard({ augment }: { augment: AugmentCatalogEntry }) {
  const description = augment.description ?? "Descrição em breve";
  const participatesInDock =
    augment.rarity === "prismatic" ||
    augment.rarity === "gold" ||
    augment.rarity === "silver";
  const tierLabel = augment.tier
    ? `tier ${augment.tier}`
    : "tier em breve";
  const label = `${augment.name} · ${tierLabel} · ${RARITY_LABEL[augment.rarity]}`;

  return (
    <div
      className="augment-dock-item"
      data-augment-dock-item={participatesInDock ? "" : undefined}
    >
      <article
        className="augment-card"
        data-rarity={augment.rarity}
        aria-label={label}
      >
        <div className="augment-card-art" aria-hidden="true">
          <AugmentArt
            url={augment.iconUrl}
            className="augment-card-art-image"
          />
        </div>

        <span className="augment-tier-badge">
          {augment.tier ? `Tier ${augment.tier}` : "Tier em breve"}
        </span>

        <BuildHoverIcon
          className="augment-icon"
          data={{
            name: augment.name,
            iconUrl: augment.iconUrl,
            badge: augment.tier ?? undefined,
            badgeClassName: augment.tier ? `tier-${augment.tier.toLowerCase().replace("+", "plus")}` : undefined,
            description,
          }}
        >
          <AugmentArt url={augment.iconUrl} className="augment-icon-image" />
        </BuildHoverIcon>

        <h3>{augment.name}</h3>
        <p className="augment-description" title={description}>
          {description}
        </p>

        {augment.champions.length > 0 && (
          <div
            className="augment-champions"
            aria-label={`Melhores campeões para ${augment.name}`}
          >
            {augment.champions.slice(0, 5).map((champion) => (
              <ChampionRecommendation
                key={champion.championId}
                champion={champion}
              />
            ))}
          </div>
        )}

      </article>
    </div>
  );
}

export function Augments() {
  const [query, setQuery] = useState("");
  const [rarity, setRarity] = useState<RarityFilter>("all");
  const { data, loading, error, retry } = useApi(
    () => fetchAugmentCatalog(),
    [],
  );

  const q = query.trim().toLocaleLowerCase("pt-BR");
  const availableRarities = useMemo(
    () => new Set((data?.augments ?? []).map((augment) => augment.rarity)),
    [data],
  );
  const filtered = useMemo(
    () =>
      (data?.augments ?? []).filter((augment) => {
        const searchable =
          `${augment.name} ${augment.description ?? ""}`.toLocaleLowerCase(
            "pt-BR",
          );
        const matchesQuery = !q || searchable.includes(q);
        const matchesRarity =
          rarity === "all" || augment.rarity === rarity;
        return matchesQuery && matchesRarity;
      }),
    [data, q, rarity],
  );
  const sections = useMemo(
    () =>
      RARITY_ORDER.map((key) => ({
        key,
        entries: filtered.filter((augment) => augment.rarity === key),
      })).filter(({ entries }) => entries.length > 0),
    [filtered],
  );

  const total = filtered.length;
  const resultLabel = `${total} ${total === 1 ? "augment encontrado" : "augments encontrados"}`;
  const hasData = Boolean(data?.augments.length);
  const hasMockedFields = Boolean(data?.mockedFields?.length);

  const pageRef = useRef<HTMLDivElement>(null);
  useGsapEntrance(pageRef, {
    steps: AUGMENTS_ENTRANCE,
    deps: [hasData],
  });
  useReveal(pageRef, {
    blocks: ".augment-rarity-section",
    deps: [hasData],
  });
  useGsapLoop(pageRef, [STATE_SPINNER_LOOP]);
  const flip = useFlipList(
    pageRef,
    ".augment-card",
    `${q}|${rarity}`,
  );
  useAugmentsHorizontalGallery(
    pageRef,
    `${q}|${rarity}|${total}|${sections.map(({ key }) => key).join(",")}`,
  );
  useGsapInteractions(pageRef, AUGMENTS_INTERACTIONS);

  return (
    <div className="augments-page" ref={pageRef} data-gsap-scope>
      <div className="augments-ambient" aria-hidden="true" />

      <div className="augments-shell">
        <header className="augments-header">
          <img
            className="augments-mode-icon"
            src="/assets/fig/icon-arena.png"
            alt=""
          />
          <div>
            <div className="augments-heading-line">
              <h1>Augments do Arena</h1>
              {data?.patch && (
                <span className="augments-patch">Patch {data.patch}</span>
              )}
            </div>
            <p>
              Encontre augments por nome, efeito ou raridade e descubra quais
              campeões aproveitam melhor cada escolha.
            </p>
          </div>
        </header>

        <div className="augments-toolbar">
          <label className="augments-search">
            <Mi name="search" />
            <input
              type="text"
              value={query}
              onChange={(event) => {
                flip.capture();
                setQuery(event.target.value);
              }}
              placeholder="Busque por nome ou descrição"
              aria-label="Buscar augment no catálogo"
            />
          </label>

          <div
            className="augments-filters"
            role="group"
            aria-label="Filtrar por raridade"
          >
            {FILTERS.map((filter) => {
              const disabled =
                filter.key !== "all" &&
                !availableRarities.has(filter.key);
              return (
                <button
                  type="button"
                  key={filter.key}
                  className={rarity === filter.key ? "is-active" : ""}
                  aria-pressed={rarity === filter.key}
                  disabled={disabled}
                  title={
                    disabled
                      ? "Esta raridade ainda não está disponível no catálogo"
                      : undefined
                  }
                  onClick={() => {
                    flip.capture();
                    setRarity(filter.key);
                  }}
                >
                  {filter.label}
                </button>
              );
            })}
          </div>

          <span className="augments-result-count tnum" aria-live="polite">
            {resultLabel}
          </span>
        </div>

        <StateBlock
          loading={loading}
          error={error}
          onRetry={retry}
          empty={!loading && !hasData}
          emptyLabel="Nenhum augment disponível neste patch."
        >
          {(q || rarity !== "all") && total === 0 ? (
            <p className="augments-filter-empty">
              Nenhum augment combina com os filtros atuais.
            </p>
          ) : (
            <div
              className="augment-gallery-stage"
              role="region"
              aria-label="Galeria horizontal de augments"
            >
              <div className="augment-rarity-sections">
                {sections.map(({ key, entries }) => (
                  <section
                    className="augment-rarity-section"
                    data-rarity={key}
                    key={key}
                    aria-label={SECTION_COPY[key].title}
                  >
                    <header>
                      <div className="augment-section-copy">
                        <h2>{SECTION_COPY[key].title}</h2>
                        <p>{SECTION_COPY[key].description}</p>
                      </div>
                      <div
                        className="augment-gallery-controls"
                        aria-label={`Navegar por ${SECTION_COPY[key].title.toLocaleLowerCase("pt-BR")}`}
                      >
                        <button
                          type="button"
                          data-augment-scroll="prev"
                          aria-label={`Ver augments anteriores em ${SECTION_COPY[key].title}`}
                        >
                          <Mi name="arrow_back" />
                        </button>
                        <button
                          type="button"
                          data-augment-scroll="next"
                          aria-label={`Ver próximos augments em ${SECTION_COPY[key].title}`}
                        >
                          <Mi name="arrow_forward" />
                        </button>
                      </div>
                    </header>
                    <div
                      className="augments-grid"
                      data-augment-gallery-row
                      role="group"
                      aria-label={`${SECTION_COPY[key].title}: ${entries.length} augments`}
                      tabIndex={0}
                    >
                      {entries.map((augment) => (
                        <AugmentCard key={augment.id} augment={augment} />
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            </div>
          )}

          {data && (
            <p className="augments-method">
              <Mi name="info" />
              {hasMockedFields ? (
                <>
                  Catálogo Riot do patch {data.patch || "atual"}. Nesta
                  prévia, tier e recomendações de campeões são demonstrativos;
                  nomes, descrições, ícones e raridades vêm do catálogo oficial.
                </>
              ) : (
                <>
                  Catálogo Riot do patch {data.patch || "atual"}. Nomes,
                  descrições, ícones e raridades são oficiais; tier e
                  recomendações aparecem quando o processamento do ArenaRank
                  estiver disponível.
                </>
              )}
            </p>
          )}
        </StateBlock>
      </div>
    </div>
  );
}
