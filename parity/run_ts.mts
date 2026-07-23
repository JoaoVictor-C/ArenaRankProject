/**
 * Parity runner — TypeScript oracle engine (@crs/rating-engine).
 *
 * Reads the shared fixtures, runs each match through the TS `rate()` with the
 * neutralized shared params, and writes the per-player results as JSON to stdout
 * for `compare.mjs` to diff against the Python runtime. Run via tsx:
 *   npx tsx parity/run_ts.mts parity/fixtures.json
 */
import { readFileSync } from "node:fs";

// Imported straight from source; tsx resolves the `.js` specifiers to `.ts`.
import { rate } from "../packages/rating-engine/src/index.js";
import type {
  MatchInput,
  ParticipantInput,
  RatingParams,
  TeamInput,
} from "../packages/rating-engine/src/index.js";

interface FixturePlayer {
  id: string;
  mu: number;
  sigma: number;
  streak?: number;
  matchesPlayed?: number;
}

const fixtures = JSON.parse(readFileSync(process.argv[2], "utf-8"));
const p = fixtures.params;

const params: RatingParams = {
  ...p,
  // JSON object keys are strings; the engine keys placementWeights by team count.
  placementWeights: Object.fromEntries(
    Object.entries(p.placementWeights).map(([k, v]) => [Number(k), v as number[]]),
  ),
};

const toCR = (mu: number, sigma: number): number =>
  (mu - 3 * sigma) * p.scaleFactor + p.baseOffset;

const results: Array<Record<string, string | number>> = [];

for (const match of fixtures.matches) {
  const teams: TeamInput[] = match.teams.map((team: { placement: number; players: FixturePlayer[] }, teamIndex: number) => ({
    teamId: teamIndex,
    placement: team.placement,
    participants: team.players.map((pl): ParticipantInput => {
      const cr = toCR(pl.mu, pl.sigma);
      return {
        playerId: pl.id,
        championId: 1,
        eligibleForProgression: true,
        isPremade: false,
        boostingPenaltyFactor: 0,
        state: {
          playerId: pl.id,
          mu: pl.mu,
          sigma: pl.sigma,
          cr,
          currentStreak: pl.streak ?? 0,
          matchesPlayed: pl.matchesPlayed ?? 50, // non-provisional
          placementMatchesRemaining: 0, // -> placement amp off
          peakCr: cr,
        },
      };
    }),
  }));

  const result = rate({
    matchId: match.matchId,
    mode: match.mode,
    teams,
    params,
  } as MatchInput);

  for (const pr of result.players) {
    results.push({
      matchId: match.matchId,
      playerId: pr.playerId,
      crBefore: pr.crBefore,
      crAfter: pr.crAfter,
      crDelta: pr.crDelta,
      muAfter: pr.muAfter,
      sigmaAfter: pr.sigmaAfter,
    });
  }
}

process.stdout.write(JSON.stringify({ engine: "ts", results }));
