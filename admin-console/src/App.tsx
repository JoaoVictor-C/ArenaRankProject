import { useCallback, useMemo, useState } from "react";
import "./styles.css";
import {
  clearAdminKey,
  resolveConn,
  setAdminKey,
  setBackendId,
  setCustomUrl,
  setProdUrl,
  type BackendId,
  type Conn,
} from "./lib/backend";
import { useTelemetry } from "./lib/useTelemetry";
import { useOverview } from "./lib/useOverview";
import { useRiotUsage } from "./lib/useRiotUsage";
import { useDailyMatches } from "./lib/useDailyMatches";
import { useOperators } from "./lib/useOperators";
import { useAudit } from "./lib/useAudit";
import { usePlayerSearch } from "./lib/usePlayerSearch";
import { TopBar } from "./components/TopBar";
import { Sidebar } from "./components/Sidebar";
import { ConnectionDrawer } from "./components/ConnectionDrawer";
import { Gate } from "./components/Gate";
import { FlowRail } from "./components/FlowRail";
import { WorkersPanel } from "./components/WorkersPanel";
import { QueuesPanel } from "./components/QueuesPanel";
import { RiotUsagePanel } from "./components/RiotUsagePanel";
import { DailyMatchesPanel } from "./components/DailyMatchesPanel";
import { HealthPanel } from "./components/HealthPanel";
import { RefillPanel } from "./components/RefillPanel";
import { fmtAge } from "./components/SourceBadge";
import { RolesPermissionsPanel } from "./components/RolesPermissionsPanel";
import { AuditLogPanel } from "./components/AuditLogPanel";
import { ActivityFeed } from "./components/ActivityFeed";
import { PlayerSearchPanel } from "./components/PlayerSearchPanel";
import { TournamentsPage } from "./components/tournaments/TournamentsPage";
import {
  DlqPanel,
  FlagsPanel,
  IntegrityPanel,
  MetricsTiles,
  SeasonCard,
} from "./components/OverviewPanels";
import { PAGE_META, type View } from "./lib/nav";

/** Views whose content is driven by the live telemetry stream/poll (`t`) and
 *  therefore share its "ainda conectando" loading state. Views backed by
 *  other hooks (riot/daily) or their own fetch (tournaments) or not yet
 *  built (audit/players/roles/activity) manage that on their own. */
const TELEMETRY_VIEWS: View[] = ["visao", "health", "workers", "queues"];

