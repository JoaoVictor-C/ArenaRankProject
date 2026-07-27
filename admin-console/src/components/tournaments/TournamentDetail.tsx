import { useEffect, useState } from "react";
import type { Conn } from "../../lib/backend";
import { fetchTournamentDetail, setMatchLink, submitMatchResult } from "../../lib/tournamentActions";
import type {
  MatchStatus,
  PlayerSlot,
  TournamentDetail as TournamentDetailData,
  TournamentMatch,
} from "../../lib/types";
import { fmtInt } from "../../lib/format";

interface Props {
  conn: Conn;
  tournamentId: string;
  onBack: () => void;
}

const STATUS_LABEL: Record<string, string> = {
  upcoming: "em breve",
  live: "ao vivo",
  ended: "encerrado",
};

function playerLabel(slot: PlayerSlot): string {
  return "empty" in slot ? "vaga aberta" : `${slot.name} (${slot.riotId})`;
}

export function TournamentDetail({ conn, tournamentId, onBack }: Props) {
  const [detail, setDetail] = useState<TournamentDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copyOk, setCopyOk] = useState(false);

  async function load() {
    setError(null);
    try {
      const d = await fetchTournamentDetail(conn, tournamentId);
      setDetail(d);
    } catch (e) {
      setError((e as Error).message ?? "Falha ao carregar campeonato");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conn.id, conn.base, conn.key, tournamentId]);

  async function copyKey() {
    if (!detail?.accessKey) return;
    try {
      await navigator.clipboard.writeText(detail.accessKey);
      setCopyOk(true);
      setTimeout(() => setCopyOk(false), 1500);
    } catch {
      /* clipboard unavailable — the key is still shown as text */
    }
  }

  return (
    <section className="panel">
      <div className="tourn-detail-head">
        <button className="mini" type="button" onClick={onBack}>
          ← Campeonatos
        </button>
        {detail && (
          <>
            <span className={`tourn-status tourn-status-${detail.status}`}>
              {STATUS_LABEL[detail.status] ?? detail.status}
            </span>
            <h2 className="tourn-detail-title">{detail.title}</h2>
            <span className="panel-note">{detail.prizeLabel}</span>
          </>
        )}
      </div>

      {error && <div className="banner banner-warn">{error}</div>}

      {loading && !detail && (
        <div className="connecting">
          <span className="spinner" /> Carregando campeonato…
        </div>
      )}

      {detail && (
        <>
          {detail.accessKey && (
            <div className="tourn-key-row">
              <span>Chave de acesso</span>
              <code>{detail.accessKey}</code>
              <button className="mini" type="button" onClick={copyKey}>
                {copyOk ? "Copiado!" : "Copiar"}
              </button>
            </div>
          )}

          <div className="tourn-section">
            <h3>Classificação</h3>
            {detail.standings.length === 0 ? (
              <div className="empty">Sem equipes ainda.</div>
            ) : (
              <div className="tourn-standings">
                <div className="tourn-standings-head">
                  <span>Equipe</span>
                  <span>Por partida</span>
                  <span>Bônus</span>
                  <span>Penalidades</span>
                  <span>Total</span>
                </div>
                {detail.standings.map((s) => (
                  <div className="tourn-standings-row" key={s.teamId}>
                    <span>{s.teamName}</span>
                    <span className="tnum">{s.perMatch.join(" · ") || "—"}</span>
                    <span className="tnum">{s.bonus}</span>
                    <span className="tnum">{s.penalties}</span>
                    <span className="tnum tourn-total">{s.total}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="tourn-section">
            <h3>Equipes</h3>
            <div className="tourn-rosters">
              {detail.registrations.map((r) => (
                <div className="tourn-roster-card" key={r.teamId}>
                  <div className="tourn-roster-name">{r.teamName}</div>
                  {r.captain && <div className="tourn-roster-captain">Capitão: {r.captain}</div>}
                  <ul className="tourn-roster-players">
                    {r.players.map((p, i) => (
                      <li key={i}>{playerLabel(p)}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>

          <div className="tourn-section">
            <h3>Partidas</h3>
            <div className="tourn-matches">
              {detail.matches.map((m) => (
                <MatchRow
                  key={m.n}
                  conn={conn}
                  tournamentId={tournamentId}
                  match={m}
                  teams={detail.registrations.map((r) => ({ teamId: r.teamId, teamName: r.teamName }))}
                  isCurrent={m.n === detail.currentMatch}
                  onMutated={load}
                />
              ))}
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function MatchRow({
  conn,
  tournamentId,
  match,
  teams,
  isCurrent,
  onMutated,
}: {
  conn: Conn;
  tournamentId: string;
  match: TournamentMatch;
  teams: { teamId: string; teamName: string }[];
  isCurrent: boolean;
  onMutated: () => void;
}) {
  const [link, setLink] = useState(match.magneticLink);
  const [status, setStatus] = useState<MatchStatus>(match.status);
  const [linkBusy, setLinkBusy] = useState(false);
  const [linkErr, setLinkErr] = useState<string | null>(null);

  const [resultOpen, setResultOpen] = useState(false);
  const [placements, setPlacements] = useState<Record<string, number>>(() =>
    Object.fromEntries(teams.map((t, i) => [t.teamId, i + 1])),
  );
  const [bravura, setBravura] = useState<Record<string, number>>(() =>
    Object.fromEntries(teams.map((t) => [t.teamId, 0])),
  );
  const [penalties, setPenalties] = useState<Record<string, number>>(() =>
    Object.fromEntries(teams.map((t) => [t.teamId, 0])),
  );
  const [resultBusy, setResultBusy] = useState(false);
  const [resultErr, setResultErr] = useState<string | null>(null);

  async function saveLink() {
    setLinkBusy(true);
    setLinkErr(null);
    try {
      await setMatchLink(conn, tournamentId, match.n, { magneticLink: link, status });
      onMutated();
    } catch (e) {
      setLinkErr((e as Error).message ?? "Falha ao salvar link/status");
    } finally {
      setLinkBusy(false);
    }
  }

  async function saveResult() {
    setResultBusy(true);
    setResultErr(null);
    try {
      await submitMatchResult(conn, tournamentId, match.n, {
        results: teams.map((t) => ({
          teamId: t.teamId,
          placement: placements[t.teamId] ?? 1,
          bravura: bravura[t.teamId] ?? 0,
        })),
        penalties: teams
          .map((t) => ({ teamId: t.teamId, value: penalties[t.teamId] ?? 0 }))
          .filter((p) => p.value !== 0),
      });
      setResultOpen(false);
      onMutated();
    } catch (e) {
      setResultErr((e as Error).message ?? "Falha ao lançar resultado");
    } finally {
      setResultBusy(false);
    }
  }

  return (
    <div className={`tourn-match-row${isCurrent ? " tourn-match-current" : ""}`}>
      <div className="tourn-match-head">
        <span className="tourn-match-n">Partida {match.n}</span>
        <span className={`tourn-status tourn-status-${match.status}`}>
          {STATUS_LABEL[match.status] ?? match.status}
        </span>
        <span className="panel-note">
          {fmtInt(match.lobbyCount)}/{fmtInt(match.lobbyMax)} no lobby
        </span>
      </div>

      {linkErr && <div className="row-err">{linkErr}</div>}
      <div className="tourn-match-form">
        <input
          value={link}
          onChange={(e) => setLink(e.target.value)}
          placeholder="arena://lobby/..."
          className="tourn-match-link"
        />
        <select value={status} onChange={(e) => setStatus(e.target.value as MatchStatus)}>
          <option value="upcoming">upcoming</option>
          <option value="live">live</option>
          <option value="ended">ended</option>
        </select>
        <button className="mini" type="button" disabled={linkBusy} onClick={saveLink}>
          {linkBusy ? "…" : "Salvar"}
        </button>
        <button className="mini" type="button" onClick={() => setResultOpen((v) => !v)}>
          {resultOpen ? "Fechar resultado" : "Lançar resultado"}
        </button>
      </div>

      {resultOpen && (
        <div className="tourn-result-form">
          {resultErr && <div className="row-err">{resultErr}</div>}
          <div className="tourn-result-head">
            <span>Equipe</span>
            <span>Colocação</span>
            <span>Bravura</span>
            <span>Penalidade</span>
          </div>
          {teams.map((t) => (
            <div className="tourn-result-row" key={t.teamId}>
              <span>{t.teamName}</span>
              <input
                type="number"
                min={1}
                max={teams.length}
                value={placements[t.teamId] ?? 1}
                onChange={(e) =>
                  setPlacements((p) => ({ ...p, [t.teamId]: Number(e.target.value) }))
                }
              />
              <input
                type="number"
                min={0}
                max={4}
                value={bravura[t.teamId] ?? 0}
                onChange={(e) => setBravura((b) => ({ ...b, [t.teamId]: Number(e.target.value) }))}
              />
              <input
                type="number"
                value={penalties[t.teamId] ?? 0}
                onChange={(e) =>
                  setPenalties((p) => ({ ...p, [t.teamId]: Number(e.target.value) }))
                }
              />
            </div>
          ))}
          <div className="row-actions">
            <button className="mini is-primary" type="button" disabled={resultBusy} onClick={saveResult}>
              {resultBusy ? "…" : "Confirmar resultado"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
