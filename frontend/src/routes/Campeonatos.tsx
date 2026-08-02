/* ============================================================
   Campeonatos (Chaves) — porta fiel do design HTML+JS para React.
   Rota: /campeonatos  |  /campeonatos/:id
   ============================================================ */
import "./Campeonatos.css";
import {
  useState,
  useEffect,
  useLayoutEffect,
  useRef,
  useCallback,
  type CSSProperties,
} from "react";
import { createPortal } from "react-dom";
import { useParams, Link } from "react-router-dom";
import { Mi } from "../components/Mi";
import { StateBlock } from "../components/StateBlock";
import { useApi } from "../hooks/useApi";
import { api } from "../lib/api";
import { nf, fmtPrize } from "../lib/format";
import type {
  TournamentMatch,
  StandingRow,
  TeamRoster,
  TournamentMatchResult,
  PlayerSlot,
  AvatarColors,
} from "../lib/types";

/* Conduta padrão (torneios sem regras de conduta próprias, ex.: sample). */
const DEFAULT_CONDUCT = [
  {
    icon: "schedule",
    title: "Check-in 15 min antes",
    desc: "Confirme presença e entre no saguão pelo link magnético; equipes incompletas são desclassificadas.",
  },
  {
    icon: "gavel",
    title: "Penalidades",
    desc: "Atraso, AFK ou conduta antidesportiva descontam pontos do total da equipe.",
  },
];

/* Acesso seguro a PlayerSlot (real | { empty: true }) — mantém os fallbacks do design. */
const EMPTY_AVATAR: AvatarColors = { c1: "#2a4a6a", c2: "#46b4ec" };
const slotName = (p?: PlayerSlot): string => (p && "name" in p ? p.name : "");
const slotAvatar = (p?: PlayerSlot): AvatarColors =>
  p && "avatar" in p ? p.avatar : EMPTY_AVATAR;

/* ------------------------------------------------------------------ */
/* Placement points (conforme design e contrato)                        */
/* ------------------------------------------------------------------ */
const PLACEMENT_POINTS: Record<number, number> = {
  1: 14,
  2: 10,
  3: 8,
  4: 6,
  5: 4,
  6: 2,
};

/* ------------------------------------------------------------------ */
/* Helpers                                                              */
/* ------------------------------------------------------------------ */
function avatarBg(c1: string, c2: string): string {
  return `radial-gradient(circle at 30% 30%, ${c1}, ${c2} 75%)`;
}

