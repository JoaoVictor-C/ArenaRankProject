import { Mi } from "../components";
import type { PdlExplanation, PdlLedgerEntry } from "../lib/types";
import "./PdlLedger.css";

function formatPdl(value: number): string {
  if (value > 0) return `+${value}`;
  if (value < 0) return `−${Math.abs(value)}`;
  return "0";
}

function formatPct(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  if (rounded > 0) return `+${rounded}%`;
  if (rounded < 0) return `−${Math.abs(rounded)}%`;
  return "0%";
}

const FIDELITY_NOTE: Record<Exclude<PdlExplanation["fidelity"], "exato">, string> = {
  derivado:
    "Alguns valores desta partida foram recalculados a partir do estado salvo — o total continua exato.",
  parcial:
    "Esta partida foi registrada antes do detalhamento completo do Raio-X — alguns fatores aparecem consolidados em uma única linha.",
};

function rowLabel(entry: PdlLedgerEntry, explanation: PdlExplanation): string {
  if (entry.kind === "cap" && explanation.cap.label) return explanation.cap.label;
  return entry.label;
}

function rowNote(entry: PdlLedgerEntry, explanation: PdlExplanation): string | null {
  if (entry.kind === "cap" && explanation.cap.description) {
    return explanation.cap.description;
  }
  return entry.note ?? null;
}

export interface PdlLedgerProps {
  explanation: PdlExplanation;
}

interface FactorRow {
  key: string;
  icon: string;
  label: string;
  pct: number;
  note: string;
}

function capFactorRows(explanation: PdlExplanation): FactorRow[] {
  const { factors } = explanation.cap;
  const rows: FactorRow[] = [];
  if (typeof factors.mismatchBonusPct === "number" && Math.abs(factors.mismatchBonusPct) > 0.05) {
    rows.push({
      key: "mismatch",
      icon: "trending_up",
      label: "Vantagem por diferença de nível",
      pct: factors.mismatchBonusPct,
      note: "Sua equipe entrou como favorita nesta partida, então o teto de ganho desta colocação subiu.",
    });
  }
  if (
    typeof factors.highCrReductionPct === "number" &&
    Math.abs(factors.highCrReductionPct) > 0.05
  ) {
    rows.push({
      key: "highCr",
      icon: "trending_down",
      label: "Redução por CR alto",
      pct: factors.highCrReductionPct,
      note: "Quanto mais alto o seu CR, menor o teto de ganho por partida — evita que o topo da tabela infle rápido demais.",
    });
  }
  if (typeof factors.compositePct === "number" && Math.abs(factors.compositePct) > 0.05) {
    rows.push({
      key: "composite",
      icon: "tune",
      label: "Efeito combinado no teto de ganho",
      pct: factors.compositePct,
      note: "A soma dos ajustes acima — o quanto o SEU teto de ganho desta colocação difere do valor padrão da curva.",
    });
  }
  return rows;
}

/** Raio-X do resultado — "ver cálculo completo". Uma linha por fator, na ordem
 *  em que o motor os aplicou, com o total exibido reconciliando exatamente a
 *  soma das linhas (`arena/rating/explain.py` garante isso no backend; aqui só
 *  renderizamos o que chega). */
