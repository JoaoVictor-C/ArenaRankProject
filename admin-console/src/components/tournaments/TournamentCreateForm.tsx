import { useState } from "react";
import type { Conn } from "../../lib/backend";
import { createTournament } from "../../lib/tournamentActions";
import type { Currency, TournamentFormat } from "../../lib/types";

interface Props {
  conn: Conn;
  onCreated: (id: string) => void;
  onCancel: () => void;
}

/** datetime-local (no timezone) -> ISO UTC string, or undefined if left blank. */
function toIso(local: string): string | undefined {
  if (!local) return undefined;
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

export function TournamentCreateForm({ conn, onCreated, onCancel }: Props) {
  const [title, setTitle] = useState("");
  const [format, setFormat] = useState<TournamentFormat>("3v3");
  const [numTeams, setNumTeams] = useState(6);
  const [numMatches, setNumMatches] = useState(3);
  const [prizeRp, setPrizeRp] = useState(5000);
  const [startsAt, setStartsAt] = useState("");
  const [tag, setTag] = useState("");
  const [currency, setCurrency] = useState<Currency>("RP");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (title.trim().length < 2) {
      setErr("Título precisa de ao menos 2 caracteres.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const detail = await createTournament(conn, {
        title: title.trim(),
        format,
        numTeams,
        numMatches,
        prizeRp,
        startsAt: toIso(startsAt) ?? null,
        tag: tag.trim() || null,
        currency,
      });
      onCreated(detail.id);
    } catch (e2) {
      setErr((e2 as Error).message ?? "Falha ao criar campeonato");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="tourn-form" onSubmit={submit}>
      {err && <div className="row-err">{err}</div>}
      <div className="tourn-form-grid">
        <label className="tourn-field tourn-field-wide">
          <span>Título</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Copa Arena de Verão"
            maxLength={80}
            required
          />
        </label>
        <label className="tourn-field">
          <span>Formato</span>
          <select value={format} onChange={(e) => setFormat(e.target.value as TournamentFormat)}>
            <option value="3v3">3v3</option>
            <option value="2v2">2v2</option>
          </select>
        </label>
        <label className="tourn-field">
          <span>Nº de equipes</span>
          <input
            type="number"
            min={2}
            max={16}
            value={numTeams}
            onChange={(e) => setNumTeams(Number(e.target.value))}
          />
        </label>
        <label className="tourn-field">
          <span>Nº de partidas</span>
          <input
            type="number"
            min={1}
            max={10}
            value={numMatches}
            onChange={(e) => setNumMatches(Number(e.target.value))}
          />
        </label>
        <label className="tourn-field">
          <span>Prêmio</span>
          <input
            type="number"
            min={0}
            value={prizeRp}
            onChange={(e) => setPrizeRp(Number(e.target.value))}
          />
        </label>
        <label className="tourn-field">
          <span>Moeda</span>
          <select value={currency} onChange={(e) => setCurrency(e.target.value as Currency)}>
            <option value="RP">RP</option>
            <option value="BRL">BRL</option>
          </select>
        </label>
        <label className="tourn-field">
          <span>Início</span>
          <input
            type="datetime-local"
            value={startsAt}
            onChange={(e) => setStartsAt(e.target.value)}
          />
        </label>
        <label className="tourn-field">
          <span>Tag</span>
          <input
            value={tag}
            onChange={(e) => setTag(e.target.value)}
            placeholder="ABERTO"
            maxLength={32}
          />
        </label>
      </div>
      <div className="row-actions">
        <button className="mini" type="button" onClick={onCancel} disabled={busy}>
          Cancelar
        </button>
        <button className="mini is-primary" type="submit" disabled={busy}>
          {busy ? "…" : "Criar campeonato"}
        </button>
      </div>
    </form>
  );
}
