import {
  useState,
  useRef,
  useEffect,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { Link, NavLink, useNavigate, useLocation, type NavigateFunction } from "react-router-dom";
import { api } from "../lib/api";
import type { SearchPlayer, TierKey } from "../lib/types";
import { PlayerAvatar } from "./Avatar";
import { nf } from "../lib/format";

const TIER_LABEL: Record<TierKey, string> = {
  top1: "#1",
  top10: "Top 10",
  top50: "Top 50",
  top100: "Top 100",
  top500: "Top 500",
  none: "",
};

const NAV: { to: string; label: string; end: boolean; soon?: boolean; soonMsg?: string }[] = [
  { to: "/", label: "INÍCIO", end: true },
  { to: "/leaderboard", label: "LEADERBOARD", end: false },
  { to: "/duo", label: "ACHE SEU DUO", end: false, soon: true, soonMsg: "Ache seu Duo chega em breve" },
  { to: "/campeonatos", label: "CAMPEONATOS", end: false, soon: true, soonMsg: "Campeonatos chegam em breve" },
  { to: "/campeoes", label: "CAMPEÕES", end: false },
  // Mesmo gate do CAMPEÕES de propósito: os três formam um cluster só (campeões
  // → augments → sinergias). Abrir um sem os outros deixa a navegação manca.
  { to: "/augments", label: "AUGMENTS", end: false },
  { to: "/sinergias", label: "SINERGIAS", end: false },
];

/**
 * Busca global do header com typeahead (mesma fonte da busca da tabela:
 * `GET /players/search`). Digita (debounce ~220ms, mín. 2 chars) → dropdown
 * sob o input; clique/Enter abre `/perfil/{riotId}`; ↑/↓ percorrem; Esc/clique
 * fora fecham. Sem resultados mas com "Nome#TAG" digitado, Enter abre direto.
 * `autoFocus` foca ao montar (usado no sheet mobile); `onNavigate` avisa o pai
 * para fechar o overlay após abrir um perfil.
 */
function HeaderSearch({
  navigate,
  autoFocus,
  onNavigate,
}: {
  navigate: NavigateFunction;
  autoFocus?: boolean;
  onNavigate?: () => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchPlayer[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [loading, setLoading] = useState(false);
  const boxRef = useRef<HTMLFormElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const reqId = useRef(0); // descarta respostas fora de ordem

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);

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
        .searchPlayers({ q, format: "3v3", limit: 7 })
        .then((rows) => {
          if (myId !== reqId.current) return;
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
    }, 220);
    return () => window.clearTimeout(t);
  }, [query]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  function go(p: SearchPlayer) {
    setOpen(false);
    setQuery("");
    setResults([]);
    navigate(`/perfil/${encodeURIComponent(p.riotId)}`);
    onNavigate?.();
  }

  function onKeyDown(e: ReactKeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      setOpen(false);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (results.length) {
        setOpen(true);
        setActive((i) => Math.min(results.length - 1, i + 1));
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const pick = results[active] ?? results[0];
    if (pick) {
      go(pick);
    } else if (query.includes("#")) {
      navigate(`/perfil/${encodeURIComponent(query.trim())}`);
      onNavigate?.();
    }
  }

  const showPanel = open && query.trim().length >= 2;

  return (
    <form className="h3-search" onSubmit={onSubmit} role="search" ref={boxRef}>
      <span className="mi">search</span>
      <input
        ref={inputRef}
        type="text"
        placeholder="Busque jogadores com Nick#Tagline, campeões, campeonatos, etc..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => {
          if (results.length) setOpen(true);
        }}
        onKeyDown={onKeyDown}
        role="combobox"
        aria-expanded={showPanel}
        aria-autocomplete="list"
        aria-controls="h3s-list"
      />
      <button className="go" type="submit" aria-label="Buscar">
        <span className="mi">arrow_forward</span>
      </button>
      <span className="br">
        <span className="mi" style={{ fontSize: 16 }}>
          expand_more
        </span>
        BR
      </span>
      {showPanel && (
        <div className="h3s-pop" id="h3s-list" role="listbox">
          {results.length === 0 ? (
            <div className="h3s-empty">
              <span className="mi">{loading ? "hourglass_top" : "person_search"}</span>
              {loading ? "Buscando jogadores…" : "Nenhum jogador encontrado"}
            </div>
          ) : (
            <>
              {results.map((p, i) => (
                <button
                  key={p.riotId}
                  type="button"
                  className={`h3s-item${i === active ? " is-active" : ""}`}
                  role="option"
                  aria-selected={i === active}
                  onMouseEnter={() => setActive(i)}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    go(p);
                  }}
                >
                  <PlayerAvatar colors={p.avatar} url={p.profileIconUrl} alt={p.name} size={36} />
                  <div className="h3s-id">
                    <div className="nm">
                      {p.name}
                      <span className="tag">{p.handle}</span>
                    </div>
                    <div className="meta">
                      <span className="rk">#{nf(p.rank)}</span>
                      {TIER_LABEL[p.tier] ? <span className="tr">{TIER_LABEL[p.tier]}</span> : null}
                    </div>
                  </div>
                  <div className="h3s-cr">
                    {nf(p.cr)}
                    <span className="u">PDL</span>
                  </div>
                </button>
              ))}
              <div className="h3s-foot">
                <kbd>↑</kbd>
                <kbd>↓</kbd>
                navegar
                <span className="dot">·</span>
                <kbd>↵</kbd>
                abrir
                <span className="dot">·</span>
                <kbd>esc</kbd>
                fechar
              </div>
            </>
          )}
        </div>
      )}
    </form>
  );
}