export default function App() {
  const [conn, setConn] = useState<Conn>(() => resolveConn());
  const [intervalMs, setIntervalMs] = useState(1500);
  const [preferStream, setPreferStream] = useState(true);
  const [nonce, setNonce] = useState(0);
  const [view, setView] = useState<View>("visao");
  const [drawerOpen, setDrawerOpen] = useState(false);

  const sync = useCallback(() => setConn(resolveConn()), []);

  const onBackend = useCallback(
    (id: BackendId) => {
      setBackendId(id);
      sync();
    },
    [sync],
  );

  const onUrl = useCallback(
    (url: string) => {
      if (conn.id === "production") setProdUrl(url);
      else if (conn.id === "custom") setCustomUrl(url);
      sync();
    },
    [conn.id, sync],
  );

  const onAuthed = useCallback(
    (key: string) => {
      setAdminKey(key);
      sync();
    },
    [sync],
  );

  const onChangeKey = useCallback(() => {
    clearAdminKey();
    sync();
  }, [sync]);

  const onReconnect = useCallback(() => setNonce((n) => n + 1), []);

  const tele = useTelemetry(conn, { intervalMs, preferStream, nonce });
  const ov = useOverview(conn, 8000, nonce);
  // Faster than the overview poll: the buckets refill over a 10s window, so an
  // 8s cadence would alias the gauge badly.
  const riot = useRiotUsage(conn, 5000, nonce);
  // A daily rollup changes at most once a minute — no need for a fast poll.
  const daily = useDailyMatches(conn, 14, 60000, nonce);
  const operators = useOperators(conn, nonce);
  const audit = useAudit(conn, 20000, nonce);
  const playerSearch = usePlayerSearch(conn);

  // Worker pause/resume needs NO forced reconnect: worker state comes from the
  // telemetry stream/poll, which reports the change within one interval, and the
  // card shows the new state optimistically meanwhile. Bumping `nonce` here used
  // to tear down the SSE stream and blank every sparkline on each click.
  const onWorkerMutated = useCallback(() => {}, []);

  // DLQ / integrity rows come from the slow /admin/overview poll, so those DO
  // need an explicit refetch — but only of that hook, not the whole transport.
  const onOverviewMutated = ov.refresh;

  const locked =
    !conn.key || tele.status === "unauthorized" || tele.status === "unconfigured";

  const lastTs = tele.telemetry?.ts ?? null;
  const t = tele.telemetry;

  const transientError = useMemo(
    () => (tele.status === "error" && t ? tele.error : null),
    [tele.status, tele.error, t],
  );

  const processedToday = useMemo(() => {
    const raw = ov.overview?.metrics.find((m) => m.key === "matchesToday")?.value;
    return raw !== undefined ? Number(raw) : null;
  }, [ov.overview]);

  const pillCounts = useMemo(
    () => ({
      integrity: ov.overview?.integrity.length || undefined,
      flags: ov.overview?.flags.length || undefined,
      dlq: ov.overview?.dlq.length || undefined,
    }),
    [ov.overview],
  );

  const meta = PAGE_META[view];

  return (
    <div className="app">
      <TopBar
        conn={conn}
        status={tele.status}
        transport={tele.transport}
        source={tele.source}
        frames={tele.frames}
        lastTs={lastTs}
        intervalMs={intervalMs}
        onOpenDrawer={() => setDrawerOpen(true)}
      />

      {locked ? (
        <Gate
          conn={conn}
          reason={tele.status}
          onBackend={onBackend}
          onUrl={onUrl}
          onAuthed={onAuthed}
        />
      ) : (
        <div className="shell">
          <Sidebar view={view} onView={setView} pillCounts={pillCounts} />

          <main className="main">
            <div className="page-head">
              <div>
                <h1 className="page-title">{meta.title}</h1>
                <div className="page-desc">{meta.desc}</div>
              </div>
            </div>

            {transientError && (
              <div className="banner banner-warn">
                Conexão instável: {transientError}. Reexibindo o último estado conhecido.
              </div>
            )}

            {/* Procedência da telemetria. Num deploy dividido (API no EC2,
                workers no notebook) esta API pode não enxergar o Redis dos
                workers — e antes disso o console mostrava "fila 0" e "workers
                parados" com toda a confiança. O banner é o que impede o
                operador de diagnosticar uma queda que não existe. */}
            {t && t.dataSource === "snapshot" && TELEMETRY_VIEWS.includes(view) && (
              <div className="banner">
                Telemetria por snapshot da caixa de workers — capturada há{" "}
                {fmtAge(t.ageSeconds)}. Esta API não divide o Redis com eles, então
                fila, workers e uso da Riot são do último instante publicado.
              </div>
            )}

            {t && t.dataSource === "unavailable" && TELEMETRY_VIEWS.includes(view) && (
              <div className="banner banner-warn">
                Sem telemetria dos workers
                {t.ageSeconds == null
                  ? ": a caixa de workers nunca publicou. Verifique se o scheduler dela está no ar."
                  : `: último sinal há ${fmtAge(t.ageSeconds)}. Ela parou de publicar.`}{" "}
                Fila, workers e uso da Riot aparecem vazios porque são
                desconhecidos — não porque estejam zerados.
              </div>
            )}

            {!t && TELEMETRY_VIEWS.includes(view) && (
              <div className="panel connecting">
                <span className="spinner" /> Conectando à telemetria…
              </div>
            )}

            {view === "visao" && t && (
              <>
                {ov.overview && <MetricsTiles metrics={ov.overview.metrics} />}
                <FlowRail t={t} processedToday={processedToday} />
              </>
            )}

            {view === "health" && t && (
              <HealthPanel
                redisAvailable={t.redisAvailable}
                workers={t.workers}
                riotApi={ov.overview?.riotApi ?? []}
              />
            )}

            {view === "workers" && t && (
              <WorkersPanel workers={t.workers} conn={conn} onMutated={onWorkerMutated} dataSource={t.dataSource}
                ageSeconds={t.ageSeconds}
              />
            )}

            {view === "queues" && t && (
              <QueuesPanel queues={t.queues} history={tele.history} />
            )}

            {view === "riot" && <RiotUsagePanel usage={riot.usage} error={riot.error} />}

            {view === "daily" && <DailyMatchesPanel daily={daily.daily} error={daily.error} />}

            {view === "integrity" && ov.overview && (
              <IntegrityPanel
                items={ov.overview.integrity}
                conn={conn}
                onMutated={onOverviewMutated}
              />
            )}

            {view === "flags" && ov.overview && <FlagsPanel flags={ov.overview.flags} />}

            {view === "dlq" && ov.overview && (
              <DlqPanel items={ov.overview.dlq} conn={conn} onMutated={onOverviewMutated} />
            )}

            {view === "season" && ov.overview && <SeasonCard season={ov.overview.season} />}

            {view === "tournaments" && <TournamentsPage conn={conn} />}

            {view === "refill" && <RefillPanel conn={conn} />}

            {view === "audit" && audit.events && <AuditLogPanel events={audit.events} />}
            {view === "audit" && audit.error && (
              <div className="banner banner-warn">{audit.error}</div>
            )}

            {view === "players" && (
              <PlayerSearchPanel
                query={playerSearch.query}
                onQueryChange={playerSearch.setQuery}
                results={playerSearch.results}
                loading={playerSearch.loading}
                conn={conn}
              />
            )}
            {view === "players" && playerSearch.error && (
              <div className="banner banner-warn">{playerSearch.error}</div>
            )}
            {view === "roles" && operators.operators && operators.permissions && (
              <RolesPermissionsPanel
                operators={operators.operators}
                permissions={operators.permissions}
                conn={conn}
                onMutated={operators.refresh}
              />
            )}
            {view === "roles" && operators.error && (
              <div className="banner banner-warn">{operators.error}</div>
            )}
            {view === "activity" && audit.events && <ActivityFeed events={audit.events} />}
            {view === "activity" && audit.error && (
              <div className="banner banner-warn">{audit.error}</div>
            )}

            <footer className="app-foot">
              <span>
                Fonte: <b>{tele.source ?? "—"}</b>
                {tele.source === "overview" &&
                  " (endpoint ao vivo não alcançável — checando /admin/workers/live no backend)"}
              </span>
              <span>Transporte: {tele.transport ?? "—"}</span>
              <span>Frames: {tele.frames}</span>
            </footer>
          </main>
        </div>
      )}

      {drawerOpen && (
        <ConnectionDrawer
          conn={conn}
          preferStream={preferStream}
          intervalMs={intervalMs}
          onBackend={onBackend}
          onUrl={onUrl}
          onToggleStream={setPreferStream}
          onInterval={setIntervalMs}
          onReconnect={onReconnect}
          onChangeKey={onChangeKey}
          onClose={() => setDrawerOpen(false)}
        />
      )}
    </div>
  );
}