/* ------------------------------------------------------------------ */
/* Equalizer (barras ao vivo — SEM texto)                               */
/* ------------------------------------------------------------------ */
function Equalizer({ className = "" }: { className?: string }) {
  return (
    <span className={`eq${className ? " " + className : ""}`} aria-hidden="true">
      <i />
      <i />
      <i />
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Toast manager                                                        */
/* ------------------------------------------------------------------ */
interface ToastItem {
  id: number;
  title: string;
  sub: string;
  show: boolean;
}

/* Overlays de viewport saem para o <body>: a rota vive dentro do #smooth-content,
   que o ScrollSmoother transforma — e transform faz `position: fixed` descendente
   se comportar como `absolute`, o que deixaria scrim e toasts rolando com a página. */
function ToastWrap({ toasts }: { toasts: ToastItem[] }) {
  return createPortal(
    <div className="toast-wrap">
      {toasts.map((t) => (
        <div key={t.id} className={`toast${t.show ? " show" : ""}`}>
          <div className="t-icon">
            <Mi name="check" />
          </div>
          <div>
            <div className="t-t">{t.title}</div>
            <div className="t-s">{t.sub}</div>
          </div>
        </div>
      ))}
    </div>,
    document.body,
  );
}

/* ------------------------------------------------------------------ */
/* Match cards                                                          */
/* ------------------------------------------------------------------ */
interface MatchCardProps {
  match: TournamentMatch;
  winnerName?: string;
  winnerBadge?: string;
  joined: boolean;
  /** Trancada até a partida anterior finalizar (sem contador). */
  locked: boolean;
  onEnterLobby: (n: number) => void;
}

function MatchCard({
  match,
  winnerName,
  winnerBadge,
  joined,
  locked,
  onEnterLobby,
}: MatchCardProps) {
  const pct =
    match.lobbyMax > 0
      ? Math.round((match.lobbyCount / match.lobbyMax) * 100)
      : 0;
  // upcoming + trancada (anterior não terminou) · upcoming + liberada (pronta p/ iniciar)
  const upcomingLocked = match.status === "upcoming" && locked;
  const upcomingReady = match.status === "upcoming" && !locked;

  return (
    <div className="match-card" data-state={match.status} data-locked={upcomingLocked ? "true" : "false"}>
      <div className="m-top">
        <span className="m-no">Partida {match.n}</span>

        {match.status === "ended" && (
          <span className="m-status finished">
            <Mi name="check_circle" style={{ fontSize: 14, marginRight: 4, verticalAlign: "-2px" }} />
            Encerrada
          </span>
        )}
        {match.status === "live" && (
          <span className="m-status live" title="Partida em andamento">
            <Equalizer />
          </span>
        )}
        {upcomingReady && (
          <span className="m-status ready">
            <Mi name="lock_open" style={{ fontSize: 14, marginRight: 4, verticalAlign: "-2px" }} />
            A seguir
          </span>
        )}
        {upcomingLocked && (
          <span className="m-status locked">
            <Mi name="lock" style={{ fontSize: 14, marginRight: 4, verticalAlign: "-2px" }} />
            Trancada
          </span>
        )}
      </div>

      {/* corpo */}
      <div className="m-body">
        {match.status === "ended" && (
          <>
            <div className="m-winner-label">Vencedora</div>
            <div className="m-winner">
              <div
                className="wbadge"
                style={{ background: winnerBadge ?? "var(--surface-3)" } as CSSProperties}
              >
                <span className="crown">★</span>
              </div>
              <div>
                <div className="wname">{winnerName ?? "—"}</div>
                <div className="wsub">+{PLACEMENT_POINTS[1]} pts · 1º lugar</div>
              </div>
            </div>
          </>
        )}

        {match.status === "live" && (
          <div className="m-live-info">
            <div className="m-winner-label">Saguão preenchendo</div>
            <div className="lobby-count">
              <b>{match.lobbyCount}</b>
              <span>/{match.lobbyMax} no saguão</span>
            </div>
            <div className="m-progress">
              <i style={{ width: `${pct}%` }} />
            </div>
          </div>
        )}

        {upcomingReady && (
          <div className="m-wait">
            <Mi name="hourglass_top" className="m-wait-ic" />
            <div className="m-wait-t">Aguardando início</div>
            <div className="m-wait-s">A organização abre o saguão</div>
          </div>
        )}

        {upcomingLocked && (
          <div className="m-wait">
            <Mi name="lock" className="m-wait-ic" />
            <div className="m-wait-t">Trancada</div>
            <div className="m-wait-s">Liberada ao fim da Partida {match.n - 1}</div>
          </div>
        )}
      </div>

      {/* rodapé */}
      <div className="m-foot">
        {match.status === "ended" && (
          <button className="magnet-btn disabled" type="button" disabled>
            Resultado registrado
          </button>
        )}
        {match.status === "live" && (
          <button
            className={`magnet-btn${joined ? " joined" : ""}`}
            type="button"
            onClick={() => !joined && onEnterLobby(match.n)}
          >
            {joined ? "No saguão" : "Entrar no saguão"}
          </button>
        )}
        {upcomingReady && (
          <button className="magnet-btn disabled" type="button" disabled>
            Aguardando início
          </button>
        )}
        {upcomingLocked && (
          <button className="magnet-btn locked" type="button" disabled>
            <Mi name="lock" style={{ fontSize: 14, marginRight: 6, verticalAlign: "-2px" }} />
            Trancada
          </button>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Ranking table                                                         */
/* ------------------------------------------------------------------ */
function RankTable({
  standings,
  matches,
  onGotoInscritos,
}: {
  standings: StandingRow[];
  matches: TournamentMatch[];
  onGotoInscritos: (teamId: string) => void;
}) {
  const namesRef = useRef<Map<string, HTMLDivElement>>(new Map());
  // Quais rosters têm nomes que estouram a largura → mostram a pílula "elenco".
  // Medido após o layout e guardado em estado, em vez de mutar o DOM na mão
  // (o que vazava listeners e rodava a cada render, sem array de dependências).
  const [overflow, setOverflow] = useState<Record<string, boolean>>({});

  useLayoutEffect(() => {
    const next: Record<string, boolean> = {};
    namesRef.current.forEach((el, teamId) => {
      if (el.scrollWidth > el.clientWidth + 1) next[teamId] = true;
    });
    setOverflow((prev) => {
      const nk = Object.keys(next);
      if (nk.length === Object.keys(prev).length && nk.every((k) => prev[k])) return prev;
      return next;
    });
  }, [standings, matches]);

  return (
    <div className="rank-table">
      {/* cabeçalho */}
      <div className="rt-row head">
        <div>#</div>
        <div>Equipe</div>
        <div>Jogadores</div>
        {matches.map((m) => (
          <div key={m.n} className="center">P{m.n}</div>
        ))}
        <div className="center">Bônus</div>
        <div className="center">Penal.</div>
        <div className="right">Total</div>
      </div>

      {standings.map((row, i) => {
        const pos = i + 1;
        const posCls = pos <= 3 ? ` p${pos}` : "";

        const perMatchCells = matches.map((m) => {
          const pts = row.perMatch[m.n - 1];
          if (m.status === "ended" && pts != null && pts > 0) {
            return (
              <div key={m.n} className="rt-mpts center">
                {pts}
              </div>
            );
          }
          if (m.status === "live") {
            return (
              <div key={m.n} className="rt-mpts center muted">
                <span className="livedot" title="em andamento" />
              </div>
            );
          }
          return (
            <div key={m.n} className="rt-mpts center muted">
              —
            </div>
          );
        });

        return (
          <div
            key={row.teamId}
            className={`rt-row rt-team-row${row.isYou ? " me" : ""}`}
          >
            <div className="rt-rank">
              <span className={`pos${posCls}`}>{pos}</span>
            </div>

            <div className="rt-team">
              <span
                className="tbadge"
                style={
                  {
                    background: `linear-gradient(135deg, ${slotAvatar(row.players[0]).c1}, ${slotAvatar(row.players[0]).c2})`,
                  } as CSSProperties
                }
              />
              <div className="tinfo">
                <div className="tname">{row.teamName}</div>
                <div className="ttag">
                  #{row.seed}{row.isYou ? " · sua equipe" : ""}
                </div>
              </div>
            </div>

            <div className="rt-players">
              <div
                className={`rt-roster${overflow[row.teamId] ? " truncated" : ""}`}
                data-team={row.teamId}
                title={overflow[row.teamId] ? "Ver elenco completo" : undefined}
                role={overflow[row.teamId] ? "button" : undefined}
                tabIndex={overflow[row.teamId] ? 0 : undefined}
                onClick={overflow[row.teamId] ? () => onGotoInscritos(row.teamId) : undefined}
                onKeyDown={
                  overflow[row.teamId]
                    ? (e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onGotoInscritos(row.teamId);
                        }
                      }
                    : undefined
                }
              >
                <div className="rt-avs">
                  {row.players.map((p, idx) => (
                    <span
                      key={idx}
                      className={`ra${slotName(p) === "Você" ? " me-av" : ""}`}
                      style={
                        {
                          background: avatarBg(slotAvatar(p).c1, slotAvatar(p).c2),
                        } as CSSProperties
                      }
                    />
                  ))}
                </div>
                <div
                  className="rt-names"
                  ref={(el) => {
                    if (el) namesRef.current.set(row.teamId, el);
                    else namesRef.current.delete(row.teamId);
                  }}
                >
                  {row.players.map((p, idx) => (
                    <span key={idx}>
                      {idx > 0 && <i className="sep-dot">·</i>}
                      <span className={row.isYou && idx === 0 ? "me-name" : ""}>
                        {slotName(p)}
                      </span>
                    </span>
                  ))}
                </div>
                {overflow[row.teamId] && <span className="roster-more">elenco</span>}
              </div>
            </div>

            {perMatchCells}

            <div className={`rt-bonus center`}>
              {row.bonus > 0 ? `+${row.bonus}` : "0"}
            </div>
            <div className={`rt-pen center${row.penalties === 0 ? " zero" : ""}`}>
              {row.penalties === 0 ? "0" : `−${row.penalties}`}
            </div>
            <div className="rt-total right">
              {row.total}
              <span className="lp">pts</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Lobby Modal                                                           */
/* ------------------------------------------------------------------ */
interface LobbyMember {
  nick: string;
  c1: string;
  c2: string;
  isMe: boolean;
  present: boolean;
}

interface LobbyModalProps {
  open: boolean;
  matchN: number;
  cap: number;
  initialCount: number;
  magneticLink: string;
  members: LobbyMember[];
  joined: boolean;
  onClose: () => void;
  onEnter: () => void;
  onCopyLink: () => void;
}

function LobbyModal({
  open,
  matchN,
  cap,
  members,
  joined,
  onClose,
  onEnter,
  onCopyLink,
}: LobbyModalProps) {
  const now = members.filter((m) => m.present).length;
  const pct = cap > 0 ? Math.round((now / cap) * 100) : 0;
  const allOthersIn = members.filter((m) => !m.isMe).every((m) => m.present);
  const stateText = joined
    ? "Você entrou"
    : allOthersIn
    ? "Pronto — entre agora"
    : "Preenchendo…";
  const stateReady = joined || allOthersIn;

  // fechar com Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  return createPortal(
    <div
      className={`modal-scrim${open ? " open" : ""}`}
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
      onClick={(e) => {
        if ((e.target as HTMLElement).classList.contains("modal-scrim")) onClose();
      }}
    >
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="mh-icon" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#4cb6ec" strokeWidth="2" strokeLinecap="round">
              <path d="M9 12h6M8.5 8H7a4 4 0 0 0 0 8h1.5M15.5 8H17a4 4 0 0 1 0 8h-1.5" />
            </svg>
          </div>
          <div>
            <div className="mh-t" id="modal-title">
              Saguão · Partida {matchN}
            </div>
            <div className="mh-s">Link magnético · campeonato</div>
          </div>
          <button
            type="button"
            className="mh-close"
            aria-label="Fechar"
            onClick={onClose}
          >
            ×
          </button>
        </div>

        <div className="modal-body">
          <div className="lobby-meter">
            <div className="lm-count">
              <b>{now}</b>
              <span>/{cap} jogadores no saguão</span>
            </div>
            <div className={`lm-state${stateReady ? " ready" : ""}`}>
              {stateText}
            </div>
          </div>

          <div className="lobby-bar">
            <i style={{ width: `${pct}%` }} />
          </div>

          <div className="lobby-grid">
            {members.map((mem, idx) => (
              <div
                key={idx}
                className={`lobby-slot${mem.present ? " filled" : ""}${mem.isMe ? " me" : ""}`}
              >
                <div
                  className="ls-av"
                  style={{ background: avatarBg(mem.c1, mem.c2) } as CSSProperties}
                />
                <span className="ls-tag">{mem.isMe ? "Você" : mem.nick}</span>
              </div>
            ))}
          </div>

          <div className="modal-foot">
            <button
              type="button"
              className={`btn-enter${joined ? " done" : ""}`}
              onClick={onEnter}
              disabled={joined}
            >
              {joined ? "Você está no saguão" : "Entrar na partida"}
            </button>
            <button type="button" className="btn-copy" onClick={onCopyLink}>
              <Mi name="content_copy" style={{ fontSize: 14 }} />
              Copiar link
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/* ------------------------------------------------------------------ */
/* Campeonatos — página principal                                        */
/* ------------------------------------------------------------------ */
export function Campeonatos({ tourneyIdOverride }: { tourneyIdOverride?: string } = {}) {
  const { id } = useParams<{ id?: string }>();

  // Lista de campeonatos provisionados (via admin). Sem id explícito na URL, abre
  // o mais recente; se não houver nenhum, renderiza um estado vazio honesto.
  const list = useApi(() => api.tournaments(), []);
  const resolvedId = tourneyIdOverride ?? id ?? list.data?.[0]?.id;

  const { data, loading, error } = useApi(
    () => (resolvedId ? api.tournament(resolvedId) : Promise.resolve(null)),
    [resolvedId],
  );

  const [activeTab, setActiveTab] = useState<
    "chaves" | "regras" | "premiacao" | "inscritos" | "historico"
  >("chaves");

  // lobby state
  const [lobbyOpen, setLobbyOpen] = useState(false);
  const [lobbyMatchN, setLobbyMatchN] = useState(0);
  const [lobbyMembers, setLobbyMembers] = useState<LobbyMember[]>([]);
  const [lobbyJoined, setLobbyJoined] = useState(false);
  const lobbyTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // sidebar player status
  const [playerStatus, setPlayerStatus] = useState<"waiting" | "lobby">("waiting");
  const [playerStatusText, setPlayerStatusText] = useState("Aguardando início da partida");

  // toasts
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const toastCounter = useRef(0);

  // inscritos highlight ref map
  const inscritoRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const matchesRef = useRef<HTMLDivElement>(null);

  function scrollMatches(dir: -1 | 1) {
    matchesRef.current?.scrollBy({ left: dir * 320, behavior: "smooth" });
  }

  function addToast(title: string, sub: string) {
    const id = ++toastCounter.current;
    setToasts((prev) => [...prev, { id, title, sub, show: false }]);
    // trigger show on next frame
    requestAnimationFrame(() => {
      setToasts((prev) =>
        prev.map((t) => (t.id === id ? { ...t, show: true } : t)),
      );
    });
    setTimeout(() => {
      setToasts((prev) =>
        prev.map((t) => (t.id === id ? { ...t, show: false } : t)),
      );
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, 350);
    }, 4200);
  }

  // build lobby members from registrations
  const buildMembers = useCallback(
    (registrations: TeamRoster[]): LobbyMember[] => {
      const members: LobbyMember[] = [];
      for (const team of registrations) {
        for (const p of team.players) {
          members.push({
            nick: slotName(p),
            c1: slotAvatar(p).c1,
            c2: slotAvatar(p).c2,
            isMe: team.isYou === true && slotName(p) === team.captain,
            present: false,
          });
        }
      }
      return members;
    },
    [],
  );

  const openLobby = useCallback(
    (matchN: number) => {
      if (!data) return;
      const m = data.matches.find((x) => x.n === matchN);
      if (!m || m.status !== "live") return;

      setLobbyMatchN(matchN);
      setLobbyJoined(false);

      const members = buildMembers(data.registrations);
      // seed initial present count (non-me players)
      let count = 0;
      for (const mem of members) {
        if (mem.isMe) continue;
        if (count < m.lobbyCount) {
          mem.present = true;
          count++;
        }
      }
      setLobbyMembers([...members]);
      setLobbyOpen(true);

      // simulate trickle
      if (lobbyTimerRef.current) clearInterval(lobbyTimerRef.current);
      lobbyTimerRef.current = setInterval(() => {
        setLobbyMembers((prev) => {
          const empty = prev.filter((x) => !x.present && !x.isMe);
          if (empty.length === 0) {
            if (lobbyTimerRef.current) clearInterval(lobbyTimerRef.current);
            return prev;
          }
          const pick = empty[Math.floor(Math.random() * empty.length)];
          return prev.map((x) =>
            x === pick ? { ...x, present: true } : x,
          );
        });
      }, 1300);
    },
    [data, buildMembers],
  );

  const closeLobby = useCallback(() => {
    setLobbyOpen(false);
    if (lobbyTimerRef.current) clearInterval(lobbyTimerRef.current);
  }, []);

  const enterMatch = useCallback(() => {
    if (lobbyJoined) return;
    setLobbyJoined(true);
    setLobbyMembers((prev) =>
      prev.map((m) => (m.isMe ? { ...m, present: true } : m)),
    );
    setPlayerStatus("lobby");
    const total = lobbyMembers.length;
    const now = lobbyMembers.filter((m) => m.present).length + 1;
    setPlayerStatusText(`No saguão da Partida ${lobbyMatchN} · ${now}/${total} jogadores`);
    addToast("Você entrou no saguão!", `Partida ${lobbyMatchN} começando · ${now}/${total} jogadores presentes`);
  }, [lobbyJoined, lobbyMatchN, lobbyMembers]);

  const copyLink = useCallback(() => {
    const m = data?.matches.find((x) => x.n === lobbyMatchN);
    if (m?.magneticLink) {
      navigator.clipboard.writeText(m.magneticLink).catch(() => {});
    }
    addToast("Link magnético copiado", "Compartilhe com sua equipe para entrarem juntos no saguão");
  }, [data, lobbyMatchN]);

  // update sidebar status as lobby fills
  useEffect(() => {
    if (!lobbyJoined) return;
    const total = lobbyMembers.length;
    const now = lobbyMembers.filter((m) => m.present).length;
    if (lobbyMembers.every((m) => m.present)) {
      setPlayerStatusText("Saguão completo · 18/18 — entrando na partida");
    } else {
      setPlayerStatusText(`No saguão da Partida ${lobbyMatchN} · ${now}/${total} jogadores`);
    }
  }, [lobbyMembers, lobbyJoined, lobbyMatchN]);

  // cleanup
  useEffect(() => () => {
    if (lobbyTimerRef.current) clearInterval(lobbyTimerRef.current);
  }, []);

  function gotoInscritos(teamId: string) {
    setActiveTab("inscritos");
    setTimeout(() => {
      const el = inscritoRefs.current.get(teamId);
      if (el) {
        const y = el.getBoundingClientRect().top + window.scrollY - 90;
        window.scrollTo({ top: y, behavior: "smooth" });
        el.classList.remove("flash");
        void el.offsetWidth;
        el.classList.add("flash");
        setTimeout(() => el.classList.remove("flash"), 1800);
      }
    }, 80);
  }

  // ----- derive winner badge color from standings/registrations -----
  function winnerBadgeBg(winnerTeamId?: string): string {
    if (!winnerTeamId || !data) return "var(--surface-3)";
    const reg = data.registrations.find((r) => r.teamId === winnerTeamId);
    if (reg && reg.players[0]) {
      return `linear-gradient(135deg, ${slotAvatar(reg.players[0]).c1}, ${slotAvatar(reg.players[0]).c2})`;
    }
    return "var(--surface-3)";
  }

  function winnerTeamName(winnerTeamId?: string): string {
    if (!winnerTeamId || !data) return "—";
    return (
      data.standings.find((s) => s.teamId === winnerTeamId)?.teamName ??
      data.registrations.find((r) => r.teamId === winnerTeamId)?.teamName ??
      "—"
    );
  }

  // live match for derived state
  const liveMatch = data?.matches.find((m) => m.status === "live");

  // my team
  const myStanding = data?.standings.find((s) => s.isYou);
  const myRank = myStanding
    ? data!.standings.indexOf(myStanding) + 1
    : null;
  const myPoints = myStanding
    ? myStanding.perMatch.reduce((acc, p) => acc + (p ?? 0), 0) + (myStanding.bonus ?? 0)
    : 0;

  // Sem torneio resolvido (nenhum provisionado) → estado vazio honesto. Todos os
  // hooks já rodaram acima, então o retorno antecipado aqui é seguro.
  if (!resolvedId) {
    return (
      <div className="page-camp">
        <section className="main" data-screen-label="Campeonatos">
          <StateBlock loading={list.loading} error={list.error}>
            <div className="camp-empty" style={{ padding: "64px 24px", textAlign: "center" }}>
              <h1>Campeonatos</h1>
              <p style={{ marginTop: 12, opacity: 0.7 }}>
                Nenhum campeonato ativo no momento. Volte em breve.
              </p>
            </div>
          </StateBlock>
        </section>
      </div>
    );
  }

  return (
    <div className="page-camp">
      {/* ===== COLUNA PRINCIPAL ===== */}
      <section className="main" data-screen-label="Campeonatos · Chaves">
        <StateBlock loading={loading} error={error}>
          {data && (
            <>
              {/* tournament hero */}
              <div className="thero">
                <div>
                  <div className="crumbs">
                    <Link to="/">Início</Link>
                    <span className="sep">›</span>
                    <Link to="/campeonatos">Campeonatos</Link>
                    <span className="sep">›</span>
                    <span>{data.title}</span>
                  </div>
                  <h1>{data.title}</h1>
                  <div className="badges">
                    {data.status === "live" && (
                      <span className="pill live">
                        <Equalizer />
                        <span>
                          {liveMatch
                            ? lobbyJoined
                              ? `Você está no saguão da Partida ${liveMatch.n}`
                              : `Partida ${liveMatch.n}`
                            : "Ao vivo"}
                        </span>
                      </span>
                    )}
                    <span className="pill">
                      {data.registrations.length} equipes ·{" "}
                      {data.registrations.reduce((a, r) => a + r.players.length, 0)} jogadores
                    </span>
                    <span className="pill">Formato pontos corridos</span>
                    <span className="pill">{data.matches.length} partidas</span>
                    {data.rules.schedule && (
                      <span className="pill">
                        <Mi name="schedule" style={{ fontSize: 13, marginRight: 4, verticalAlign: -2 }} />
                        {data.rules.schedule}
                      </span>
                    )}
                    {data.rules.entry?.fee && (
                      <span className="pill">
                        <Mi name="payments" style={{ fontSize: 13, marginRight: 4, verticalAlign: -2 }} />
                        Inscrição {data.rules.entry.fee}
                      </span>
                    )}
                  </div>
                </div>
                <div className="prize-block">
                  <div className="amt">
                    {data.currency === "BRL" && <small>R$ </small>}
                    {nf(data.prizeRp)}
                    {data.currency !== "BRL" && <small> RP</small>}
                  </div>
                  <div className="lbl">Premiação total</div>
                </div>
              </div>

              {/* sub tabs */}
              <div className="sub-tabs" role="tablist">
                {(
                  [
                    ["chaves", "Chaves"],
                    ["regras", "Regras"],
                    ["premiacao", "Premiação"],
                    ["inscritos", "Inscritos"],
                    ["historico", "Histórico"],
                  ] as const
                ).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    className={activeTab === key ? "active" : ""}
                    aria-selected={activeTab === key}
                    onClick={() => setActiveTab(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {/* ===== CHAVES ===== */}
              <div className={`tab-panel${activeTab === "chaves" ? " active" : ""}`}>
                <div className="sec-h">
                  <h2>Partidas</h2>
                  <span className="hint">
                    Clique no link magnético da partida ao vivo para entrar no saguão
                  </span>
                </div>
                <div className="matches-carousel">
                  {data.matches.length > 3 && (
                    <button
                      type="button"
                      className="mc-arrow left"
                      onClick={() => scrollMatches(-1)}
                      aria-label="Partidas anteriores"
                    >
                      <Mi name="chevron_left" />
                    </button>
                  )}
                  <div className="matches" ref={matchesRef}>
                    {data.matches.map((m) => (
                      <MatchCard
                        key={m.n}
                        match={m}
                        winnerName={winnerTeamName(m.winnerTeamId)}
                        winnerBadge={winnerBadgeBg(m.winnerTeamId)}
                        joined={lobbyJoined && lobbyMatchN === m.n}
                        // trancada até a partida anterior finalizar (sem contador)
                        locked={m.n > 1 && data.matches[m.n - 2]?.status !== "ended"}
                        onEnterLobby={openLobby}
                      />
                    ))}
                  </div>
                  {data.matches.length > 3 && (
                    <button
                      type="button"
                      className="mc-arrow right"
                      onClick={() => scrollMatches(1)}
                      aria-label="Próximas partidas"
                    >
                      <Mi name="chevron_right" />
                    </button>
                  )}
                </div>

                <div className="sec-h">
                  <h2>Classificação</h2>
                  <span className="hint">Ranking por pontos · penalidades descontadas</span>
                </div>
                <RankTable
                  standings={data.standings}
                  matches={data.matches}
                  onGotoInscritos={gotoInscritos}
                />
                <div className="table-foot">
                  <span className="key">
                    <span className="sw" style={{ background: "var(--gold)" }} />
                    1º–3º lugar
                  </span>
                  <span className="key">
                    <span className="sw" style={{ background: "var(--primary)" }} />
                    sua equipe
                  </span>
                  <span className="key">
                    <span className="sw" style={{ background: "var(--red)" }} />
                    penalidade
                  </span>
                </div>
              </div>

              {/* ===== REGRAS ===== */}
              <div className={`tab-panel${activeTab === "regras" ? " active" : ""}`}>
                <div className="sec-h">
                  <h2>Regras do campeonato</h2>
                  <span className="hint">{data.format} · formato pontos corridos</span>
                </div>
                <div className="rules-grid">
                  <div className="rcard tall">
                    <h3>
                      <span className="ic">
                        <Mi name="format_list_numbered" />
                      </span>
                      Formato e pontuação
                    </h3>
                    <p className="sub">
                      {data.rules.format.join(" · ")}
                    </p>
                    <div className="pts-table">
                      {data.rules.scoring.map(({ place, points }) => (
                        <div key={place} className="pts-row">
                          <span className="pl">
                            <span
                              className={`pos-chip${place <= 3 ? ` p${place}` : ""}`}
                            >
                              {place}
                            </span>
                            {place}º lugar
                          </span>
                          <span className="pp">{points} pts</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="rcard">
                    <h3>
                      <span className="ic">
                        <Mi name="gavel" />
                      </span>
                      Regras e conduta
                    </h3>
                    <div className="rlist">
                      {(data.rules.conduct ?? DEFAULT_CONDUCT).map((c, i) => (
                        <div key={i} className="ritem">
                          <div className="rn"><Mi name={c.icon} style={{ fontSize: 15 }} /></div>
                          <div>
                            <div className="rt2">{c.title}</div>
                            <div className="rd">{c.desc}</div>
                          </div>
                        </div>
                      ))}
                      {data.rules.entry?.fee && (
                        <div className="ritem">
                          <div className="rn"><Mi name="payments" style={{ fontSize: 15 }} /></div>
                          <div>
                            <div className="rt2">Inscrição</div>
                            <div className="rd">
                              {data.rules.entry.fee} por equipe
                              {data.rules.entry.pix ? ` · ${data.rules.entry.pix}` : ""}
                            </div>
                          </div>
                        </div>
                      )}
                      {data.rules.schedule && (
                        <div className="ritem">
                          <div className="rn"><Mi name="schedule" style={{ fontSize: 15 }} /></div>
                          <div>
                            <div className="rt2">Horário</div>
                            <div className="rd">Início às {data.rules.schedule}</div>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="rcard">
                    <h3>
                      <span className="ic">
                        <Mi name="balance" />
                      </span>
                      Critérios de desempate
                    </h3>
                    <div className="rlist">
                      {data.rules.tiebreak.map((tb, i) => (
                        <div key={i} className="ritem">
                          <div className="rn">{i + 1}</div>
                          <div>
                            <div className="rt2">{tb}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* ===== PREMIAÇÃO ===== */}
              <div className={`tab-panel${activeTab === "premiacao" ? " active" : ""}`}>
                <div className="sec-h">
                  <h2>Premiação</h2>
                  <span className="hint">
                    Distribuída conforme a classificação final · dividida entre os jogadores
                  </span>
                </div>
                <div className="prize-hero">
                  <div className="ph-l">
                    <div className="t">Prêmio total</div>
                    <div className="s">{data.prizeLabel}</div>
                  </div>
                  <div className="ph-amt">
                    {data.currency === "BRL" && <small>R$ </small>}
                    {nf(data.prizeRp)}
                    {data.currency !== "BRL" && <small> RP</small>}
                  </div>
                </div>
                {data.rules.prizeNote && (
                  <div className="prize-note">
                    <Mi name="info" style={{ fontSize: 15, color: "var(--amber)" }} />
                    {data.rules.prizeNote}
                  </div>
                )}
                <div className="prize-list">
                  {data.prizes.map((p) => {
                    const medalCls =
                      p.medal === "gold"
                        ? " g"
                        : p.medal === "silver"
                        ? " s"
                        : p.medal === "bronze"
                        ? " b"
                        : "";
                    const isTop = p.medal !== "none";
                    return (
                      <div key={p.place} className={`prize-row${isTop ? " top" : ""}`}>
                        <span className={`medal${medalCls}`}>{p.place}º</span>
                        <span className="plabel">
                          {p.place === 1
                            ? "Campeã"
                            : p.place === 2
                            ? "Vice-campeã"
                            : p.place === 3
                            ? "Terceiro lugar"
                            : `${p.place}º lugar`}
                          {data.prizeRp > 0 && (
                            <small>{Math.round((p.rp / data.prizeRp) * 100)}% da premiação</small>
                          )}
                        </span>
                        <span className="ppl">
                          ÷ {data.registrations[0]?.players.length ?? 3} ·{" "}
                          {fmtPrize(p.perPlayer, data.currency)} cada
                        </span>
                        <span className="pamt">
                          {fmtPrize(p.rp, data.currency)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* ===== INSCRITOS ===== */}
              <div className={`tab-panel${activeTab === "inscritos" ? " active" : ""}`}>
                <div className="sec-h">
                  <h2>Equipes inscritas</h2>
                  <span className="hint">
                    {data.registrations.length} equipes · semeadas por CR
                  </span>
                </div>
                <div className="ins-grid">
                  {data.registrations.map((team, i) => (
                    <div
                      key={team.teamId}
                      id={`ins-${team.teamId}`}
                      className={`ins-card${team.isYou ? " me" : ""}`}
                      ref={(el) => {
                        if (el) inscritoRefs.current.set(team.teamId, el);
                      }}
                    >
                      <div className="ins-top">
                        <span
                          className="tbadge"
                          style={
                            {
                              background: `linear-gradient(135deg, ${slotAvatar(team.players[0]).c1}, ${slotAvatar(team.players[0]).c2})`,
                            } as CSSProperties
                          }
                        />
                        <div>
                          <div className="tname">{team.teamName}</div>
                          <div className="ttag">
                            #{team.seed}{team.isYou ? " · sua equipe" : ""}
                          </div>
                        </div>
                        <span className="seed">Seed #{i + 1}</span>
                      </div>
                      <div className="ins-players">
                        {team.players.map((p, idx) => (
                          <div
                            key={idx}
                            className={`ins-player${team.isYou && slotName(p) === team.captain ? " me-p" : ""}`}
                          >
                            <span
                              className="iav"
                              style={
                                {
                                  background: avatarBg(slotAvatar(p).c1, slotAvatar(p).c2),
                                } as CSSProperties
                              }
                            />
                            <span className="inick">{slotName(p)}</span>
                            {idx === 0 && <span className="cap">Capitã</span>}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* ===== HISTÓRICO ===== */}
              <div className={`tab-panel${activeTab === "historico" ? " active" : ""}`}>
                <div className="sec-h">
                  <h2>Histórico de resultados</h2>
                  <span className="hint">Resultado de cada partida do campeonato</span>
                </div>
                {data.history.map((hm) => (
                  <HistMatchBlock
                    key={hm.n}
                    result={hm}
                    standings={data.standings}
                    registrations={data.registrations}
                  />
                ))}
              </div>
            </>
          )}
        </StateBlock>
      </section>

      {/* ===== SIDEBAR ===== */}
      <aside className="sidebar" aria-label="Seu desempenho no campeonato">
        <StateBlock loading={loading} error={error}>
          {data && myStanding && (
            <div className="pp-card">
              <div className="pp-top">
                <div className="pp-avatar" />
                <div>
                  <div className="pp-name">
                    {slotName(myStanding.players[0]) || myStanding.teamName}
                  </div>
                  <div className="pp-team">
                    <span className="tdot" />
                    <span>{myStanding.teamName} · #{myRank ?? "—"} geral</span>
                  </div>
                </div>
              </div>

              <div className={`pp-status ${playerStatus}`}>
                <span className="s-dot" />
                <span>{playerStatusText}</span>
              </div>

              <div className="pp-stats">
                <div className="pp-stat">
                  <div className="v gold">{myPoints}</div>
                  <div className="l">Pontos no torneio</div>
                </div>
                <div className="pp-stat">
                  <div className="v purple">{myRank != null ? `${myRank}º` : "—"}</div>
                  <div className="l">Posição da equipe</div>
                </div>
                <div className="pp-stat">
                  <div className="v red">{myStanding.penalties}</div>
                  <div className="l">Penalidades</div>
                </div>
              </div>
            </div>
          )}
          {data && !myStanding && (
            <div className="pp-card pp-card-empty">
              <p>Você ainda não está inscrito neste campeonato.</p>
              <button type="button" className="magnet-btn" onClick={() => setActiveTab("inscritos")}>
                Ver equipes inscritas
              </button>
            </div>
          )}
        </StateBlock>

        {data && (
          <>
            {/* histórico de partidas do jogador */}
            <div className="side-h">Histórico da partida</div>
            <div className="log">
              {data.history
                .filter((h) => h.status === "ended")
                .map((h) => {
                  const myResult = h.results.find((r) => {
                    const stand = data.standings.find(
                      (s) => s.isYou && s.teamName === r.teamName,
                    );
                    return !!stand;
                  });
                  if (!myResult) return null;
                  const color =
                    myResult.place === 1
                      ? "var(--gold)"
                      : myResult.place === 2
                      ? "var(--silver)"
                      : myResult.place === 3
                      ? "var(--bronze)"
                      : "var(--line)";
                  return (
                    <div
                      key={h.n}
                      className="log-item"
                      style={{ "--lc": color } as CSSProperties}
                    >
                      <div className="place">
                        {myResult.place}º<small>de {h.results.length}</small>
                      </div>
                      <div className="li-info">
                        <div className="li-t">Partida {h.n}</div>
                        <div className="li-s">{data.format.toUpperCase()} · Bravura</div>
                      </div>
                      <div className={`li-pts${myResult.points >= 0 ? " pos" : " neg"}`}>
                        {myResult.points >= 0 ? "+" : ""}
                        {myResult.points}
                      </div>
                    </div>
                  );
                })}
              {/* live placeholder */}
              {data.matches.find((m) => m.status === "live") && (
                <div
                  className="log-item"
                  style={{ "--lc": "var(--red)" } as CSSProperties}
                >
                  <div className="place" style={{ color: "var(--red)" }}>—</div>
                  <div className="li-info">
                    <div className="li-t">
                      Partida {data.matches.find((m) => m.status === "live")?.n}
                    </div>
                    <div className="li-s">
                      {lobbyJoined
                        ? "No saguão — partida começando"
                        : "Aguardando início"}
                    </div>
                  </div>
                  <div className="li-pts" style={{ color: "var(--text-faint)" }}>·</div>
                </div>
              )}
            </div>

            {/* Histórico entre campeonatos (cross-tournament) ainda não existe como
                endpoint — depende de identidade de jogador, que o produto não tem
                hoje. Um array de exemplo fixo aqui apareceria como resultado real
                para qualquer visitante; mostramos a lacuna em vez disso. */}
            <div className="side-h">Histórico no campeonato</div>
            <div className="hist hist-empty">
              <p>Histórico entre campeonatos ainda não está disponível.</p>
            </div>
          </>
        )}
      </aside>

      {/* ===== MODAL DE LOBBY ===== */}
      {data && (
        <LobbyModal
          open={lobbyOpen}
          matchN={lobbyMatchN}
          cap={data.matches.find((m) => m.n === lobbyMatchN)?.lobbyMax ?? 18}
          initialCount={data.matches.find((m) => m.n === lobbyMatchN)?.lobbyCount ?? 0}
          magneticLink={data.matches.find((m) => m.n === lobbyMatchN)?.magneticLink ?? ""}
          members={lobbyMembers}
          joined={lobbyJoined}
          onClose={closeLobby}
          onEnter={enterMatch}
          onCopyLink={copyLink}
        />
      )}

      {/* ===== TOASTS ===== */}
      <ToastWrap toasts={toasts} />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Bloco de histórico de partida                                         */
/* ------------------------------------------------------------------ */
function HistMatchBlock({
  result,
  standings,
  registrations,
}: {
  result: TournamentMatchResult;
  standings: StandingRow[];
  registrations: TeamRoster[];
}) {
  function teamBadgeBg(teamName: string): string {
    const reg = registrations.find((r) => r.teamName === teamName);
    if (reg && reg.players[0]) {
      return `linear-gradient(135deg, ${slotAvatar(reg.players[0]).c1}, ${slotAvatar(reg.players[0]).c2})`;
    }
    return "var(--surface-3)";
  }

  function isMyTeam(teamName: string): boolean {
    return !!standings.find((s) => s.isYou && s.teamName === teamName);
  }

  return (
    <div className="hist-match">
      <div className="hm-top">
        <span className="hm-label">Partida {result.n}</span>
        {result.status === "ended" && (
          <span className="m-status finished">
            <Mi name="check_circle" style={{ fontSize: 14, marginRight: 4, verticalAlign: "-2px" }} />
            Encerrada
          </span>
        )}
        {result.status === "live" && (
          <span className="m-status live">
            <Equalizer />
          </span>
        )}
        {result.status === "upcoming" && (
          <span className="m-status upcoming">Em breve</span>
        )}
      </div>

      {result.status === "ended" ? (
        <div className="hm-results">
          {result.results
            .slice()
            .sort((a, b) => a.place - b.place)
            .map((r) => (
              <div
                key={r.place}
                className={`hm-row${isMyTeam(r.teamName) ? " me" : ""}`}
              >
                <span
                  className={`hm-pos${r.place <= 3 ? ` p${r.place}` : ""}`}
                >
                  {r.place}
                </span>
                <span
                  className="tbadge-sm"
                  style={
                    { background: teamBadgeBg(r.teamName) } as CSSProperties
                  }
                />
                <span className="hm-name">{r.teamName}</span>
                <span className="hm-pts">+{r.points} pts</span>
              </div>
            ))}
        </div>
      ) : result.status === "live" ? (
        <div className="hm-pending">
          <Equalizer className="" />
          Partida em andamento — resultado em breve
        </div>
      ) : (
        <div className="hm-pending">Aguardando início da partida</div>
      )}
    </div>
  );
}
