/* ============================================================
   Campeonatos2 — página de PRÉVIA/TESTE (/campeonatos2)
   Reaproveita a view de Campeonatos, mas exibe os torneios
   PROVISIONADOS pelo Admin (POST /admin/tournaments). Resolve o
   mais recente por padrão; /campeonatos2/:id abre um específico.
   ============================================================ */
import { Link, useParams } from "react-router-dom";
import { Campeonatos } from "./Campeonatos";
import { StateBlock } from "../components/StateBlock";
import { Mi } from "../components/Mi";
import { useApi } from "../hooks/useApi";
import { api } from "../lib/api";
import "./Campeonatos2.css";

export function Campeonatos2() {
  const { id } = useParams<{ id?: string }>();
  const { data: list, loading, error } = useApi(() => api.tournaments(), []);

  const tournaments = list ?? [];
  const activeId = id ?? tournaments[0]?.id;

  return (
    <div className="c2-wrap">
      <div className="c2-banner">
        <span className="c2-eyebrow">
          <Mi name="science" />
          Prévia · campeonato provisionado
        </span>
        <span className="c2-hint">
          Torneios criados no <Link to="/admin">Painel Admin → Campeonatos</Link>. Esta página é a área de testes
          ponta-a-ponta (provisionar → exibir).
        </span>
        {tournaments.length > 0 && (
          <div className="c2-selector">
            {tournaments.map((t) => (
              <Link
                key={t.id}
                to={`/campeonatos2/${encodeURIComponent(t.id)}`}
                className="c2-chip"
                data-active={t.id === activeId}
              >
                {t.title}
              </Link>
            ))}
          </div>
        )}
      </div>

      <StateBlock loading={loading} error={error} empty={!loading && !error && tournaments.length === 0}>
        {activeId && <Campeonatos key={activeId} tourneyIdOverride={activeId} />}
      </StateBlock>
    </div>
  );
}
