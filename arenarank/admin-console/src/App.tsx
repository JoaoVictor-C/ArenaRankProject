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
import { TopBar } from "./components/TopBar";
import { Gate } from "./components/Gate";
import { FlowRail } from "./components/FlowRail";
import { WorkersPanel } from "./components/WorkersPanel";
import { QueuesPanel } from "./components/QueuesPanel";
import {
  DlqPanel,
  FlagsPanel,
  IntegrityPanel,
  MetricsTiles,
  SeasonCard,
} from "./components/OverviewPanels";

export default function App() {
  const [conn, setConn] = useState<Conn>(() => resolveConn());
  const [intervalMs, setIntervalMs] = useState(1500);
  const [preferStream, setPreferStream] = useState(true);
  const [nonce, setNonce] = useState(0);

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
  const onMutated = useCallback(() => setNonce((n) => n + 1), []);

  const tele = useTelemetry(conn, { intervalMs, preferStream, nonce });
  const ov = useOverview(conn, 8000, nonce);

  const locked =
    !conn.key || tele.status === "unauthorized" || tele.status === "unconfigured";

  const lastTs = tele.telemetry?.ts ?? null;
  const t = tele.telemetry;

  const transientError = useMemo(
    () => (tele.status === "error" && t ? tele.error : null),
    [tele.status, tele.error, t],
  );

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
        preferStream={preferStream}
        onBackend={onBackend}
        onUrl={onUrl}
        onInterval={setIntervalMs}
        onToggleStream={setPreferStream}
        onReconnect={onReconnect}
        onChangeKey={onChangeKey}
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
        <main className="main">
          {transientError && (
            <div className="banner banner-warn">
              Conexão instável: {transientError}. Reexibindo o último estado conhecido.
            </div>
          )}

          {ov.overview && <MetricsTiles metrics={ov.overview.metrics} />}

          {t ? (
            <>
              <FlowRail t={t} />
              <WorkersPanel workers={t.workers} conn={conn} onMutated={onMutated} />
              <div className="cols cols-2">
                <QueuesPanel queues={t.queues} history={tele.history} />
                {ov.overview && <SeasonCard season={ov.overview.season} />}
              </div>
            </>
          ) : (
            <div className="panel connecting">
              <span className="spinner" /> Conectando à telemetria…
            </div>
          )}

          {ov.overview && (
            <div className="cols cols-3">
              <DlqPanel items={ov.overview.dlq} conn={conn} onMutated={onMutated} />
              <IntegrityPanel items={ov.overview.integrity} conn={conn} onMutated={onMutated} />
              <FlagsPanel flags={ov.overview.flags} />
            </div>
          )}

          <footer className="app-foot">
            <span>
              Fonte: <b>{tele.source ?? "—"}</b>
              {tele.source === "overview" && " (endpoint ao vivo não conectado — veja BACKEND_SETUP.md)"}
            </span>
            <span>Transporte: {tele.transport ?? "—"}</span>
            <span>Frames: {tele.frames}</span>
          </footer>
        </main>
      )}
    </div>
  );
}
