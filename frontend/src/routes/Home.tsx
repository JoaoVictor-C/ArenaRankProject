import "./Home.css";
import { useRef, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Mi,
  ChampIcon,
} from "../components";
import { useApi } from "../hooks/useApi";
import { api } from "../lib/api";
import { nf } from "../lib/format";
import type { LeaderboardRow } from "../lib/types";

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

/* ------------------------------------------------------------------ */
/* Componente principal                                                */
/* ------------------------------------------------------------------ */
export function Home() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  const lb = useApi(() => api.leaderboard({ format: "3v3", limit: 5 }), []);
  const featured: LeaderboardRow | null = lb.data?.rows?.[0] ?? null;

  // Campeões em alta: top-6 por taxa de 1º lugar (dados reais de /champions).
  const champs = useApi(() => api.champions({ format: "3v3", metric: "first" }), []);
  const topChamps = (champs.data?.table ?? []).slice(0, 6);

  // Campeonatos: lista real (/tournaments). Vazio até um operador provisionar.
  const tournaments = useApi(() => api.tournaments(), []);
  const camps = (tournaments.data ?? []).slice(0, 6);

  function handleSearch(e: FormEvent) {
    e.preventDefault();
    const val = inputRef.current?.value.trim() ?? "";
    if (!val) return;
    navigate(`/perfil/${encodeURIComponent(val)}`);
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

      {/* ==================== FEATURED TOP 1 ==================== */}
      <div className="fig-feature">
        <div className="feature-card">
          <div className="fc-bg" aria-hidden="true" />
          <span className="fc-top1">TOP 1</span>
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
            <span className="v tnum">{featured ? nf(featured.cr) : "5.241"}</span>
            <span className="pdl">PDL</span>
            <span className="plus">+{featured?.delta7d ?? 200}</span>
          </div>
          <div className="fc-wl">
            <span className="txt">{featured ? `${featured.wins}` : "300"} <span className="d">V</span> – {featured ? `${featured.losses}` : "120"} <span className="d">D</span></span>
            <span className="wr">{featured ? `${featured.winrate}%` : "81%"}</span>
          </div>
          <Link className="fc-btn" to="/leaderboard">
            VER TABELA COMPLETA <span className="mi">arrow_forward</span>
          </Link>
        </div>
      </div>

      {/* ==================== CAMPEONATOS ==================== */}
      <section className="fig-camp">
        <div className="camp-head">
          <div>
            <h2>CAMPEONATOS</h2>
            <div className="sub">Competições da comunidade Arena — entre, assista e suba de nível.</div>
          </div>
          <Link className="camp-all" to="/campeonatos">
            VER TODOS OS CAMPEONATOS <span className="mi">arrow_forward</span>
          </Link>
        </div>
        <div className="camp-filters">
          <div className="camp-chip" data-active="true">Todos</div>
          <div className="camp-chip">Ao vivo</div>
          <div className="camp-chip">Inscrições abertas</div>
          <div className="camp-chip">Em breve</div>
          <div className="camp-chip">Encerrados</div>
        </div>
        <div className="camp-grid">
          {camps.map((c) => {
            const meta = `${c.teams} EQUIPES · ${c.format.toUpperCase()}`;
            const tag = c.tag ?? "ABERTO";
            const statusClass = /vivo|live|andamento/i.test(tag)
              ? "live"
              : /aberto|inscri/i.test(tag)
                ? "open"
                : /encerr|final/i.test(tag)
                  ? "done"
                  : "soon";
            return (
              <Link className="camp-card" to={`/campeonatos/${c.id}`} key={c.id}>
                <div className="ban">
                  <div className="tint" style={{ background: CAMP_TINTS[c.bannerTone] ?? "#2f6fd6" }} />
                  <span className={`camp-status ${statusClass}`}>
                    <span className="dot" />{tag}
                  </span>
                  <div className="camp-prize"><span>Premiação</span>{c.amountLabel}</div>
                </div>
                <div className="camp-body">
                  <div className="ttl">{c.title}</div>
                  <div className="meta">{meta.split(" · ").map((s, j) => (
                    <span key={j}>{j > 0 && <span className="sep">·</span>}{s}</span>
                  ))}</div>
                  <div className="camp-foot">
                    <span className="camp-when">
                      <span className="mi">sports_esports</span>{c.whenLabel}
                    </span>
                    <span className="camp-cta">Detalhes <span className="mi">arrow_forward</span></span>
                  </div>
                </div>
              </Link>
            );
          })}
          {!tournaments.loading && camps.length === 0 && (
            <div className="camp-empty" style={{ opacity: 0.7, padding: "24px 4px" }}>
              Nenhum campeonato ativo no momento. Volte em breve.
            </div>
          )}
        </div>
      </section>

      {/* ==================== META · CAMPEÕES EM ALTA ==================== */}
      <section className="sec">
        <div className="sec-top">
          <div>
            <span className="eyebrow">Meta da Arena</span>
            <h2>Campeões em alta</h2>
          </div>
          <Link className="see-all" to="/winrate">Ver todos os campeões →</Link>
        </div>
        <div className="meta-grid">
          {topChamps.map((r) => {
            const c1 = r.champion.c1;
            const c2 = r.champion.c2;
            const tierClass = r.tier.charAt(0).toLowerCase();
            return (
              <Link className="meta-card" to="/winrate" key={r.rank} style={{ "--mc1": c1, "--mc2": c2 } as React.CSSProperties}>
                <span className={`meta-tier ${tierClass}`}>{r.tier}</span>
                <ChampIcon colors={{ c1, c2 }} size="lg" />
                <div className="meta-name">{r.name}</div>
                {r.role && <div className="meta-role">{r.role}</div>}
                <div className="meta-stat">
                  <div className="v">{r.first}%</div>
                  <div className="l">Taxa de 1º lugar</div>
                </div>
                <div className="meta-foot">
                  <span className="pick">Pick {r.pickRate.toFixed(1)}%</span>
                  <span className="meta-trend">
                    <span className="mi">social_leaderboard</span>
                    Coloc. {r.avgPlace.toFixed(2)}
                  </span>
                </div>
              </Link>
            );
          })}
          {champs.loading && topChamps.length === 0 && (
            <div className="meta-loading">Carregando campeões…</div>
          )}
        </div>
      </section>

      {/* ==================== FEATURES ==================== */}
      <section className="sec" style={{ paddingTop: 24 }}>
        <div className="sec-top">
          <div><span className="eyebrow">Tudo num só lugar</span><h2>Recursos</h2></div>
        </div>
        <div className="features">
          <Link className="feat" to="/perfil/busca">
            <div className="ic"><Mi name="account_circle" /></div>
            <h3>Perfil completo <span className="arrow">→</span></h3>
            <p>CR, rank, tier, badges e sua evolução — tudo num painel claro e organizado.</p>
          </Link>
          <Link className="feat" to="/partida/busca">
            <div className="ic"><Mi name="receipt_long" /></div>
            <h3>Histórico transparente <span className="arrow">→</span></h3>
            <p>Veja exatamente por que seu CR mudou em cada partida, com todos os ajustes explicados.</p>
          </Link>
          <Link className="feat" to="/perfil/busca">
            <div className="ic"><Mi name="bar_chart" /></div>
            <h3>Stats por campeão <span className="arrow">→</span></h3>
            <p>Taxa de 1º lugar, top 4, colocação média e impacto no CR de cada campeão que você joga.</p>
          </Link>
          <Link className="feat" to="/duo">
            <div className="ic"><Mi name="group" /></div>
            <h3>Head-to-head <span className="arrow">→</span></h3>
            <p>Descubra com quem você joga melhor e como se sai contra rivais específicos.</p>
          </Link>
          <Link className="feat" to="/sistema">
            <div className="ic"><Mi name="verified_user" /></div>
            <h3>Justo e à prova de abuso <span className="arrow">→</span></h3>
            <p>Proteção contra boosting, AFK e combinação de partidas — com revisão humana.</p>
          </Link>
          <Link className="feat" to="/leaderboard">
            <div className="ic"><Mi name="military_tech" /></div>
            <h3>Temporadas e badges <span className="arrow">→</span></h3>
            <p>Reinício suave a cada temporada, conquistas permanentes e arquivo histórico.</p>
          </Link>
        </div>
      </section>

      {/* ==================== CTA ==================== */}
      <div className="cta">
        <div className="cta-inner">
          <div>
            <h2>Pronto para descobrir seu rank?</h2>
            <p>Busque seu Riot ID e veja seu Casual Rating em segundos. Grátis, sem cadastro.</p>
          </div>
          <div className="cta-actions">
            <Link className="btn primary lg" to="/perfil/busca">Ver meu perfil</Link>
            <Link className="btn lg" to="/leaderboard">Explorar ranking</Link>
          </div>
        </div>
      </div>
    </>
  );
}
