import { api } from "../lib/api";
import { isDevMockOn } from "../lib/devMock";
import type {
  AugmentEntry,
  AugmentRarity,
  CombatStats,
  LoadoutEntry,
  MatchDetail,
  MatchPlayer,
  PlayerMatchRich,
  SubTeam,
} from "../lib/types";

/* O combate e o loadout deixaram de ser exclusivos do fixture: o backend passou
   a ingeri-los por participante e a servi-los hidratados em `/match/{id}`.
   Estes aliases existem só para não quebrar os imports da tela — a definição
   canônica é a de `lib/types`, compartilhada com o cliente da API. */
export type ProfileAugmentRarity = AugmentRarity;
export type ProfileLoadoutEntry = LoadoutEntry;
export type ProfileAugmentEntry = AugmentEntry;

/** `rankLabel` é o único campo que o backend NÃO serve: o rank do jogador na
 *  partida não vem no payload da Riot. A tela deriva dele do `crAfter`, que já
 *  é persistido — por isso ele vive aqui e não em `CombatStats`. */
export interface ProfileCombatStats extends CombatStats {
  rankLabel?: string;
}

export interface ProfileMatchPlayer extends MatchPlayer, ProfileCombatStats {
  items?: ProfileLoadoutEntry[];
  augments?: ProfileAugmentEntry[];
}

export interface ProfileMatchTeam extends Omit<SubTeam, "players"> {
  players: ProfileMatchPlayer[];
}

export interface ProfileMatchDetail extends Omit<MatchDetail, "subteams"> {
  subteams: ProfileMatchTeam[];
  mockedFields: Array<"items" | "augments" | "combat">;
}

export interface ProfileMatchSummary extends ProfileCombatStats {
  items?: ProfileLoadoutEntry[];
  augments?: ProfileAugmentEntry[];
  mocked: boolean;
}

interface FixtureLoadout {
  items: ProfileLoadoutEntry[];
  augments: ProfileAugmentEntry[];
}

interface FixturePlayer extends Required<ProfileCombatStats> {
  loadout: number;
}

export interface ProfileMatchFixture {
  label: string;
  loadouts: FixtureLoadout[];
  players: FixturePlayer[];
}

const FIXTURE_PATH = "/fixtures/profile-match-detail.json";
let fixtureCache: Promise<ProfileMatchFixture> | null = null;

export function loadProfileMatchFixture(): Promise<ProfileMatchFixture> {
  fixtureCache ??= fetch(FIXTURE_PATH).then((response) => {
    if (!response.ok) {
      throw new Error("Não foi possível carregar o detalhe mockado da partida.");
    }
    return response.json() as Promise<ProfileMatchFixture>;
  });
  return fixtureCache;
}

function hashMatchId(matchId: string): number {
  let hash = 0;
  for (const char of matchId) {
    hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  }
  return hash;
}

function fixturePlayerAt(
  fixture: ProfileMatchFixture,
  matchId: string,
  offset: number,
): FixturePlayer {
  const base = hashMatchId(matchId) % fixture.players.length;
  return fixture.players[(base + offset) % fixture.players.length];
}

function summaryFromTemplate(
  fixture: ProfileMatchFixture,
  matchId: string,
): ProfileMatchSummary {
  const player = fixturePlayerAt(fixture, matchId, 0);
  const loadout = fixture.loadouts[player.loadout % fixture.loadouts.length];
  return {
    level: player.level,
    rankLabel: player.rankLabel,
    kills: player.kills,
    deaths: player.deaths,
    assists: player.assists,
    killParticipation: player.killParticipation,
    damageToChampions: player.damageToChampions,
    damagePerMinute: player.damagePerMinute,
    goldEarned: player.goldEarned,
    items: loadout.items,
    augments: loadout.augments,
    mocked: true,
  };
}

export function adaptProfileMatchDetail(detail: MatchDetail): ProfileMatchDetail {
  return {
    ...detail,
    mockedFields: [],
    subteams: detail.subteams.map((team) => ({
      ...team,
      players: team.players.map((player) => ({ ...player })),
    })),
  };
}

export function enrichProfileMatchDetail(
  detail: MatchDetail,
  fixture: ProfileMatchFixture,
  profileRiotId: string,
): ProfileMatchDetail {
  let nextOpponentOffset = 1;

  return {
    ...detail,
    mockedFields: ["items", "augments", "combat"],
    subteams: detail.subteams.map((team) => ({
      ...team,
      players: team.players.map((player) => {
        const isProfile = player.riotId === profileRiotId;
        const template = fixturePlayerAt(
          fixture,
          detail.matchId,
          isProfile ? 0 : nextOpponentOffset++,
        );
        const loadout =
          fixture.loadouts[template.loadout % fixture.loadouts.length];

        return {
          ...player,
          level: template.level,
          rankLabel: template.rankLabel,
          kills: template.kills,
          deaths: template.deaths,
          assists: template.assists,
          killParticipation: template.killParticipation,
          damageToChampions: template.damageToChampions,
          damagePerMinute: template.damagePerMinute,
          goldEarned: template.goldEarned,
          items: loadout.items,
          augments: loadout.augments,
        };
      }),
    })),
  };
}

export async function loadProfileMatchDetail(
  matchId: string,
  profileRiotId: string,
): Promise<ProfileMatchDetail> {
  const detail = await api.match(matchId);
  if (!isDevMockOn()) return adaptProfileMatchDetail(detail);
  return enrichProfileMatchDetail(
    detail,
    await loadProfileMatchFixture(),
    profileRiotId,
  );
}

export async function loadProfileMatchSummary(
  match: PlayerMatchRich,
): Promise<ProfileMatchSummary | null> {
  if (!isDevMockOn()) return null;
  return summaryFromTemplate(await loadProfileMatchFixture(), match.matchId);
}
