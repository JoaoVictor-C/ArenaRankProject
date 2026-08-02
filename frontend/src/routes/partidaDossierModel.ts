import { api } from "../lib/api";
import type { MatchDetail } from "../lib/types";
import {
  adaptProfileMatchDetail,
  enrichProfileMatchDetail,
  loadProfileMatchFixture,
  type ProfileMatchDetail,
  type ProfileMatchFixture,
  type ProfileMatchPlayer,
  type ProfileMatchTeam,
} from "./profileMatchDetail";

export type ComparisonMetric =
  | "damageToChampions"
  | "damagePerMinute"
  | "killParticipation"
  | "goldEarned";

type TeamTotalMetric =
  | "kills"
  | "deaths"
  | "assists"
  | "damageToChampions"
  | "goldEarned";

type CombatMetric =
  | "level"
  | "kills"
  | "deaths"
  | "assists"
  | "killParticipation"
  | "damageToChampions"
  | "damagePerMinute"
  | "goldEarned";

type NullableCombatMetrics = {
  [Metric in CombatMetric]?: number | null;
};

const COMBAT_METRICS: CombatMetric[] = [
  "level",
  "kills",
  "deaths",
  "assists",
  "killParticipation",
  "damageToChampions",
  "damagePerMinute",
  "goldEarned",
];

export type PartidaDossierPlayer = Omit<ProfileMatchPlayer, CombatMetric>
  & NullableCombatMetrics;

export interface PartidaDossierTeam extends Omit<ProfileMatchTeam, "players"> {
  players: PartidaDossierPlayer[];
}

type PartidaDossierDetail = Omit<ProfileMatchDetail, "subteams"> & {
  subteams: PartidaDossierTeam[];
};

export interface PartidaDossier {
  detail: PartidaDossierDetail;
  teams: PartidaDossierTeam[];
  demo: boolean;
  telemetryAvailable: boolean;
}

export function isPartidaDemoEnabled(
  search: string,
  development = import.meta.env.DEV,
): boolean {
  return development && new URLSearchParams(search).get("demo") === "1";
}

export function hasCombatTelemetry(
  player: PartidaDossierPlayer,
): boolean {
  return COMBAT_METRICS.some((metric) => typeof player[metric] === "number");
}

export function playerKda(player: PartidaDossierPlayer): number | null {
  if (
    typeof player.kills !== "number" ||
    typeof player.deaths !== "number" ||
    typeof player.assists !== "number"
  ) {
    return null;
  }

  return (player.kills + player.assists) / Math.max(player.deaths, 1);
}

export function teamMetricTotal(
  team: PartidaDossierTeam,
  metric: TeamTotalMetric,
): number | null {
  let total = 0;

  for (const player of team.players) {
    const value = player[metric];
    if (typeof value !== "number") return null;
    total += value;
  }

  return total;
}

export function comparisonMaximum(
  teams: PartidaDossierTeam[],
  metric: ComparisonMetric,
): number | null {
  let maximum: number | null = null;

  for (const team of teams) {
    for (const player of team.players) {
      const value = player[metric];
      if (typeof value !== "number") continue;
      maximum = maximum === null ? value : Math.max(maximum, value);
    }
  }

  return maximum;
}

export function createPartidaDossier(
  detail: MatchDetail,
  fixture?: ProfileMatchFixture,
): PartidaDossier {
  const firstRiotId = detail.subteams.flatMap((team) => team.players)[0]?.riotId ?? "";
  const adapted = fixture
    ? enrichProfileMatchDetail(detail, fixture, firstRiotId)
    : adaptProfileMatchDetail(detail);
  const teams = [...adapted.subteams].sort(
    (left, right) => left.placement - right.placement,
  );

  return {
    detail: { ...adapted, subteams: teams },
    teams,
    demo: Boolean(fixture),
    telemetryAvailable: teams.some((team) =>
      team.players.some(hasCombatTelemetry),
    ),
  };
}

export async function loadPartidaDossier(
  matchId: string,
  demo: boolean,
): Promise<PartidaDossier> {
  const detail = await api.match(matchId);
  const fixture = demo ? await loadProfileMatchFixture() : undefined;

  return createPartidaDossier(detail, fixture);
}
