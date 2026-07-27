import type { RiotBucketUsage, RiotUsage } from "../lib/types";
import { fmtInt, fmtPct } from "../lib/format";

interface Props {
  usage: RiotUsage | null;
  error: string | null;
}

/** Utilization tone: green while there is real slack, amber approaching the
 *  ceiling, red once effectively saturated. */
function tone(u: number): string {
  if (u >= 0.9) return "var(--red)";
  if (u >= 0.65) return "var(--amber)";
  return "var(--green)";
}

/** "há 12s" from epoch SECONDS (the observed snapshot uses epoch, not ISO). */
function agoFromEpoch(epochSeconds: number): string {
  if (!epochSeconds) return "—";
  const s = Math.max(0, Math.round(Date.now() / 1000 - epochSeconds));
  if (s < 2) return "agora";
  if (s < 60) return `há ${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `há ${m}min`;
  return `há ${Math.floor(m / 60)}h`;
}

function BucketRow({ b }: { b: RiotBucketUsage }) {
  // Riot's own count is authoritative when present; our token bucket is only a
  // model of it. Show both, but let Riot's reading drive the gauge.
  const observed = b.observed ?? null;
  const utilization = observed ? observed.utilization : b.utilization;
  const color = tone(utilization);

  return (
    <div className="rbucket">
      <div className="rbucket-head">
        <div className="rbucket-label">{b.label}</div>
        <div className="rbucket-limit tnum">
          {fmtInt(b.capacity)}
          {/* advertised is absent on an older backend (console can point at
              Local/Produção/Custom independently) — fall back to capacity. */}
          {b.advertised != null && b.advertised !== b.capacity && (
            <span className="rbucket-nominal"> / {fmtInt(b.advertised)}</span>
          )}
          <span className="rbucket-window"> por {b.windowSeconds}s</span>
        </div>
      </div>

      <div className="rbar" role="meter" aria-valuenow={Math.round(utilization * 100)}>
        <span className="rbar-fill" style={{ width: `${Math.min(100, utilization * 100)}%`, background: color }} />
      </div>

      <div className="rbucket-foot">
        <span className="rbucket-util tnum" style={{ color }}>
          {fmtPct(utilization)}
        </span>
        <span className="rbucket-src">
          {observed ? `medido pela Riot · ${agoFromEpoch(observed.observedAt)}` : "estimado (sem leitura da Riot ainda)"}
        </span>
        <span className="rbucket-calls tnum">
          {fmtInt(b.lastMinute)}/min · {fmtInt(b.lastHour)}/h
        </span>
      </div>

      {b.drift && <div className="rbucket-drift">⚠ {b.drift}</div>}
    </div>
  );
}

export function RiotUsagePanel({ usage, error }: Props) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Chave da Riot</h2>
        <span className="panel-note">
          {usage
            ? `…${usage.keySuffix}` +
              (usage.headroom != null ? ` · margem ${fmtPct(usage.headroom)}` : "")
            : "carregando…"}
        </span>
      </div>

      {error && <div className="banner banner-warn">{error}</div>}

      {usage && !usage.keyConfigured && (
        <div className="empty">
          Nenhuma RIOT_API_KEY configurada — a ingestão de novas partidas está parada.
        </div>
      )}

      {usage?.driftWarnings?.map((w) => (
        <div className="banner banner-warn" key={w}>
          {w}
        </div>
      ))}

      {usage && (
        <>
          <div className="trend-row">
            <div className="trend">
              <div className="trend-k">Chamadas/min</div>
              <div className="trend-v tnum">{fmtInt(usage.requestsLastMinute)}</div>
            </div>
            <div className="trend">
              <div className="trend-k">Chamadas/h</div>
              <div className="trend-v tnum">{fmtInt(usage.requestsLastHour)}</div>
            </div>
            <div className="trend">
              <div className="trend-k">429 (1h)</div>
              <div
                className="trend-v tnum"
                style={{ color: usage.rateLimitedLastHour > 0 ? "var(--red)" : undefined }}
              >
                {fmtInt(usage.rateLimitedLastHour)}
              </div>
            </div>
            <div className="trend">
              <div className="trend-k">Erros (1h)</div>
              <div
                className="trend-v tnum"
                style={{ color: usage.errorsLastHour > 0 ? "var(--amber)" : undefined }}
              >
                {fmtInt(usage.errorsLastHour)}
              </div>
            </div>
          </div>

          <div className="rbuckets">
            {usage.buckets.length === 0 && <div className="empty">Nenhum bucket configurado.</div>}
            {usage.buckets.map((b) => (
              <BucketRow b={b} key={b.name} />
            ))}
          </div>
        </>
      )}

      {!usage && !error && (
        <div className="connecting">
          <span className="spinner" /> Lendo consumo da chave…
        </div>
      )}
    </section>
  );
}
