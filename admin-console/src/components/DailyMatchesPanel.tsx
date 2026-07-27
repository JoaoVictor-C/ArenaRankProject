import type { AdminDailyMatchStat, AdminDailyMatches } from "../lib/types";
import { fmtInt } from "../lib/format";

interface Props {
  daily: AdminDailyMatches | null;
  error: string | null;
}

function fmtDuration(seconds: number | null): string {
  if (seconds === null || Number.isNaN(seconds)) return "—";
  const m = Math.round(seconds / 60);
  return `${m}min`;
}

/** "26/07" from a YYYY-MM-DD string, without pulling in a date library. */
function fmtDayLabel(date: string): string {
  const [, mo, d] = date.split("-");
  return mo && d ? `${d}/${mo}` : date;
}

function DayBar({ day, max }: { day: AdminDailyMatchStat; max: number }) {
  const pct = max > 0 ? Math.max(2, Math.round((day.matches / max) * 100)) : 2;
  const modeParts = [
    day.trios > 0 ? `${fmtInt(day.trios)} trios` : null,
    day.duos > 0 ? `${fmtInt(day.duos)} duos` : null,
  ].filter(Boolean);
  const title =
    `${day.date} · ${fmtInt(day.matches)} partidas` +
    (modeParts.length ? ` (${modeParts.join(", ")})` : "") +
    (day.avgDurationSeconds !== null ? ` · duração média ${fmtDuration(day.avgDurationSeconds)}` : "") +
    (day.withIntegrityFlags > 0 ? ` · ${fmtInt(day.withIntegrityFlags)} com flag de integridade` : "");

  return (
    <div className="dbar" title={title}>
      <div className="dbar-track">
        <div className="dbar-fill" style={{ height: `${pct}%` }} />
      </div>
      <div className="dbar-label">{fmtDayLabel(day.date)}</div>
    </div>
  );
}

export function DailyMatchesPanel({ daily, error }: Props) {
  const days = daily?.days ?? [];
  const max = days.reduce((m, d) => Math.max(m, d.matches), 0);
  const totalMatches = days.reduce((s, d) => s + d.matches, 0);
  const totalFlagged = days.reduce((s, d) => s + d.withIntegrityFlags, 0);
  const withDuration = days.filter((d) => d.avgDurationSeconds !== null);
  const avgDurationOverall = withDuration.length
    ? withDuration.reduce((s, d) => s + (d.avgDurationSeconds ?? 0) * d.matches, 0) /
      Math.max(1, withDuration.reduce((s, d) => s + d.matches, 0))
    : null;
  const avgPerDay = days.length ? Math.round(totalMatches / days.length) : 0;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Partidas por dia</h2>
        <span className="panel-note">
          {daily ? `últimos ${days.length || "—"} dias · UTC` : "carregando…"}
        </span>
      </div>

      {error && <div className="banner banner-warn">{error}</div>}

      {daily && days.length === 0 && !error && (
        <div className="empty">Sem partidas registradas na janela.</div>
      )}

      {daily && days.length > 0 && (
        <>
          <div className="trend-row">
            <div className="trend">
              <div className="trend-k">Total na janela</div>
              <div className="trend-v tnum">{fmtInt(totalMatches)}</div>
            </div>
            <div className="trend">
              <div className="trend-k">Média/dia</div>
              <div className="trend-v tnum">{fmtInt(avgPerDay)}</div>
            </div>
            <div className="trend">
              <div className="trend-k">Duração média</div>
              <div className="trend-v tnum">{fmtDuration(avgDurationOverall)}</div>
            </div>
            <div className="trend">
              <div className="trend-k">Com flag de integridade</div>
              <div
                className="trend-v tnum"
                style={{ color: totalFlagged > 0 ? "var(--amber)" : undefined }}
              >
                {fmtInt(totalFlagged)}
              </div>
            </div>
          </div>

          <div className="dbars">
            {days.map((d) => (
              <DayBar day={d} max={max} key={d.date} />
            ))}
          </div>
        </>
      )}

      {!daily && !error && (
        <div className="connecting">
          <span className="spinner" /> Lendo partidas por dia…
        </div>
      )}
    </section>
  );
}
