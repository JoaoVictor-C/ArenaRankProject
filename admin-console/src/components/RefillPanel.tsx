import { useCallback, useEffect, useState } from "react";
import {
  fetchIngestStatus,
  startRefill,
  stopRefill,
  type IngestStatus,
} from "../lib/actions";
import type { Conn } from "../lib/backend";
import { fmtInt } from "../lib/format";

interface Props {
  conn: Conn;
}

/* Refill da temporada.

   Existe porque abrir uma temporada com janela retroativa sobre uma base vazia
   não se recupera sozinho: a Riot não tem endpoint de "todas as partidas da
   região", então todo id é alcançado por um puuid que já conhecemos — sem
   semente, nada começa.

   Durante o refill a temporada fica em `catching_up`: a descoberta continua,
   mas NADA é avaliado na chegada. As partidas ficam estacionadas e são
   avaliadas depois em ordem cronológica estrita, porque o motor de rating
   depende da ordem e a descoberta chega essencialmente embaralhada. */

function relative(iso: string | null): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms)) return "—";
  const min = Math.floor(ms / 60000);
  if (min < 1) return "agora";
  if (min < 60) return `há ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `há ${h} h`;
  return `há ${Math.floor(h / 24)} d`;
}

export function RefillPanel({ conn }: Props) {
  const [status, setStatus] = useState<IngestStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        setStatus(await fetchIngestStatus(conn, signal));
        setError(null);
      } catch (e) {
        if (signal?.aborted) return;
        setError(e instanceof Error ? e.message : "Falha ao ler o estado do refill.");
      }
    },
    [conn],
  );

  useEffect(() => {
    const ac = new AbortController();
    void load(ac.signal);
    // Enquanto o refill roda os números mudam a cada tick do scheduler (1 min);
    // 10 s dá a sensação de progresso sem martelar a API.
    const t = setInterval(() => void load(), 10_000);
    return () => {
      ac.abort();
      clearInterval(t);
    };
  }, [load]);

  const act = async (fn: (c: Conn) => Promise<IngestStatus>) => {
    setBusy(true);
    try {
      setStatus(await fn(conn));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ação falhou.");
    } finally {
      setBusy(false);
    }
  };

  const catching = status?.mode === "catching_up";

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Refill da temporada</h2>
        <span className="panel-note">
          repovoa a janela e avalia tudo em ordem cronológica
        </span>
      </div>

      {error && <div className="state-block state-error">{error}</div>}

      <div className="trend-row">
        <div className="trend">
          <div className="trend-k">Modo</div>
          <div className="trend-v" style={{ color: catching ? "var(--cyan)" : "var(--green)" }}>
            {catching ? "Recuperando" : "Ao vivo"}
          </div>
          <div className="stage-sub">
            {catching
              ? "descobrindo · nada avaliado na chegada"
              : "avaliando na chegada"}
          </div>
        </div>
        <div className="trend">
          <div className="trend-k">Estacionadas</div>
          <div className="trend-v tnum">{fmtInt(status?.staged ?? 0)}</div>
          <div className="stage-sub">
            {status?.oldestStagedAt
              ? `mais antiga ${relative(status.oldestStagedAt)}`
              : "fila cronológica vazia"}
          </div>
        </div>
        <div className="trend">
          <div className="trend-k">Jogadores alcançados</div>
          <div className="trend-v tnum">{fmtInt(status?.frontierDone ?? 0)}</div>
          <div className="stage-sub">
            {status?.saturatedAt
              ? `fronteira saturou ${relative(status.saturatedAt)}`
              : `${fmtInt(status?.frontierPending ?? 0)} na fronteira`}
          </div>
        </div>
        <div className="trend">
          <div className="trend-k">Cobertura</div>
          <div className="trend-v tnum">
            {status?.coveragePct == null ? "—" : `${status.coveragePct.toFixed(1)}%`}
          </div>
          <div className="stage-sub">
            {status?.coverageAt ? `amostrado ${relative(status.coverageAt)}` : "sem amostra"}
          </div>
        </div>
      </div>

      {status?.replayFloor && (
        <div className="state-block">
          Há cauda fora de ordem desde <strong>{relative(status.replayFloor)}</strong>. O
          reprocessamento cronológico roda sozinho quando as filas esvaziarem.
        </div>
      )}

      <div className="panel-actions">
        <button
          type="button"
          className="btn"
          disabled={busy || catching}
          onClick={() => void act(startRefill)}
        >
          Iniciar refill
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          disabled={busy || !catching}
          onClick={() => void act(stopRefill)}
        >
          Encerrar refill
        </button>
      </div>

      <p className="panel-note">
        As sementes vêm de <code>BOOTSTRAP_SEED_RIOT_IDS</code>. Encerrar volta a
        avaliar na chegada; o que já está estacionado continua sendo drenado em
        ordem.
      </p>
    </section>
  );
}
