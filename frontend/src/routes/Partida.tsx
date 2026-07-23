/* ============================================================
   Partida.tsx — Detalhe de partida (Arena 3v3 / 2v2)
   Rota: /partida/:matchId
   ============================================================ */
import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import "./Partida.css";
import { ChampIcon, Mi, Placement, Delta, StateBlock } from "../components";
import { useApi } from "../hooks/useApi";
import { api } from "../lib/api";
import type { SubTeam, MatchPlayer, MatchDetail } from "../lib/types";
import { nf, signed, deltaClass, timeAgo, fmtCountdown } from "../lib/format";

/* ---------- helpers locais ---------- */

/** Soma do crDelta de todos os jogadores do subtime */
function teamCrSum(team: SubTeam): number {
  return team.players.reduce((acc, p) => acc + p.crDelta, 0);
}

/** Formata data/hora ISO em pt-BR legível */
function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("pt-BR", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

/* ---------- sub-componente: card de jogador (breakdown) ---------- */
function PlayerCard({ player }: { player: MatchPlayer }) {
  return (
    <div className="pp-card">
      {/* cabeçalho: campeão + nome + delta CR */}
      <div className="pp-head">
        <ChampIcon colors={player.champion} url={player.championIconUrl} alt={player.championName} size="lg" />
        <div>
          <div className="nm">
            <Link to={`/perfil/${encodeURIComponent(player.riotId)}`} className="nm">
              {player.name}
            </Link>{" "}
            <span className="faint" style={{ fontWeight: 500, fontSize: 11 }}>
              {player.handle}
            </span>
          </div>
          <div style={{ fontSize: 11, color: "var(--text-faint)", marginTop: 4 }}>
            {player.championName}
          </div>
        </div>
        <div className="cr-range" style={{ marginLeft: "auto", textAlign: "right" }}>
          <Delta value={player.crDelta} className="" />
          <div className="range-txt">
            {nf(player.crBefore)} → {nf(player.crAfter)}
          </div>
        </div>
      </div>

      {/* modificadores */}
      {player.modifiers.map((mod, idx) => (
        <div className="pp-mod" key={idx}>
          <span className="l">
            <span className="ic mi">{mod.icon}</span>
            {mod.label}
          </span>
          <span className={`v${mod.value !== 0 ? ` delta ${deltaClass(mod.value)}` : ""}`}>
            {mod.value === 0 ? "—" : signed(mod.value)}
          </span>
        </div>
      ))}

      {/* flags de integridade (se houver) */}
      {player.integrity && player.integrity.length > 0 && (
        <div className="pp-integrity">
          {player.integrity.map((flag, idx) => (
            <span key={idx} className={`flag ${flag.kind}`}>
              <span className="dot" />
              {flag.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------- sub-componente: linha de subtime ---------- */
function TeamRow({ team }: { team: SubTeam }) {
  const [open, setOpen] = useState(false);
  const sum = teamCrSum(team);

  return (
    <div className="team-row" data-open={open ? "true" : "false"}>
      {/* linha principal (clicável) */}
      <div className="team-main" onClick={() => setOpen((v) => !v)} role="button" tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setOpen((v) => !v); }}
        aria-expanded={open}>
        {/* colocação */}
        <div className="team-place">
          <Placement place={team.placement} />
          <span className="pl">equipe</span>
        </div>

        {/* jogadores (avatar + nome + delta individual) */}
        <div className="team-players">
          {team.players.map((p) => (
            <div className="tp" key={p.riotId}>
              <ChampIcon colors={p.champion} url={p.championIconUrl} alt={p.championName} size="lg" />
              <div>
                <div className="nm">{p.name}</div>
                <div className="tag">{p.handle}</div>
                <div className={`d delta ${deltaClass(p.crDelta)}`}>
                  {p.crDelta >= 0 ? "+" : ""}
                  {p.crDelta} CR
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* soma do time */}
        <div className="team-cr">
          <div className={`sum delta ${deltaClass(sum)}`}>
            {sum >= 0 ? "+" : ""}
            {sum} CR
          </div>
          <div className="cap">soma da equipe</div>
        </div>

        {/* caret */}
        <div className="team-caret" aria-hidden="true">⌄</div>
      </div>

      {/* detalhe expandido: cards dos jogadores */}
      {open && (
        <div className="team-detail">
          <div className="pp-grid">
            {team.players.map((p) => (
              <PlayerCard key={p.riotId} player={p} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------- painel de integridade da partida ---------- */
function IntegrityPanel({ match }: { match: MatchDetail }) {
  /* agrega todas as flags de integridade de todos os jogadores */
  const allFlags = match.subteams.flatMap((t) =>
    t.players.flatMap((p) =>
      (p.integrity ?? []).map((f) => ({ ...f, player: p.name }))
    )
  );

  return (
    <div className="panel panel-pad integ-panel">
      <div className="section-head" style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 18 }}>Sinalizações de integridade</h2>
        <div className="rule" style={{ flexBasis: 60 }} />
        <div className="spacer" />
      </div>

      {allFlags.length === 0 ? (
        <span className="flag info">
          <span className="dot" />
          Sem violações detectadas nesta partida
        </span>
      ) : (
        allFlags.map((f, idx) => (
          <span key={idx} className={`flag ${f.kind}`}>
            <span className="dot" />
            {f.player} — {f.label}
          </span>
        ))
      )}

      <div className="integ-note">
        Cada partida é checada automaticamente contra boosting, repetição de lobby e
        duração atípica. Casos graves são enviados para revisão manual — o sistema nunca
        pune sozinho. Esta partida foi processada e arquivada como registro imutável.
      </div>
    </div>
  );
}

/* ---------- painel de processamento ---------- */
function ProcessingPanel({ match }: { match: MatchDetail }) {
  return (
    <div className="panel panel-pad">
      <div className="section-head" style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 18 }}>Processamento</h2>
        <div className="rule" style={{ flexBasis: 60 }} />
        <div className="spacer" />
      </div>
      <div className="proc">
        <div className="proc-row">
          <span className="k">Status</span>
          <span className="v" style={{ color: "var(--green)" }}>✓ processada</span>
        </div>
        <div className="proc-row">
          <span className="k">Processada em</span>
          <span className="v">{fmtDateTime(match.processedAt)}</span>
        </div>
        <div className="proc-row">
          <span className="k">Partida jogada em</span>
          <span className="v">{fmtDateTime(match.playedAt)}</span>
        </div>
        <div className="proc-row">
          <span className="k">Patch</span>
          <span className="v mono">{match.patch}</span>
        </div>
        <div className="proc-row">
          <span className="k">ID</span>
          <span className="v mono">{match.matchId}</span>
        </div>
        <div className="proc-row">
          <span className="k">Idempotência</span>
          <span className="v">flag atômico setado no commit</span>
        </div>
      </div>
      <div className="integ-note">
        Registro de partida auto-contido e imutável. Reprocessar é idempotente: a mesma
        entrada sempre produz o mesmo resultado de rating.
      </div>
    </div>
  );
}

/* ---------- componente principal ---------- */
export function Partida() {
  const { matchId = "" } = useParams<{ matchId: string }>();
  const { data, loading, error } = useApi(
    () => api.match(matchId),
    [matchId]
  );

  return (
    <div className="shell">
      {/* breadcrumb */}
      <div className="breadcrumb">
        <Link to="/">Início</Link>
        <span className="sep">›</span>
        <span>{matchId || "Partida"}</span>
      </div>

      <StateBlock loading={loading} error={error} empty={!data && !loading && !error}>
        {data && <PartidaContent match={data} />}
      </StateBlock>
    </div>
  );
}

/* ---------- conteúdo (renderizado só quando data existe) ---------- */
function PartidaContent({ match }: { match: MatchDetail }) {
  /* número de equipes a partir dos dados reais */
  const numTeams = match.subteams.length;

  return (
    <>
      {/* ---------- cabeçalho da partida ---------- */}
      <section className="mh">
        {/* coluna 1: rótulo da fila */}
        <div className="col">
          <div className="k">Partida</div>
          <span className="mode-badge">
            <Mi name="swords" style={{ fontSize: 16, marginRight: 6, verticalAlign: -3 }} />
            {match.queueLabel.toUpperCase()} · {numTeams} EQUIPES
          </span>
          <div className="mid">
            Formato <b>{match.format.toUpperCase()}</b>
            <br />
            <span className="mono faint" style={{ fontSize: 11 }}>
              ID: {match.matchId}
            </span>
          </div>
        </div>

        {/* coluna 2: quando */}
        <div className="col when">
          <div className="k">Quando</div>
          <b>{timeAgo(match.playedAt)}</b>
          <div className="abs">
            {fmtDateTime(match.playedAt)} · duração {fmtCountdown(match.durationSec)}
          </div>
        </div>

        {/* coluna 3: integridade resumida */}
        <div className="integ">
          <div className="k">Integridade</div>
          <span className="ok">
            <Mi name="verified" style={{ fontSize: 16, marginRight: 5, verticalAlign: -3 }} />
            Processada · sem violações críticas
          </span>
          <span className="flag info">
            <span className="dot" />
            Composição validada · todos elegíveis
          </span>
        </div>
      </section>

      {/* ---------- cabeçalho da seção de classificação ---------- */}
      <div className="section-head">
        <h2 style={{ fontSize: 24 }}>Classificação final</h2>
        <div className="rule" style={{ flexBasis: 110 }} />
        <div className="spacer" />
        <span className="faint" style={{ font: "500 12px/1 'Plus Jakarta Sans', sans-serif" }}>
          Clique numa equipe para ver os modificadores aplicados
        </span>
      </div>

      {/* ---------- lista de subteams ordenados por colocação ---------- */}
      <div className="standings">
        {match.subteams
          .slice()
          .sort((a, b) => a.placement - b.placement)
          .map((team) => (
            <TeamRow key={team.placement} team={team} />
          ))}
      </div>

      {/* ---------- grid inferior: integridade + processamento ---------- */}
      <div className="grid2">
        <IntegrityPanel match={match} />
        <ProcessingPanel match={match} />
      </div>
    </>
  );
}
