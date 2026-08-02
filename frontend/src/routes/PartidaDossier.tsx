import { useEffect, useRef, type CSSProperties } from "react";

import { ChampIcon, Delta, Mi, Placement } from "../components";
import { fmtCountdown, nf, timeAgo } from "../lib/format";
import "./Partida.css";
import type {
  ProfileAugmentEntry,
  ProfileLoadoutEntry,
} from "./profileMatchDetail";
import {
  comparisonMaximum,
  hasCombatTelemetry,
  playerKda,
  teamMetricTotal,
  type ComparisonMetric,
  type PartidaDossier,
  type PartidaDossierTeam,
} from "./partidaDossierModel";
import { usePartidaDossierMotion } from "./partidaDossierMotion";
import { ProfileRatingSignals } from "./profileRatingSignals";

export interface PartidaDossierViewProps {
  dossier: PartidaDossier;
  selectedTeamIndex: number;
  selectedPlayerRiotId: string;
  onSelectTeam(index: number): void;
  onSelectPlayer(riotId: string): void;
}

function teamCrDelta(team: PartidaDossierTeam): number {
  return team.players.reduce((total, player) => total + player.crDelta, 0);
}

function teamChampionNames(team: PartidaDossierTeam): string {
  return team.players.map((player) => player.championName).join(" · ");
}

function compactNumber(value: number): string {
  if (Math.abs(value) < 1000) return nf(value);

  return `${(value / 1000).toLocaleString("pt-BR", {
    maximumFractionDigits: 1,
  })} mil`;
}

function absolutePlayedAt(value: string): string {
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "long",
    timeStyle: "short",
    timeZone: "America/Sao_Paulo",
  }).format(new Date(value));
}

const comparisonMetrics: Array<{
  key: ComparisonMetric;
  label: string;
  testIdPrefix: string;
  format(value: number): string;
}> = [
  {
    key: "damageToChampions",
    label: "Dano a campeões",
    testIdPrefix: "damage",
    format: compactNumber,
  },
  {
    key: "damagePerMinute",
    label: "Dano por minuto",
    testIdPrefix: "dpm",
    format: compactNumber,
  },
  {
    key: "killParticipation",
    label: "Participação em abates",
    testIdPrefix: "participation",
    format: (value) => `${nf(value)}%`,
  },
  {
    key: "goldEarned",
    label: "Ouro recebido",
    testIdPrefix: "gold",
    format: compactNumber,
  },
];

function scoreMetric(value: number | null | undefined, compact = false): string {
  if (typeof value !== "number") return "—";
  return compact ? compactNumber(value) : nf(value);
}

function scoreKda(team: PartidaDossierTeam): string {
  const kills = teamMetricTotal(team, "kills");
  const deaths = teamMetricTotal(team, "deaths");
  const assists = teamMetricTotal(team, "assists");

  if (kills === null || deaths === null || assists === null) return "—";
  return `${nf(kills)}/${nf(deaths)}/${nf(assists)}`;
}

function teamCr(team: PartidaDossierTeam): number {
  return team.players.reduce((total, player) => total + player.crAfter, 0);
}

function PlayerLoadout({
  player,
}: {
  player: PartidaDossierTeam["players"][number];
}) {
  if (player.items == null && player.augments == null) {
    return <>—</>;
  }

  const entries = [...(player.items ?? []), ...(player.augments ?? [])];
  if (!entries.length) return <>Sem loadout</>;

  return (
    <>
      {entries.map((entry, index) => (
        <span key={`${entry.id}-${index}`}>{entry.name}</span>
      ))}
    </>
  );
}

function LoadoutEntryView({
  entry,
  augment,
}: {
  entry: ProfileLoadoutEntry | ProfileAugmentEntry;
  augment?: boolean;
}): JSX.Element {
  const rarity = augment && "rarity" in entry ? entry.rarity : undefined;

  return (
    <div
      className={`partida-loadout-entry${augment ? " is-augment" : ""}`}
      data-match-item={augment ? undefined : ""}
      data-match-augment={augment ? "" : undefined}
      data-rarity={rarity}
    >
      {entry.iconUrl ? (
        <img src={entry.iconUrl} alt={entry.name} loading="lazy" decoding="async" />
      ) : (
        <span aria-label={entry.name}>{augment ? "A" : "I"}</span>
      )}
      <span>{entry.name}</span>
    </div>
  );
}

