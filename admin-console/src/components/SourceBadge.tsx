import type { TelemetrySource } from "../lib/types";

/* Selo de procedência de um painel de telemetria.
 *
 * Existe por causa do deploy dividido (API pública no EC2, workers no
 * notebook): as duas caixas têm Redis SEPARADOS, e filas/heartbeats/token-bucket
 * só existem na caixa de workers. Lendo do EC2, o console não ficava sem dado —
 * ficava com o dado ERRADO: fila 0 (contra 166 reais) e todo worker
 * `active: false`. Um operador olha isso e vai caçar uma queda que não houve.
 *
 * O selo torna a diferença visível: ao vivo, snapshot com idade, ou
 * indisponível. "Não sei" é uma resposta melhor que um zero convincente. */

export function fmtAge(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`;
  const min = Math.floor(seconds / 60);
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} h`;
  return `${Math.floor(h / 24)} d`;
}

interface Props {
  source?: TelemetrySource;
  ageSeconds?: number | null;
  /** Rótulo curto do que o painel mostra, usado no title (tooltip). */
  what?: string;
}

export function SourceBadge({ source, ageSeconds, what = "telemetria" }: Props) {
  // Backend antigo (sem o campo) => trate como ao vivo, que era o
  // comportamento anterior. Nunca invente "indisponível" por omissão.
  const src: TelemetrySource = source ?? "live";

  if (src === "live") {
    return (
      <span className="src-badge src-live" title={`${what} lida ao vivo do Redis desta caixa`}>
        ao vivo
      </span>
    );
  }
  if (src === "snapshot") {
    return (
      <span
        className="src-badge src-snapshot"
        title={`${what} publicada pela caixa de workers via banco · capturada há ${fmtAge(ageSeconds)}`}
      >
        snapshot · {fmtAge(ageSeconds)}
      </span>
    );
  }
  return (
    <span
      className="src-badge src-unavailable"
      title={
        ageSeconds == null
          ? `Sem ${what}: a caixa de workers nunca publicou. Verifique se o scheduler dela está no ar.`
          : `Sem ${what} atual: último sinal há ${fmtAge(ageSeconds)}. A caixa de workers parou de publicar.`
      }
    >
      {ageSeconds == null ? "indisponível" : `sem sinal há ${fmtAge(ageSeconds)}`}
    </span>
  );
}

/** True quando o painel NÃO deve desenhar números como se fossem atuais. */
export function isUnavailable(source?: TelemetrySource): boolean {
  return (source ?? "live") === "unavailable";
}
