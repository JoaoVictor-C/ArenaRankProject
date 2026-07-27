import { useState } from "react";
import type { Conn } from "../../lib/backend";
import type { TournamentListItem } from "../../lib/types";
import { fmtInt } from "../../lib/format";
import { TournamentCreateForm } from "./TournamentCreateForm";

interface Props {
  conn: Conn;
  tournaments: TournamentListItem[] | null;
  loading: boolean;
  error: string | null;
  onSelect: (id: string) => void;
  onCreated: (id: string) => void;
}

export function TournamentList({ conn, tournaments, loading, error, onSelect, onCreated }: Props) {
  const [creating, setCreating] = useState(false);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Campeonatos</h2>
        <span className="panel-note">
          {tournaments ? `${tournaments.length} campeonatos` : "carregando…"}
        </span>
        {!creating && (
          <button className="mini is-primary" type="button" onClick={() => setCreating(true)}>
            Criar campeonato
          </button>
        )}
      </div>

      {error && <div className="banner banner-warn">{error}</div>}

      {creating && (
        <TournamentCreateForm
          conn={conn}
          onCancel={() => setCreating(false)}
          onCreated={(id) => {
            setCreating(false);
            onCreated(id);
          }}
        />
      )}

      {!tournaments && loading && !creating && (
        <div className="connecting">
          <span className="spinner" /> Lendo campeonatos…
        </div>
      )}

      {tournaments && tournaments.length === 0 && !creating && (
        <div className="empty">Nenhum campeonato criado ainda.</div>
      )}

      {tournaments && tournaments.length > 0 && (
        <div className="tourn-grid">
          {tournaments.map((t) => (
            <button
              key={t.id}
              type="button"
              className="tourn-card"
              onClick={() => onSelect(t.id)}
            >
              <div className="tourn-card-head">
                <span className={`tourn-badge tourn-badge-${t.format === "3v3" ? "trios" : "duos"}`}>
                  {t.format}
                </span>
                <span className="tourn-tag">{t.tag}</span>
              </div>
              <div className="tourn-card-title">{t.title}</div>
              <div className="tourn-card-meta">
                <span>{fmtInt(t.teams)} equipes</span>
                <span>{t.amountLabel}</span>
                <span>{t.whenLabel}</span>
              </div>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