export function PartidaDossierView({
  dossier,
  selectedTeamIndex,
  selectedPlayerRiotId,
  onSelectTeam,
  onSelectPlayer,
}: PartidaDossierViewProps): JSX.Element {
  const scopeRef = useRef<HTMLElement>(null);
  const previousTeam = useRef(selectedTeamIndex);
  const selectedTeam = dossier.teams[selectedTeamIndex] ?? dossier.teams[0];
  const { detail } = dossier;
  const direction: -1 | 0 | 1 =
    selectedTeamIndex === previousTeam.current
      ? 0
      : selectedTeamIndex > previousTeam.current
        ? 1
        : -1;

  usePartidaDossierMotion(scopeRef, {
    teamKey: selectedTeamIndex,
    playerKey: selectedPlayerRiotId,
    direction,
    ready: Boolean(selectedTeam?.players.length),
  });

  useEffect(() => {
    previousTeam.current = selectedTeamIndex;
  }, [selectedTeamIndex]);

  if (!selectedTeam) {
    return <section aria-label="Dossiê da partida">Nenhuma equipe registrada.</section>;
  }

  const selectedCrDelta = teamCrDelta(selectedTeam);
  const focusedPlayer = selectedTeam.players.find(
    (player) => player.riotId === selectedPlayerRiotId,
  ) ?? selectedTeam.players[0];

  if (!focusedPlayer) {
    return <section aria-label="Dossiê da partida">Nenhum jogador registrado.</section>;
  }

  const kda = playerKda(focusedPlayer);
  const focusedHasTelemetry = hasCombatTelemetry(focusedPlayer);
  const selectedTeamKills = teamMetricTotal(selectedTeam, "kills");
  const selectedTeamDeaths = teamMetricTotal(selectedTeam, "deaths");
  const selectedTeamAssists = teamMetricTotal(selectedTeam, "assists");
  const selectedTeamDamage = teamMetricTotal(
    selectedTeam,
    "damageToChampions",
  );
  const selectedTeamGold = teamMetricTotal(selectedTeam, "goldEarned");
  const selectedTeamHasKda =
    selectedTeamKills !== null &&
    selectedTeamDeaths !== null &&
    selectedTeamAssists !== null;
  const comparisonGroups = comparisonMetrics.map((metric) => ({
    ...metric,
    maximum: comparisonMaximum(dossier.teams, metric.key),
  }));
  const hasComparisons = comparisonGroups.some(({ maximum }) => maximum !== null);
  const publicIntegrity = dossier.teams.flatMap((team) =>
    team.players.flatMap((player) =>
      (player.integrity ?? []).map((flag) => ({ player, flag })),
    ),
  );

  return (
    <section
      ref={scopeRef}
      className="partida-dossier"
      aria-label="Dossiê da partida"
    >
      <header className="partida-dossier-hero">
        <div data-hero-copy="">
          <p className="eyebrow">Partida completa</p>
          <h1>{detail.queueLabel}</h1>
          <p>
            <Mi name="swords" /> {detail.format.toUpperCase()} · {nf(dossier.teams.length)} equipes
          </p>
        </div>
        <div data-hero-copy="" aria-label="Metadados públicos da partida">
          <p>
            <Mi name="schedule" />{" "}
            <time dateTime={detail.playedAt}>
              {timeAgo(detail.playedAt)} · {absolutePlayedAt(detail.playedAt)}
            </time>
          </p>
          <p>
            <Mi name="timer" /> Duração {fmtCountdown(detail.durationSec)}
          </p>
          <p>Patch {detail.patch}</p>
        </div>
      </header>

      {dossier.demo && (
        <aside
          className="partida-demo-disclosure"
          role="status"
          aria-label="Aviso de dados demonstrativos"
          data-demo-disclosure=""
        >
          <Mi name="science" />
          <strong>Dados demonstrativos</strong>
          <span>
            Telemetria complementar simulada apenas para pré-visualização local.
          </span>
        </aside>
      )}

      <div className="partida-orbital" data-testid="orbital-map">
        <nav aria-label="Equipes da partida">
          {dossier.teams.map((team, index) => (
            <button
              key={team.placement}
              type="button"
              className={`partida-orbital-team pd-orbit-node--${index + 1}`}
              data-orbit-node=""
              aria-label={`Selecionar equipe ${team.placement}, ${team.placement}º lugar`}
              aria-pressed={index === selectedTeamIndex}
              onClick={() => onSelectTeam(index)}
            >
              <Placement place={team.placement} />
              <span aria-hidden="true">
                {team.players.map((player) => (
                  <ChampIcon
                    key={player.riotId}
                    colors={player.champion}
                    url={player.championIconUrl}
                    alt=""
                    size="sm"
                  />
                ))}
              </span>
            </button>
          ))}
        </nav>

        <div
          className="partida-orbital-summary"
          data-orbit-core=""
          data-team-swap=""
          data-testid="orbital-summary"
          aria-live="polite"
        >
          <Placement place={selectedTeam.placement} />
          <h2>{teamChampionNames(selectedTeam)}</h2>
          <p>{nf(selectedTeam.players.length)} jogadores</p>
          <p>CR agregado {nf(teamCr(selectedTeam))}</p>
          <p className="partida-orbital-result">
            Resultado da equipe <Delta value={selectedCrDelta} /> PDL
          </p>
          <div
            className="partida-orbital-totals"
            aria-label="Totais completos da equipe"
          >
            {selectedTeamHasKda && (
              <p>
                K/D/A {nf(selectedTeamKills)}/{nf(selectedTeamDeaths)}/
                {nf(selectedTeamAssists)}
              </p>
            )}
            {selectedTeamDamage !== null && (
              <p>Dano da equipe {compactNumber(selectedTeamDamage)}</p>
            )}
            {selectedTeamGold !== null && (
              <p>Ouro da equipe {compactNumber(selectedTeamGold)}</p>
            )}
          </div>
        </div>
      </div>

      <section
        className="partida-team-lab"
        data-dossier-section=""
        aria-label="Laboratório da equipe"
      >
        <header>
          <p className="eyebrow">Equipe selecionada</p>
          <h2>Jogadores</h2>
        </header>
        <div className="partida-team-players">
          {selectedTeam.players.map((player) => {
            const playerAma = playerKda(player);

            return (
              <button
                key={player.riotId}
                type="button"
                className="partida-team-player"
                data-team-player=""
                data-selected={player.riotId === focusedPlayer.riotId ? "true" : undefined}
                aria-label={`Selecionar ${player.name}, ${player.championName}, para análise`}
                aria-pressed={player.riotId === selectedPlayerRiotId}
                onClick={() => onSelectPlayer(player.riotId)}
              >
                <ChampIcon
                  colors={player.champion}
                  url={player.championIconUrl}
                  alt=""
                  size="sm"
                />
                <span className="partida-team-player-name">{player.name}</span>
                <span className="partida-team-player-id">{player.riotId}</span>
                <span className="partida-team-player-champion">
                  {player.championName}
                </span>
                <span className="partida-team-player-rating">
                  PDL <Delta value={player.crDelta} />
                </span>
                {playerAma !== null && (
                  <span className="partida-team-player-kda">
                    {player.kills}/{player.deaths}/{player.assists}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </section>

      <section
        className="partida-player-analysis"
        aria-label={`Análise de ${focusedPlayer.name}`}
        data-dossier-section=""
        data-focused-player=""
      >
        <header>
          <p className="eyebrow">Laboratório do jogador</p>
          <h2>{focusedPlayer.name}</h2>
          <p>{focusedPlayer.riotId}</p>
        </header>

        {focusedHasTelemetry ? (
          <div className="partida-combat-stats">
            <p>
              K/D/A {scoreMetric(focusedPlayer.kills)}/
              {scoreMetric(focusedPlayer.deaths)}/
              {scoreMetric(focusedPlayer.assists)}
            </p>
            <p>
              AMA {kda === null
                ? "—"
                : kda.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}
            </p>
            {typeof focusedPlayer.level === "number" && (
              <p>Nível {nf(focusedPlayer.level)}</p>
            )}
            {typeof focusedPlayer.killParticipation === "number" && (
              <p>Participação {nf(focusedPlayer.killParticipation)}%</p>
            )}
            {typeof focusedPlayer.damageToChampions === "number" && (
              <p>Dano {compactNumber(focusedPlayer.damageToChampions)}</p>
            )}
            {typeof focusedPlayer.damagePerMinute === "number" && (
              <p>DPM {compactNumber(focusedPlayer.damagePerMinute)}</p>
            )}
            {typeof focusedPlayer.goldEarned === "number" && (
              <p>Ouro {compactNumber(focusedPlayer.goldEarned)}</p>
            )}
          </div>
        ) : (
          <p>Telemetria não registrada nesta partida</p>
        )}

        <div className="partida-rating-summary">
          <p>{nf(focusedPlayer.crBefore)} CR → {nf(focusedPlayer.crAfter)} CR</p>
          <p>PDL final {nf(focusedPlayer.crAfter)}</p>
        </div>

        <section aria-label="Itens da partida">
          <h3>Build</h3>
          {focusedPlayer.items == null ? (
            <p>Build não registrada</p>
          ) : focusedPlayer.items.length ? (
            focusedPlayer.items.map((item, index) => (
              <LoadoutEntryView entry={item} key={`${item.id}-${index}`} />
            ))
          ) : (
            <p>Nenhum item final nesta partida</p>
          )}
        </section>

        <section aria-label="Augments da partida">
          <h3>Augments</h3>
          {focusedPlayer.augments == null ? (
            <p>Augments não registrados</p>
          ) : focusedPlayer.augments.length ? (
            focusedPlayer.augments.map((augment, index) => (
              <LoadoutEntryView
                augment
                entry={augment}
                key={`${augment.id}-${index}`}
              />
            ))
          ) : (
            <p>Nenhum augment nesta partida</p>
          )}
        </section>

        <ProfileRatingSignals
          modifiers={focusedPlayer.modifiers}
          placement={selectedTeam.placement}
          premade={focusedPlayer.premade ?? false}
          crDelta={focusedPlayer.crDelta}
        />
      </section>

      <section
        className="partida-scoreboard"
        data-dossier-section=""
        aria-label="Placar completo da partida"
      >
        <header>
          <p className="eyebrow">Todos os competidores</p>
          <h2>Placar completo</h2>
        </header>
        <div className="partida-scoreboard-table">
          <table>
            <caption>Desempenho de todos os jogadores por colocação</caption>
            <thead>
              <tr>
                <th scope="col">Colocação</th>
                <th scope="col">Campeão e Riot ID</th>
                <th scope="col">Nível</th>
                <th scope="col">K/D/A</th>
                <th scope="col">AMA</th>
                <th scope="col">Participação</th>
                <th scope="col">Dano</th>
                <th scope="col">DPM</th>
                <th scope="col">Ouro</th>
                <th scope="col">Loadout</th>
                <th scope="col">CR</th>
                <th scope="col">PDL</th>
              </tr>
            </thead>
            {dossier.teams.map((team, teamIndex) => {
              const teamSelected = teamIndex === selectedTeamIndex;

              return (
                <tbody
                  key={team.placement}
                  className={teamSelected ? "is-selected-team" : undefined}
                  data-score-team=""
                  data-selected-team={teamSelected ? "true" : undefined}
                >
                  <tr className="partida-score-team-total">
                    <th scope="rowgroup">
                      <Placement place={team.placement} />
                    </th>
                    <th scope="row">Totais da equipe</th>
                    <td>—</td>
                    <td>{scoreKda(team)}</td>
                    <td>—</td>
                    <td>—</td>
                    <td>
                      {scoreMetric(
                        teamMetricTotal(team, "damageToChampions"),
                        true,
                      )}
                    </td>
                    <td>—</td>
                    <td>
                      {scoreMetric(teamMetricTotal(team, "goldEarned"), true)}
                    </td>
                    <td>—</td>
                    <td>{nf(teamCr(team))}</td>
                    <td><Delta value={teamCrDelta(team)} /> PDL</td>
                  </tr>
                  {team.players.map((player) => {
                    const playerAma = playerKda(player);
                    const playerSelected =
                      player.riotId === selectedPlayerRiotId;

                    return (
                      <tr
                        key={player.riotId}
                        className={playerSelected ? "is-selected-player" : undefined}
                        data-score-player=""
                        data-selected-player={playerSelected ? "true" : undefined}
                        data-testid="score-player"
                      >
                        <td>{team.placement}º</td>
                        <th scope="row">
                          <button
                            type="button"
                            aria-label={`Selecionar ${player.name} no placar`}
                            aria-pressed={playerSelected}
                            onClick={() => {
                              onSelectTeam(teamIndex);
                              onSelectPlayer(player.riotId);
                            }}
                          >
                            <ChampIcon
                              colors={player.champion}
                              url={player.championIconUrl}
                              alt=""
                              size="sm"
                            />
                            <span>{player.championName}</span>
                            <span>{player.riotId}</span>
                          </button>
                        </th>
                        <td>{scoreMetric(player.level)}</td>
                        <td>
                          {playerAma !== null
                            ? `${player.kills}/${player.deaths}/${player.assists}`
                            : "—"}
                        </td>
                        <td>
                          {playerAma === null
                            ? "—"
                            : playerAma.toLocaleString("pt-BR", {
                                maximumFractionDigits: 1,
                              })}
                        </td>
                        <td>
                          {typeof player.killParticipation !== "number"
                            ? "—"
                            : `${nf(player.killParticipation)}%`}
                        </td>
                        <td>{scoreMetric(player.damageToChampions, true)}</td>
                        <td>{scoreMetric(player.damagePerMinute, true)}</td>
                        <td>{scoreMetric(player.goldEarned, true)}</td>
                        <td><PlayerLoadout player={player} /></td>
                        <td>{nf(player.crAfter)}</td>
                        <td><Delta value={player.crDelta} /> PDL</td>
                      </tr>
                    );
                  })}
                </tbody>
              );
            })}
          </table>
        </div>
      </section>

      {hasComparisons ? (
        <section
          className="partida-comparisons"
          data-dossier-section=""
          data-comparison-section=""
          aria-label="Comparativos de combate"
        >
          <header>
            <p className="eyebrow">Escala da partida</p>
            <h2>Comparativos de combate</h2>
          </header>
          {comparisonGroups.map((metric) => {
            const maximum = metric.maximum;
            if (maximum === null) return null;

            return (
              <section key={metric.key} aria-label={metric.label}>
                <h3>{metric.label}</h3>
                <ul>
                  {dossier.teams.flatMap((team) =>
                    team.players.map((player) => {
                      const value = player[metric.key];

                      if (typeof value !== "number") {
                        return (
                          <li key={player.riotId}>
                            <span>{player.name}</span>
                            <span>—</span>
                          </li>
                        );
                      }

                      const railValue = maximum === 0
                        ? 0
                        : Math.max(
                            0,
                            Math.min(100, (value / maximum) * 100),
                          );

                      return (
                        <li
                          key={player.riotId}
                          data-comparison-rail=""
                          data-testid={`${metric.testIdPrefix}-${player.riotId}`}
                          style={{
                            "--rail-value": `${railValue}%`,
                          } as CSSProperties}
                        >
                          <span>{player.name}</span>
                          <span aria-hidden="true" className="partida-comparison-mark" />
                          <strong>{metric.format(value)}</strong>
                        </li>
                      );
                    }),
                  )}
                </ul>
              </section>
            );
          })}
        </section>
      ) : (
        <p className="partida-comparisons-unavailable">
          Comparativos indisponíveis para esta partida
        </p>
      )}

      <section
        className="partida-public-integrity"
        data-dossier-section=""
        aria-label="Integridade pública da partida"
      >
        <header>
          <p className="eyebrow">Jogo limpo</p>
          <h2>Integridade pública</h2>
        </header>
        {publicIntegrity.length ? (
          <ul>
            {publicIntegrity.map(({ player, flag }, index) => (
              <li key={`${player.riotId}-${flag.label}-${index}`}>
                <strong>{player.name}</strong>
                <span>{flag.label}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p>Sem violações detectadas nesta partida</p>
        )}
      </section>
    </section>
  );
}
