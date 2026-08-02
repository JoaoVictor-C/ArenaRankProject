import "./Home.css";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Mi,
  ChampIcon,
} from "../components";
import { useApi } from "../hooks/useApi";
import { useIconColors } from "../hooks/useIconColors";
import { api } from "../lib/api";
import { nf } from "../lib/format";
import { seedFrom, type SnapshotFile } from "../lib/snapshot";
import snapshotHome from "../generated/snapshot.home.json";
import type { LeaderboardRow, LeaderboardResponse, ChampTierlistResponse } from "../lib/types";
import { useFeatureCardMotion, useHomeMotion } from "./homeMotion";

// Semente congelada no build: a home pinta o top-5 e os campeões em alta sem
// esperar a API, e revalida em seguida (ver lib/snapshot).
const SNAP = snapshotHome as SnapshotFile;
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function getInitialReducedMotionPreference(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return true;
  }

  return window.matchMedia(REDUCED_MOTION_QUERY).matches;
}

function getInitialDocumentVisibility(): boolean {
  return typeof document !== "undefined" && document.visibilityState === "visible";
}

/* ------------------------------------------------------------------ */
/* Tint do banner do card de campeonato, derivado do bannerTone da API */
/* ------------------------------------------------------------------ */
const CAMP_TINTS: Record<string, string> = {
  b1: "#e23a34",
  b2: "#1f8a5b",
  b3: "#d5a038",
  b4: "#2f6fd6",
  b5: "#7a3ad6",
  b6: "#3a3f4a",
};

const HOME_PORTALS = [
  {
    key: "leaderboard",
    index: "01",
    label: "Leaderboard",
    title: "A subida começa no placar.",
    description: "Acompanhe o topo, compare PDL e encontre o ritmo da temporada.",
    to: "/leaderboard",
    cta: "Entrar no leaderboard",
  },
  {
    key: "perfil",
    index: "02",
    label: "Perfil",
    title: "Cada ponto deixa um rastro.",
    description: "Histórico, forma recente e os sinais por trás de cada mudança.",
    to: "/",
    cta: "Consultar meu perfil",
  },
  {
    key: "campeoes",
    index: "03",
    label: "Campeões",
    title: "Leia o meta antes da fila.",
    description: "Primeiro lugar, pick rate e colocação média lado a lado.",
    to: "/campeoes",
    cta: "Analisar campeões",
  },
  {
    key: "sinergias",
    index: "04",
    label: "Sinergias",
    title: "A composição muda a luta.",
    description: "Descubra quais duplas e trios transformam uma escolha em plano.",
    to: "/sinergias",
    cta: "Abrir sinergias",
  },
  {
    key: "augments",
    index: "05",
    label: "Augments",
    title: "Feche a build com intenção.",
    description: "Navegue pelo catálogo, raridades e recomendações disponíveis.",
    to: "/augments",
    cta: "Explorar augments",
  },
  {
    key: "campeonatos",
    index: "06",
    label: "Campeonatos",
    title: "A comunidade entra em cena.",
    description: "Inscrições, formatos e premiações num calendário competitivo.",
    to: "/campeonatos",
    cta: "Ver campeonatos",
  },
] as const;

/* Splash centralizado no rosto (Community Dragon) do campeão mais jogado —
   fundo do card TOP 1. Community Dragon é CDN da COMUNIDADE (não oficial Riot);
   montado só aqui, no front, por ora. Precisa apenas do championId numérico. */
function centeredSplash(championId?: number | null): string | undefined {
  return championId
    ? `https://cdn.communitydragon.org/latest/champion/${championId}/splash-art/centered/skin/0`
    : undefined;
}

