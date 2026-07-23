import {
  useState,
  useRef,
  useEffect,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { Link, NavLink, useNavigate, type NavigateFunction } from "react-router-dom";
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

const NAV: { to: string; label: string; end: boolean; soon?: boolean }[] = [
  { to: "/", label: "INICIO", end: true },
  { to: "/leaderboard", label: "LEADERBOARD", end: false },
  { to: "/duo", label: "ACHE SEU DUO", end: false, soon: true },
  { to: "/campeonatos", label: "CAMPEONATOS", end: false },
  { to: "/sistema", label: "PROBUILDS", end: false },
];

/**
 * Busca global do header com typeahead (mesma fonte da busca da tabela:
 * `GET /players/search`). Digita (debounce ~220ms, mín. 2 chars) → dropdown
 * sob o input; clique/Enter abre `/perfil/{riotId}`; ↑/↓ percorrem; Esc/clique
 * fora fecham. Sem resultados mas com "Nome#TAG" digitado, Enter abre direto.
 */
function HeaderSearch({ navigate }: { navigate: NavigateFunction }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchPlayer[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [loading, setLoading] = useState(false);
  const boxRef = useRef<HTMLFormElement>(null);
  const reqId = useRef(0); // descarta respostas fora de ordem

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
    if (pick) go(pick);
    else if (query.includes("#")) navigate(`/perfil/${encodeURIComponent(query.trim())}`);
  }

  const showPanel = open && query.trim().length >= 2;

  return (
    <form className="h3-search" onSubmit={onSubmit} role="search" ref={boxRef}>
      <span className="mi">search</span>
      <input
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

export function Header() {
  const navigate = useNavigate();

  // Toast "em breve" — login/perfil ainda não implementados (OAuth virá depois).
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);

  function showComingSoon(msg: string) {
    setToast(msg);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 3200);
  }

  useEffect(() => () => window.clearTimeout(toastTimer.current), []);

  return (
    <header className="h3">
      {/* Tier 1: Logo + game mode tabs */}
      <div className="h3-row h3-1">
        <Link className="gm-logo" to="/">
          <img src="/assets/fig/logo-wordmark.png" alt="ArenaRank" />
        </Link>
        <nav className="gm-tabs" aria-label="Modos">
          <span className="gm-tab on">
            <span className="gi" style={{ backgroundImage: "url(/assets/fig/icon-arena.png)" }} />
            <span className="gl">ARENA<sup>3V3</sup></span>
          </span>
          <span className="gm-tab">
            <span className="gi" style={{ backgroundImage: "url(/assets/fig/icon-aram.png)" }} />
            <span className="gl">ARAM MAYHEM</span>
          </span>
        </nav>
      </div>

      {/* Tier 2: Search + actions */}
      <div className="h3-row h3-2">
        <HeaderSearch navigate={navigate} />
        <div className="h3-actions">
          <Link className="perfil-gold" to="/leaderboard">
            <span className="ico" />LEADERBOARD
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

      {/* Tier 3: Mini mode + navigation */}
      <div className="h3-row h3-3">
        <nav className="h3-nav" aria-label="Principal">
          {NAV.map((n) =>
            n.soon ? (
              <button
                key={n.to}
                type="button"
                className="nav-soon"
                title="Ache seu Duo chega em breve"
                aria-disabled="true"
                onClick={() => showComingSoon("Ache seu Duo chega em breve")}
                style={{
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  font: "inherit",
                  color: "inherit",
                  opacity: 0.5,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: 0,
                }}
              >
                <s>{n.label}</s>
                <span
                  style={{
                    fontSize: 9,
                    fontWeight: 800,
                    letterSpacing: 0.5,
                    lineHeight: 1,
                    background: "var(--gold, #d9b25f)",
                    color: "#141414",
                    borderRadius: 4,
                    padding: "2px 5px",
                    textTransform: "uppercase",
                  }}
                >
                  em breve
                </span>
              </button>
            ) : (
              <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => isActive ? "active" : ""}>
                {n.label}
              </NavLink>
            ),
          )}
        </nav>
      </div>

      {toast && (
        <div className="h3-toast" role="status" aria-live="polite">
          <span className="mi fill" aria-hidden="true">construction</span>
          {toast}
        </div>
      )}
    </header>
  );
}
