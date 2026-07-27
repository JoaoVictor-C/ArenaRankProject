/* Health page: not a new data source — a per-service read of the same
   telemetry/overview data the Workers and Riot pages already show, just
   rolled up into one status list (Redis, each worker pool, each Riot
   bucket-limiter target). */
import type { AdminRiotApi, NormWorker } from "../lib/types";

interface Props {
  redisAvailable: boolean | null;
  workers: NormWorker[];
  riotApi: AdminRiotApi[];
}

type Tone = "ok" | "warn" | "down";

const WORKER_TONE: Record<NormWorker["health"], Tone> = {
  active: "ok",
  idle: "ok",
  paused: "warn",
  warn: "warn",
  down: "down",
};

function Row({ tone, name, detail }: { tone: Tone; name: string; detail: string }) {
  return (
    <div className="health-row">
      <span className={`health-dot health-${tone}`} aria-hidden="true" />
      <span className="health-name">{name}</span>
      <span className="health-detail">{detail}</span>
    </div>
  );
}

export function HealthPanel({ redisAvailable, workers, riotApi }: Props) {
  const redisTone: Tone = redisAvailable === false ? "down" : "ok";
  const okCount =
    (redisAvailable !== false ? 1 : 0) +
    workers.filter((w) => WORKER_TONE[w.health] === "ok").length +
    riotApi.filter((r) => r.status === "ok").length;
  const total = 1 + workers.length + riotApi.length;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Saúde do sistema</h2>
        <span className="panel-note">
          {okCount} de {total} respondendo
        </span>
      </div>
      <div className="rows">
        <Row
          tone={redisTone}
          name="Redis"
          detail={redisAvailable === false ? "indisponível" : "disponível"}
        />
        {workers.map((w) => (
          <Row
            key={w.name}
            tone={WORKER_TONE[w.health]}
            name={w.label}
            detail={w.health}
          />
        ))}
        {riotApi.map((r) => (
          <Row key={r.name} tone={r.status === "ok" ? "ok" : "warn"} name={r.name} detail={r.usage} />
        ))}
      </div>
    </section>
  );
}