/* ------------------------------------------------------------------ */
/* Componente principal                                                */
/* ------------------------------------------------------------------ */
export function Home() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const storyRef = useRef<HTMLElement>(null);
  const featureRef = useRef<HTMLDivElement>(null);
  const portalsRef = useRef<HTMLElement>(null);
  const portalsVideoRef = useRef<HTMLVideoElement>(null);
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(
    getInitialReducedMotionPreference,
  );
  const [isPortalsNearViewport, setIsPortalsNearViewport] = useState(false);
  const [isDocumentVisible, setIsDocumentVisible] = useState(
    getInitialDocumentVisibility,
  );
  const [isColiseuPaused, setIsColiseuPaused] = useState(false);
  const canManageColiseuVideo =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    typeof window.IntersectionObserver === "function";
  const shouldLoadColiseuVideo =
    canManageColiseuVideo && !prefersReducedMotion && isPortalsNearViewport;
  const shouldPlayColiseuVideo =
    shouldLoadColiseuVideo && isDocumentVisible && !isColiseuPaused;

  const lb = useApi(
    () => api.leaderboard({ format: "3v3", limit: 5 }),
    [],
    seedFrom<LeaderboardResponse>(SNAP, "leaderboard")
  );
  const featured: LeaderboardRow | null = lb.data?.rows?.[0] ?? null;
  // Campeão mais jogado do TOP 1 (championsStats vem ordenado por partidas).
  const featuredSplash = centeredSplash(featured?.championsStats?.[0]?.championId);
  const mainIconUrl =
    featured?.championIconUrls?.[0] ??
    featured?.championsStats?.[0]?.iconUrl ??
    featured?.profileIconUrl;
  const mainColors = useIconColors(mainIconUrl);
  const featureDeep = mainColors?.[0] ?? featured?.avatar.c1 ?? "var(--primary)";
  const featureBright =
    mainColors?.[1] ?? featured?.avatar.c2 ?? "var(--primary-bright)";

  // Campeões em alta: top-6 por taxa de 1º lugar (dados reais de /champions).
  const champs = useApi(
    () => api.champions({ format: "3v3", metric: "first" }),
    [],
    seedFrom<ChampTierlistResponse>(SNAP, "champions")
  );
  const topChamps = (champs.data?.table ?? []).slice(0, 6);

  // Campeonatos: lista real (/tournaments). Vazio até um operador provisionar.
  const tournaments = useApi(() => api.tournaments(), []);
  const camps = (tournaments.data ?? []).slice(0, 6);
  useFeatureCardMotion(featureRef, [featureDeep, featureBright]);
  useHomeMotion(storyRef, [featured?.cr, topChamps.length, camps.length]);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") {
      setPrefersReducedMotion(true);
      return;
    }

    const mediaQuery = window.matchMedia(REDUCED_MOTION_QUERY);
    const handlePreferenceChange = (event: MediaQueryListEvent) => {
      setPrefersReducedMotion(event.matches);
    };

    setPrefersReducedMotion(mediaQuery.matches);
    mediaQuery.addEventListener("change", handlePreferenceChange);

    return () => {
      mediaQuery.removeEventListener("change", handlePreferenceChange);
    };
  }, []);

  useEffect(() => {
    const section = portalsRef.current;
    if (
      prefersReducedMotion ||
      typeof window.IntersectionObserver !== "function" ||
      !section
    ) {
      setIsPortalsNearViewport(false);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => setIsPortalsNearViewport(Boolean(entry?.isIntersecting)),
      { rootMargin: "320px 0px", threshold: 0.01 },
    );
    observer.observe(section);

    return () => observer.disconnect();
  }, [prefersReducedMotion]);

  useEffect(() => {
    const handleVisibilityChange = () => {
      setIsDocumentVisible(document.visibilityState === "visible");
    };

    handleVisibilityChange();
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, []);

  useEffect(() => {
    const video = portalsVideoRef.current;
    if (!video) return;

    let isCurrent = true;
    if (!shouldPlayColiseuVideo) {
      video.pause();
      return;
    }

    const playAttempt = video.play();
    void playAttempt.catch(() => {
      if (isCurrent) setIsColiseuPaused(true);
    });

    return () => {
      isCurrent = false;
      video.pause();
    };
  }, [shouldPlayColiseuVideo]);

  function handleSearch(e: FormEvent) {
    e.preventDefault();
    const val = inputRef.current?.value.trim() ?? "";
    if (!val) return;
    navigate(`/perfil/${encodeURIComponent(val)}`);
  }

  function focusHeroSearch(event: React.MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    inputRef.current?.focus();
  }

  return (
    <>
      {/* ==================== HERO ==================== */}
      <section className="fig-hero">
        <div className="bg" aria-hidden="true">
          <video
            className="bg-vid"
            autoPlay
            muted
            loop
            playsInline
            preload="auto"
            poster="/assets/fig/hero-bg.png"
          >
            <source src="/assets/fundo.webm" type="video/webm" />
          </video>
        </div>
        <div className="inner">
          <div className="wordmark">
            <span className="wm-word wm-left" aria-label="ARENA">
              {"ARENA".split("").map((l, i) => (
                <span key={i} className="wm-l" style={{ "--i": i } as React.CSSProperties}>{l}</span>
              ))}
            </span>
            <video
              className="mark"
              autoPlay
              muted
              loop
              playsInline
              preload="auto"
              poster="/assets/fig/medallion-poster.png"
              aria-hidden="true"
            >
              <source src="/assets/medallion.webm" type="video/webm" />
            </video>
            <span className="wm-word wm-right" aria-label="RANK">
              {"RANK".split("").map((l, i) => (
                <span key={i} className="wm-l" style={{ "--i": i + 5 } as React.CSSProperties}>{l}</span>
              ))}
            </span>
          </div>

          <form className="hero-search" onSubmit={handleSearch}>
            <span className="mi">search</span>
            <input
              ref={inputRef}
              type="text"
              placeholder="Busque por campeões, jogadores, augments, etc..."
            />
            <span className="br">
              <span className="mi" style={{ fontSize: 15 }}>expand_more</span>BR
            </span>
          </form>

          <div className="hero-btns">
            <Link className="hb blue" to="/leaderboard">MELHORES DO ARENA</Link>
            <Link className="hb gold" to="/campeonatos">CAMPEONATOS</Link>
          </div>

          <div className="hero-tag">
            RANQUEADA, CAMPEONATOS, BUILDS DE ARENA<br />E MUITO MAIS
          </div>
        </div>
      </section>

      {/* THESIS: abaixo do hero, a home vira uma travessia pelo Coliseu, não uma
          grade de benefícios. OWN-WORLD: pedra escura, azul de sistema e ouro
          escasso. STORY: provar o PDL, atravessar as superfícies e entrar.
          FIRST VIEWPORT: Header e fig-hero acima permanecem intocados.
          FORM: portais editoriais horizontais no desktop e fluxo no mobile. */}
      <main className="home-story" ref={storyRef} data-home-story>
        {/* ==================== FEATURED TOP 1 ==================== */}
        <div className="fig-feature" data-home-feature>
          <span className="fc-top1">TOP 1</span>
          <div
            ref={featureRef}
            className="feature-card"
            data-testid="home-feature-card"
            style={{
              "--fc-fallback-deep": featureDeep,
              "--fc-fallback-bright": featureBright,
            } as React.CSSProperties}
          >
            <div
              className="fc-bg"
              aria-hidden="true"
              style={featuredSplash ? { backgroundImage: `url(${featuredSplash})` } : undefined}
            />
            <div className="fc-energy" data-feature-energy aria-hidden="true">
              <span className="fc-energy__field">
                <i className="fc-energy__shape fc-energy__shape--a" data-feature-shape />
                <i className="fc-energy__shape fc-energy__shape--b" data-feature-shape />
                <i className="fc-energy__shape fc-energy__shape--c" data-feature-shape />
              </span>
              <i className="fc-energy__beam" data-feature-beam />
              <i className="fc-energy__frame" data-feature-frame />
            </div>
            <div className="fc-rank">{featured?.rank ?? 1}</div>
            <div
              className="fc-av"
              role="img"
              aria-label={`Avatar de ${featured?.name ?? "TOP 1"}`}
              style={
                featured?.profileIconUrl
                  ? { backgroundImage: `url(${featured.profileIconUrl})`, backgroundSize: "cover", backgroundPosition: "center" }
                  : featured
                    ? { background: `linear-gradient(135deg, ${featured.avatar.c1}, ${featured.avatar.c2})` }
                    : undefined
              }
            />
            <div className="fc-id">
              <div className="nm-row">
                <span className="nm">{featured?.name ?? "PRESENTE"}</span>
                <span className="hash">{featured?.handle ?? "#1001"}</span>
              </div>
              <div className="fc-tags">
                {(featured?.tags ?? []).slice(0, 3).map((t, i) => (
                  <span className={`fc-tag ${i === 0 ? "gold" : "vio"}`} key={i}>
                    <Mi name={t.icon} />
                    {t.label}
                  </span>
                ))}
                {(featured?.tags?.length ?? 0) > 3 && (
                  <span className="fc-tag more">+{featured!.tags.length - 3}</span>
                )}
              </div>
            </div>
            <div className="fc-spacer" />
            <div className="fc-cr">
              <span className="v tnum" data-countup>
                {featured ? nf(featured.cr) : "5.241"}
              </span>
              <span className="pdl">PDL</span>
              <span className="plus">+{featured?.delta7d ?? 200}</span>
            </div>
            <div className="fc-wl">
              <span className="txt">{featured ? `${featured.wins}` : "300"} <span className="d">V</span> – {featured ? `${featured.losses}` : "120"} <span className="d">D</span></span>
              <span className="wr">{featured ? `${featured.winrate}%` : "81%"}</span>
            </div>
            <Link className="fc-btn" to="/leaderboard">
              <span className="fc-btn__label">VER TABELA COMPLETA</span>
              <span className="mi">arrow_forward</span>
            </Link>
          </div>
        </div>

        <section className="home-manifesto" aria-labelledby="home-manifesto-title">
          <div className="home-manifesto__aside">
            <span className="home-sigil" aria-hidden="true">AR</span>
            <p>Uma camada competitiva para cada escolha dentro do Arena.</p>
          </div>
          <div className="home-manifesto__copy">
            <span className="home-kicker">O hub competitivo do Arena</span>
            <h2 id="home-manifesto-title" data-home-manifesto>
              O Arena agora tem um placar. E tudo se conecta a ele.
            </h2>
          </div>
        </section>

        <section
          className="home-portals"
          aria-label="Portais do Coliseu"
          data-home-portals
          ref={portalsRef}
        >
          <div
            className="home-portals__media"
            data-home-portals-media
            aria-hidden="true"
          >
            <video
              data-home-portals-video
              ref={portalsVideoRef}
              autoPlay={shouldPlayColiseuVideo}
              muted
              loop
              playsInline
              preload="metadata"
            >
              {shouldLoadColiseuVideo && (
                <source
                  src="/assets/card-arena-coliseu.webm"
                  type="video/webm"
                />
              )}
            </video>
          </div>

          {canManageColiseuVideo && !prefersReducedMotion && (
            <button
              className="home-portals__motion-control"
              type="button"
              aria-label={
                isColiseuPaused
                  ? "Retomar animação do Coliseu"
                  : "Pausar animação do Coliseu"
              }
              aria-pressed={isColiseuPaused}
              onClick={() => setIsColiseuPaused((paused) => !paused)}
            >
              <span className="mi" aria-hidden="true">
                {isColiseuPaused ? "play_arrow" : "pause"}
              </span>
            </button>
          )}

          <div className="home-portals__head">
            <div>
              <span className="home-kicker">Escolha uma entrada</span>
              <h2>O Coliseu inteiro,<br />numa só travessia.</h2>
            </div>
            <p>
              Ranking, histórico e meta compartilham a mesma linguagem:
              sua próxima partida.
            </p>
          </div>

          <div className="home-portals__viewport">
            <div className="home-portals__track" data-home-portal-track>
              {HOME_PORTALS.map((portal) => (
                <Link
                  className={`home-portal home-portal--${portal.key}`}
                  to={portal.to}
                  key={portal.key}
                  aria-label={portal.cta}
                  data-home-portal
                  onClick={portal.key === "perfil" ? focusHeroSearch : undefined}
                >
                  <span className="home-portal__index">{portal.index}</span>
                  <div className="home-portal__copy">
                    <span className="home-portal__label">{portal.label}</span>
                    <h3>{portal.title}</h3>
                    <p>{portal.description}</p>
                  </div>

                  <div className="home-portal__visual" aria-hidden="true">
                    {portal.key === "leaderboard" && (
                      <div className="portal-board">
                        {[0, 1, 2].map((offset) => (
                          <span className="portal-board__row" key={offset}>
                            <i>0{offset + 1}</i>
                            <b>{offset === 0 ? featured?.name ?? "TOP 1" : ["RIVAL", "ASCENDENTE"][offset - 1]}</b>
                            <em>{offset === 0 && featured ? nf(featured.cr) : nf(5030 - offset * 164)} PDL</em>
                          </span>
                        ))}
                      </div>
                    )}

                    {portal.key === "perfil" && (
                      <div className="portal-profile">
                        <span className="portal-profile__avatar" />
                        <span className="portal-profile__id">{featured?.name ?? "SEU RIOT ID"}<small>{featured?.handle ?? "#BR1"}</small></span>
                        <strong>{featured ? nf(featured.cr) : "—"}<small>PDL</small></strong>
                        <svg viewBox="0 0 240 68" role="presentation">
                          <path d="M4 57 C45 52 52 20 91 34 S145 58 168 25 S212 10 236 8" />
                        </svg>
                      </div>
                    )}

                    {portal.key === "campeoes" && (
                      <div className="portal-champions">
                        {topChamps.slice(0, 3).map((champ) => (
                          <span key={champ.rank}>
                            <ChampIcon
                              colors={{ c1: champ.champion.c1, c2: champ.champion.c2 }}
                              url={champ.championIconUrl ?? undefined}
                              size="lg"
                            />
                            <b>{champ.name}</b>
                            <em>{champ.tier}</em>
                          </span>
                        ))}
                      </div>
                    )}

                    {portal.key === "sinergias" && (
                      <div className="portal-synergy">
                        <i className="portal-synergy__line" />
                        {topChamps.slice(0, 3).map((champ, index) => (
                          <span className={`portal-synergy__node n${index + 1}`} key={champ.rank}>
                            <ChampIcon
                              colors={{ c1: champ.champion.c1, c2: champ.champion.c2 }}
                              url={champ.championIconUrl ?? undefined}
                              size="lg"
                            />
                          </span>
                        ))}
                        <strong>COMPOSIÇÃO<br />EM SINCRONIA</strong>
                      </div>
                    )}

                    {portal.key === "augments" && (
                      <div className="portal-augments">
                        <span className="prismatic"><Mi name="diamond" /><b>Prismático</b></span>
                        <span className="gold"><Mi name="auto_awesome" /><b>Ouro</b></span>
                        <span className="silver"><Mi name="hexagon" /><b>Prata</b></span>
                      </div>
                    )}

                    {portal.key === "campeonatos" && (
                      <div className="portal-tournament">
                        <span>{camps[0]?.tag ?? "PRÓXIMA ARENA"}</span>
                        <b>{camps[0]?.title ?? "Calendário competitivo"}</b>
                        <strong>{camps[0]?.amountLabel ?? "EM BREVE"}</strong>
                        <small>{camps[0]?.whenLabel ?? "Acompanhe as inscrições"}</small>
                      </div>
                    )}
                  </div>

                  <span className="home-portal__cta">
                    {portal.cta}
                    <Mi name="arrow_outward" />
                  </span>
                </Link>
              ))}
            </div>
          </div>
        </section>

        <section className="home-meta" aria-label="Diagnóstico do meta">
          <div className="home-section-head">
            <div>
              <span className="home-kicker">Diagnóstico do meta</span>
              <h2>Seis nomes.<br />Quatro sinais.<br />Uma decisão.</h2>
            </div>
            <div className="home-section-head__aside">
              <p>
                Compare quem transforma presença em primeiro lugar antes de
                escolher sua próxima composição.
              </p>
              <Link to="/campeoes">Abrir análise completa <Mi name="arrow_outward" /></Link>
            </div>
          </div>

          <div className="home-meta__plate">
            <div className="home-meta__legend" aria-hidden="true">
              <span>Campeão</span>
              <span>1º lugar</span>
              <span>Pick</span>
              <span>Coloc.</span>
            </div>
            {topChamps.map((champ) => (
              <Link
                className="home-meta__specimen"
                to="/campeoes"
                key={champ.rank}
              >
                <span className="home-meta__identity">
                  <ChampIcon
                    colors={{ c1: champ.champion.c1, c2: champ.champion.c2 }}
                    url={champ.championIconUrl ?? undefined}
                    size="lg"
                  />
                  <span>
                    <b>{champ.name}</b>
                    <small>{champ.role ?? `Tier ${champ.tier}`}</small>
                  </span>
                  <i className={`home-meta__tier t-${champ.tier.charAt(0).toLowerCase()}`}>
                    {champ.tier}
                  </i>
                </span>
                <strong className="tnum">{champ.first}%</strong>
                <span className="tnum">{champ.pickRate.toFixed(1)}%</span>
                <span className="tnum">{champ.avgPlace.toFixed(2)}</span>
                <Mi name="arrow_outward" />
              </Link>
            ))}
            {champs.loading && topChamps.length === 0 && (
              <div className="home-meta__empty">Atualizando leitura do meta…</div>
            )}
            <svg
              className="home-meta__paths"
              viewBox="0 0 1200 560"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <path data-home-meta-path d="M310 0 V560" />
              <path data-home-meta-path d="M650 0 V560" />
              <path data-home-meta-path d="M820 0 V560" />
              <path data-home-meta-path d="M990 0 V560" />
            </svg>
          </div>
        </section>

        <section
          className="home-tournaments"
          aria-label="Campeonatos da comunidade"
        >
          <div className="home-section-head">
            <div>
              <span className="home-kicker">Campeonatos da comunidade</span>
              <h2>A próxima arena<br />já está sendo montada.</h2>
            </div>
            <div className="home-section-head__aside">
              <p>
                Entre, acompanhe e transforme o leaderboard numa cena que
                joga junto.
              </p>
              <Link to="/campeonatos">Ver calendário completo <Mi name="arrow_outward" /></Link>
            </div>
          </div>

          {camps.length > 0 ? (
            <div className="home-tournaments__rail">
              {camps.map((camp, index) => {
                const tag = camp.tag ?? "ABERTO";
                return (
                  <Link
                    className="home-tournament"
                    to={`/campeonatos/${camp.id}`}
                    key={camp.id}
                    style={{ "--tint": CAMP_TINTS[camp.bannerTone] ?? "#2f6fd6" } as React.CSSProperties}
                  >
                    <span className="home-tournament__number">0{index + 1}</span>
                    <span className="home-tournament__status"><i />{tag}</span>
                    <div className="home-tournament__body">
                      <h3>{camp.title}</h3>
                      <p>{camp.teams} equipes · {camp.format.toUpperCase()}</p>
                    </div>
                    <strong>{camp.amountLabel}</strong>
                    <span className="home-tournament__when">{camp.whenLabel}</span>
                    <Mi name="arrow_outward" />
                  </Link>
                );
              })}
            </div>
          ) : (
            <div className="home-tournaments__empty">
              <span className="home-sigil" aria-hidden="true">AR</span>
              <div>
                <h3>Nenhum campeonato ativo no momento.</h3>
                <p>O calendário abre assim que a próxima disputa for confirmada.</p>
              </div>
              <Link to="/campeonatos">Acompanhar campeonatos <Mi name="arrow_outward" /></Link>
            </div>
          )}
        </section>

        <section className="home-close" aria-labelledby="home-close-title">
          <span className="home-close__orbit" aria-hidden="true">
            <i />
            <b>AR</b>
          </span>
          <div className="home-close__copy">
            <span className="home-kicker">Sua próxima entrada</span>
            <h2 id="home-close-title">O histórico já começou.<br />Agora encontre seu lugar.</h2>
          </div>
          <div className="home-close__actions">
            <Link
              className="home-action home-action--primary"
              to="/"
              onClick={focusHeroSearch}
            >
              Consultar meu perfil <Mi name="arrow_outward" />
            </Link>
            <Link className="home-action" to="/leaderboard">
              Explorar o leaderboard <Mi name="arrow_outward" />
            </Link>
          </div>
        </section>
      </main>
    </>
  );
}
