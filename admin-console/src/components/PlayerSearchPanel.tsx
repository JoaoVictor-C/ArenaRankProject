import { useEffect, useState } from "react";
import type { Conn } from "../lib/backend";
import { updatePlayerModeration } from "../lib/playerActions";
import type { PlayerSearchRow } from "../lib/types";

type StatusFilter = "all" | "ativo" | "flagged" | "banido";

const CHIPS: { id: StatusFilter; label: string }[] = [
  { id: "all", label: "Todos" },
  { id: "ativo", label: "Ativos" },
  { id: "flagged", label: "Com flags" },
  { id: "banido", label: "Banidos" },
];

function statusOf(p: PlayerSearchRow): "ativo" | "sinalizado" | "banido" | "inativo" {
  if (p.banned) return "banido";
  if (p.shadowbanned || p.restricted) return "sinalizado";
  if (!p.active) return "inativo";
  return "ativo";
}

function matches(p: PlayerSearchRow, filter: StatusFilter): boolean {
  if (filter === "all") return true;
  if (filter === "ativo") return statusOf(p) === "ativo";
  if (filter === "banido") return p.banned;
  return p.shadowbanned || p.restricted || p.flagCount > 0;
}

interface Props {
  query: string;
  onQueryChange: (q: string) => void;
  results: PlayerSearchRow[];
  loading: boolean;
  conn: Conn;
}

export function PlayerSearchPanel({ query, onQueryChange, results, loading, conn }: Props) {
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [rows, setRows] = useState<PlayerSearchRow[]>(results);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // New search results replace local state; a moderation toggle below then
  // mutates `rows` directly (optimistic) without waiting for a re-search.
  useEffect(() => setRows(results), [results]);

  const visible = rows.filter((p) => matches(p, filter));

  async function toggle(p: PlayerSearchRow, field: "banned" | "shadowbanned" | "restricted") {
    setBusyId(p.id);
    setErr(null);
    try {
      const result = await updatePlayerModeration(conn, p.id, { [field]: !p[field] });
      setRows((prev) =>
        prev.map((row) =>
          row.id === p.id
            ? {
                ...row,
                banned: result.banned,
                shadowbanned: result.shadowbanned,
                restricted: result.restricted,
              }
            : row,
        ),
      );
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <section className="panel">
        <div className="player-searchbox">
          <span className="ms ms-18" aria-hidden="true">
            search
          </span>
          <input
            type="text"
            placeholder="Buscar por Riot ID, PUUID ou nome de invocador…"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
          />
          <span className="player-searchbox-count">
            {loading ? "buscando…" : `${visible.length} de ${rows.length}`}
          </span>
        </div>
        <div className="audit-chips">
          {CHIPS.map((c) => (
            <button
              key={c.id}
              type="button"
              className={filter === c.id ? "drawer-chip drawer-chip-on" : "drawer-chip"}
              onClick={() => setFilter(c.id)}
            >
              {c.label}
            </button>
          ))}
        </div>
      </section>

      {err && (
        <div className="banner banner-warn">
          {err}
        </div>
      )}

      <section className="panel">
        <div className="player-grid">
          <div className="player-head">
            <div>Jogador</div>
            <div>PUUID</div>
            <div>CR</div>
            <div>Região</div>
            <div>Status</div>
            <div>Ação</div>
          </div>
          {query.trim().length < 2 && (
            <div className="empty">Digite ao menos 2 caracteres para buscar.</div>
          )}
          {query.trim().length >= 2 && visible.length === 0 && !loading && (
            <div className="empty">Nenhum jogador corresponde ao filtro.</div>
          )}
          {visible.map((p) => {
            const status = statusOf(p);
            return (
              <div className="player-row" key={p.id}>
                <div className="player-identity">
                  <span
                    className="player-avatar"
                    style={{
                      background: `linear-gradient(135deg, ${p.avatar.c1}, ${p.avatar.c2})`,
                    }}
                  />
                  <div className="player-name-wrap">
                    <div className="player-riotid">{p.riotId}</div>
                  </div>
                </div>
                <div className="player-puuid" title={p.puuid}>
                  {p.puuid}
                </div>
                <div className="player-cr">{p.cr ?? "—"}</div>
                <div className="player-region">{p.region ?? "—"}</div>
                <div>
                  <span className={`role-badge player-status-${status}`}>{status}</span>
                </div>
                <div className="player-actions">
                  <button
                    type="button"
                    className={`mini${p.banned ? " is-danger is-on" : ""}`}
                    disabled={busyId === p.id}
                    onClick={() => toggle(p, "banned")}
                  >
                    {p.banned ? "Desbanir" : "Banir"}
                  </button>
                  <button
                    type="button"
                    className={`mini${p.shadowbanned ? " is-on" : ""}`}
                    disabled={busyId === p.id}
                    onClick={() => toggle(p, "shadowbanned")}
                  >
                    {p.shadowbanned ? "Remover SB" : "Shadowban"}
                  </button>
                  <button
                    type="button"
                    className={`mini${p.restricted ? " is-on" : ""}`}
                    disabled={busyId === p.id}
                    onClick={() => toggle(p, "restricted")}
                  >
                    {p.restricted ? "Remover restrição" : "Restringir"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </>
  );
}