/** Modos de jogo — compartilhado entre o tier 1 (desktop) e o drawer (mobile). */
function GameModes() {
  return (
    <nav className="gm-tabs" aria-label="Modos">
      <span className="gm-tab on">
        <span className="gi" style={{ backgroundImage: "url(/assets/fig/icon-arena.png)" }} />
        <span className="gl">
          ARENA<sup>3V3</sup>
        </span>
      </span>
      <span className="gm-tab">
        <span className="gi" style={{ backgroundImage: "url(/assets/fig/icon-aram.png)" }} />
        <span className="gl">ARAM MAYHEM</span>
      </span>
    </nav>
  );
}

export function Header() {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  // Toast "em breve" — login/perfil ainda não implementados (OAuth virá depois).
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);

  // Overlays mobile: menu (drawer lateral) e busca (sheet full-width).
  const [menuOpen, setMenuOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);

  function showComingSoon(msg: string) {
    setToast(msg);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 3200);
  }

  useEffect(() => () => window.clearTimeout(toastTimer.current), []);

  // Navegar fecha qualquer overlay aberto.
  useEffect(() => {
    setMenuOpen(false);
    setSearchOpen(false);
  }, [pathname]);

  // Trava o scroll do body enquanto um overlay mobile está aberto.
  useEffect(() => {
    const lock = menuOpen || searchOpen;
    const prev = document.body.style.overflow;
    document.body.style.overflow = lock ? "hidden" : prev;
    return () => {
      document.body.style.overflow = prev;
    };
  }, [menuOpen, searchOpen]);

  // Esc fecha; ao abrir o drawer, move o foco para dentro dele.
  useEffect(() => {
    if (!menuOpen && !searchOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setMenuOpen(false);
        setSearchOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    if (menuOpen) drawerRef.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen, searchOpen]);

  return (
    <header className="h3">
      {/* Barra mobile (≤ 900px): logo + busca + menu. Escondida no desktop. */}
      <div className="h3-mobile">
        <Link className="gm-logo" to="/" aria-label="ArenaRank — início">
          <img src="/assets/fig/logo-wordmark.png" alt="ArenaRank" />
        </Link>
        <div className="h3m-actions">
          <button
            className={`h3m-icon${searchOpen ? " on" : ""}`}
            type="button"
            aria-label={searchOpen ? "Fechar busca" : "Buscar"}
            aria-expanded={searchOpen}
            onClick={() => {
              setSearchOpen((v) => !v);
              setMenuOpen(false);
            }}
          >
            <span className="mi">{searchOpen ? "close" : "search"}</span>
          </button>
          <button
            className={`h3m-icon${menuOpen ? " on" : ""}`}
            type="button"
            aria-label={menuOpen ? "Fechar menu" : "Abrir menu"}
            aria-expanded={menuOpen}
            onClick={() => {
              setMenuOpen((v) => !v);
              setSearchOpen(false);
            }}
          >
            <span className="mi">{menuOpen ? "close" : "menu"}</span>
          </button>
        </div>
      </div>

      {/* Sheet de busca mobile — o mesmo typeahead, em largura cheia. */}
      {searchOpen && (
        <div className="h3m-searchsheet">
          <HeaderSearch navigate={navigate} autoFocus onNavigate={() => setSearchOpen(false)} />
        </div>
      )}

      {/* Tier 1: Logo + game mode tabs (desktop) */}
      <div className="h3-row h3-1">
        <Link className="gm-logo" to="/">
          <img src="/assets/fig/logo-wordmark.png" alt="ArenaRank" />
        </Link>
        <GameModes />
      </div>

      {/* Tier 2: Search + actions (desktop) */}
      <div className="h3-row h3-2">
        <HeaderSearch navigate={navigate} />
        <div className="h3-actions">
          <Link className="perfil-gold" to="/leaderboard">
            <span className="ico" />
            LEADERBOARD
          </Link>
          <Link className="trophy" to="/campeonatos" aria-label="Campeonatos">
            <span className="mi fill">emoji_events</span>
          </Link>
          <button
            className="btn-perfil"
            type="button"
            onClick={() => showComingSoon("Perfil chega em breve")}
          >
            PERFIL
          </button>
          <button
            className="btn-entrar"
            type="button"
            onClick={() => showComingSoon("Login chega em breve")}
          >
            ENTRAR
          </button>
        </div>
      </div>

      {/* Tier 3: Mini mode + navigation (desktop) */}
      <div className="h3-row h3-3">
        <nav className="h3-nav" aria-label="Principal">
          {NAV.map((n) =>
            n.soon ? (
              <button
                key={n.to}
                type="button"
                className="nav-soon"
                title={n.soonMsg ?? "Em breve"}
                aria-disabled="true"
                onClick={() => showComingSoon(n.soonMsg ?? "Em breve")}
              >
                <s>{n.label}</s>
                <span className="soon-badge">em breve</span>
              </button>
            ) : (
              <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? "active" : "")}>
                {n.label}
              </NavLink>
            ),
          )}
        </nav>
      </div>

      {/* Camada fixa do tamanho da viewport que CLIPA o drawer fora da tela.
          Necessária porque o drawer é position:fixed e `overflow:clip` no <html>
          não clipa elementos fixed → o drawer fechado (translateX(100%)) somava
          largura fantasma à direita em toda página (cards "comidos" no iOS). */}
      <div className="h3-drawer-layer" data-open={menuOpen}>
      <div
        className="h3-backdrop"
        data-open={menuOpen}
        onClick={() => setMenuOpen(false)}
        aria-hidden="true"
      />
      <aside
        className="h3-drawer"
        data-open={menuOpen}
        role="dialog"
        aria-modal="true"
        aria-label="Menu de navegação"
        aria-hidden={!menuOpen}
        tabIndex={-1}
        ref={drawerRef}
      >
        <div className="h3d-head">
          <span className="h3d-title">Menu</span>
          <button
            className="h3m-icon"
            type="button"
            aria-label="Fechar menu"
            onClick={() => setMenuOpen(false)}
          >
            <span className="mi">close</span>
          </button>
        </div>

        <GameModes />

        <nav className="h3d-nav" aria-label="Navegação">
          {NAV.map((n) =>
            n.soon ? (
              <button
                key={n.to}
                type="button"
                className="h3d-link soon"
                onClick={() => showComingSoon(n.soonMsg ?? "Em breve")}
              >
                <s>{n.label}</s>
                <span className="soon-badge">em breve</span>
              </button>
            ) : (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) => `h3d-link${isActive ? " active" : ""}`}
              >
                {n.label}
                <span className="mi">chevron_right</span>
              </NavLink>
            ),
          )}
        </nav>

        <div className="h3d-actions">
          <Link className="perfil-gold" to="/leaderboard">
            <span className="ico" />
            LEADERBOARD
          </Link>
          <Link className="trophy" to="/campeonatos" aria-label="Campeonatos">
            <span className="mi fill">emoji_events</span>
            <span className="lbl">Campeonatos</span>
          </Link>
          <button
            className="btn-perfil"
            type="button"
            onClick={() => showComingSoon("Perfil chega em breve")}
          >
            PERFIL
          </button>
          <button
            className="btn-entrar"
            type="button"
            onClick={() => showComingSoon("Login chega em breve")}
          >
            ENTRAR
          </button>
        </div>

        <div className="h3d-region">
          <span className="mi">public</span>
          Região <b>BR</b>
        </div>
      </aside>
      </div>

      {toast && (
        <div className="h3-toast" role="status" aria-live="polite">
          <span className="mi fill" aria-hidden="true">
            construction
          </span>
          {toast}
        </div>
      )}
    </header>
  );
}