export function PdlLedger({ explanation }: PdlLedgerProps) {
  const nonZero = explanation.entries.filter((entry) => entry.pdl !== 0);
  const rows = nonZero.length > 0 ? nonZero : explanation.entries.slice(0, 1);
  const hasCapRow = rows.some((entry) => entry.kind === "cap");
  const showCapNote =
    !hasCapRow && explanation.cap.active && explanation.cap.rule !== "nenhum" && explanation.cap.description;
  const factorRows = capFactorRows(explanation);
  const curve = explanation.cap.placementCurve;
  const lobby = explanation.lobby;

  return (
    <div className="pdl-ledger">
      {explanation.fidelity !== "exato" && (
        <p className="pdl-ledger-note">
          <Mi name="info" />
          <span>{FIDELITY_NOTE[explanation.fidelity]}</span>
        </p>
      )}

      {showCapNote && (
        <p className="pdl-ledger-note">
          <Mi name="shield" />
          <span>
            <b>{explanation.cap.label}.</b> {explanation.cap.description}
          </span>
        </p>
      )}

      <ul className="pdl-ledger-rows">
        {rows.map((entry, index) => (
          <li
            key={`${entry.kind}-${index}`}
            className={`pdl-ledger-row ${entry.pdl >= 0 ? "is-positive" : "is-negative"}${
              entry.exact ? "" : " is-inexact"
            }`}
          >
            <span className="pdl-ledger-icon" aria-hidden="true">
              <Mi name={entry.icon} />
            </span>
            <span className="pdl-ledger-text">
              <b>{rowLabel(entry, explanation)}</b>
              {rowNote(entry, explanation) && <small>{rowNote(entry, explanation)}</small>}
            </span>
            <span className="pdl-ledger-value">{formatPdl(entry.pdl)}</span>
          </li>
        ))}
      </ul>

      <div className="pdl-ledger-total">
        <span>Total</span>
        <strong>{formatPdl(explanation.totalPdl)} PDL</strong>
      </div>

      {!explanation.reconciles && (
        <p className="pdl-ledger-note is-warning">
          <Mi name="warning" />
          <span>
            Diferença residual de {explanation.residualPdl.toFixed(3)} PDL entre as linhas e o
            total — arredondamento de ponto flutuante, não um valor real.
          </span>
        </p>
      )}

      {factorRows.length > 0 && (
        <div className="pdl-ledger-section">
          <h4 className="pdl-ledger-section-title">Por que o seu teto de ganho é este</h4>
          <ul className="pdl-ledger-factors">
            {factorRows.map((row) => (
              <li key={row.key} className="pdl-ledger-factor">
                <span className="pdl-ledger-icon" aria-hidden="true">
                  <Mi name={row.icon} />
                </span>
                <span className="pdl-ledger-text">
                  <b>{row.label}</b>
                  <small>{row.note}</small>
                </span>
                <span className={`pdl-ledger-pct ${row.pct >= 0 ? "is-positive" : "is-negative"}`}>
                  {formatPct(row.pct)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {curve.length > 0 && (
        <div className="pdl-ledger-section">
          <h4 className="pdl-ledger-section-title">
            Curva de colocação ({explanation.teamCount} equipes)
          </h4>
          <p className="pdl-ledger-section-hint">
            O teto/piso PADRÃO de cada colocação nesta partida — antes de qualquer ajuste por
            diferença de nível ou CR alto (acima).
          </p>
          <div className="pdl-ledger-curve">
            {curve.map((point) => (
              <div
                key={point.placement}
                className={`pdl-ledger-curve-row${
                  point.placement === explanation.placement ? " is-you" : ""
                }`}
              >
                <span className="pdl-ledger-curve-place">{point.placement}º</span>
                <span className="pdl-ledger-curve-bounds">
                  {point.minGain > 0 && <span className="is-floor">piso {formatPdl(point.minGain)}</span>}
                  <span className="is-positive">{formatPdl(point.gainCap)}</span>
                  <span className="pdl-ledger-curve-sep">·</span>
                  <span className="is-negative">{formatPdl(point.lossCap)}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {lobby.length > 1 && (
        <div className="pdl-ledger-section">
          <h4 className="pdl-ledger-section-title">Resultado de todas as equipes</h4>
          <ul className="pdl-ledger-lobby">
            {lobby.map((entry) => (
              <li
                key={entry.riotId}
                className={`pdl-ledger-lobby-row${entry.isYou ? " is-you" : ""}`}
              >
                <span className="pdl-ledger-lobby-place">{entry.placement}º</span>
                <span className="pdl-ledger-lobby-name">{entry.isYou ? "Você" : entry.name}</span>
                <span
                  className={`pdl-ledger-value ${entry.crDelta >= 0 ? "is-positive" : "is-negative"}`}
                >
                  {formatPdl(entry.crDelta)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
