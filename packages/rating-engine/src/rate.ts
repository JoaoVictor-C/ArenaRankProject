import type {
  AppliedModifiers,
  MatchInput,
  PlayerRatingResult,
  RatingParams,
  RatingResult,
  TeamInput,
} from './types.js';

import { ratePlackettLuce } from './model/plackett-luce.js';
import { placementWeight } from './modifiers/placement-weight.js';
import { placementAmp } from './modifiers/placement-amp.js';
import { streakMultiplier, nextStreak } from './modifiers/streak.js';
import { softCapFactor } from './modifiers/soft-cap.js';
import { dispersionCap } from './modifiers/dispersion-cap.js';
import { boostingPenalty } from './modifiers/boosting-penalty.js';
import { toCR } from './cr.js';
import { validateParams } from './params.js';

/**
 * Modifier breakdown for a frozen (ineligible or voided) player: every gamified
 * multiplier collapses to its neutral element and the deltas are exactly zero
 * (spec §9 / D3 / I3). Reported verbatim for transparency.
 */
const ZEROED_MODIFIERS: AppliedModifiers = {
  plBaseDeltaMu: 0,
  placementWeight: 1,
  placementAmp: 1,
  streakMult: 1,
  softCapFactor: 1,
  boostingFactor: 1,
  dispersionClamped: false,
  finalDeltaMu: 0,
};

/**
 * Deterministic team ordering (spec §8). Sort teams by (placement, teamId), and
 * players within a team by playerId, so every downstream summation runs in a
 * fixed f64 op order and `rate()` is invariant to input permutation (I2).
 *
 * Returns a fresh array; the input match is never mutated.
 */
function sortTeamsDeterministically(teams: TeamInput[]): TeamInput[] {
  return [...teams]
    .sort((a, b) =>
      a.placement !== b.placement ? a.placement - b.placement : a.teamId - b.teamId,
    )
    .map((t) => ({
      ...t,
      // playerIds are unique within a match, so a two-way comparator is a total,
      // stable order (no equal-key branch needed). Result-array order is thus
      // canonical and permutation-invariant.
      participants: [...t.participants].sort((p, q) => (p.playerId < q.playerId ? -1 : 1)),
    }));
}

/**
 * Reject a non-finite structural input (spec §9 — "NaN/Infinity inputs (reject)").
 *
 * A single NaN/±Infinity anywhere flows through the shared PL normalizer
 * (`c`, `exp(muTeam/c)`) and poisons EVERY eligible player's output, so I9
 * ("no NaN/Infinity output") only holds if such input is caught at the door.
 * `where` names the offending field (and playerId) for a debuggable message.
 */
function assertFinite(value: number, where: string): void {
  if (!Number.isFinite(value)) {
    throw new Error(`rate: ${where} must be finite, got ${value}`);
  }
}

/**
 * Validate the caller-supplied params object at the SAME door that guards every
 * participant scalar (spec §9, §12). `params` is untrusted: per §12 it is
 * season-tunable and loaded from JSONB, so a structurally-valid match can still
 * carry a corrupt params object. Two failure modes this catches:
 *
 *   - A non-finite scalar (e.g. `maxDeltaMu = NaN`) silently disables a guard:
 *     dispersionCap's `Math.abs(d) > NaN` is always false, so the I7 cap is
 *     disabled and |Δμ_final| becomes unbounded.
 *   - A non-finite entry in a `placementWeights` curve flows through
 *     `placementWeight()` and poisons EVERY eligible player's Δμ/μ/CR with NaN,
 *     breaking I9 ("no NaN/Infinity output").
 *
 * Every numeric param is asserted finite (mirroring the participant check),
 * every weight-curve entry is swept, and the structural spec-§7 guards are
 * delegated to {@link validateParams} (kappa range, non-positive σ0/β, etc.).
 */
function assertParamsValid(params: RatingParams): void {
  // Every numeric scalar in RatingParams. Listed explicitly (not via
  // Object.values) so a non-finite value names the offending field, exactly
  // like the per-participant assertFinite messages.
  const scalars: [number, string][] = [
    [params.mu0, 'params.mu0'],
    [params.sigma0, 'params.sigma0'],
    [params.beta, 'params.beta'],
    [params.tau, 'params.tau'],
    [params.kappa, 'params.kappa'],
    [params.scaleFactor, 'params.scaleFactor'],
    [params.baseOffset, 'params.baseOffset'],
    [params.placementAmp, 'params.placementAmp'],
    [params.placementMatchCount, 'params.placementMatchCount'],
    [params.streakLossFloor, 'params.streakLossFloor'],
    [params.streakWinCeil, 'params.streakWinCeil'],
    [params.streakThreshold, 'params.streakThreshold'],
    [params.softCapThreshold, 'params.softCapThreshold'],
    [params.softCapScale, 'params.softCapScale'],
    [params.maxDeltaMu, 'params.maxDeltaMu'],
    [params.resetAnchor, 'params.resetAnchor'],
    [params.resetFactor, 'params.resetFactor'],
    [params.sigmaResetMult, 'params.sigmaResetMult'],
    [params.sigmaResetCap, 'params.sigmaResetCap'],
  ];
  for (const [value, where] of scalars) {
    assertFinite(value, where);
  }

  // Sweep every entry of every placement-weight curve: a single NaN/±Infinity
  // anywhere multiplies into an eligible player's Δμ via placementWeight().
  const curves: [string, number[]][] = Object.entries(params.placementWeights);
  for (const [teamCount, curve] of curves) {
    for (let i = 0; i < curve.length; i += 1) {
      assertFinite(curve[i], `params.placementWeights[${teamCount}][${i}]`);
    }
  }

  // Structural spec-§7 guards (kappa range, non-positive σ0/β, weight-curve
  // presence, streak bounds). Finite-but-invalid params surface here.
  validateParams(params);
}

/**
 * rate — public entry point (spec §5, §8, §9). Runs the deterministic Weng-Lin
 * Plackett-Luce base update plus the CRS modifier pipeline over a match.
 *
 * Pipeline (per spec §5):
 *   1. Sort teams/players deterministically (§8) — invariance to permutation (I2).
 *   2. Run {@link ratePlackettLuce} over ALL teams. Ineligible players stay in the
 *      team aggregate so eligible opponents still update correctly (D3/I3).
 *   3. For each ELIGIBLE player apply the multiplicative modifier chain in EXACT
 *      order — placementWeight × placementAmp × streakMultiplier × softCapFactor ×
 *      boostingPenalty — then the dispersion cap LAST (§5.6 / I7).
 *   4. μ_after = μ_before + finalΔμ. σ_after starts as min(PL σ, σ_before) — rate()
 *      forbids the τ-dynamics step from inflating σ (openskill `preventSigmaIncrease`
 *      at the boundary; the base PL port stays faithful for I10). For CLEAN accounts
 *      (boostingPenaltyFactor f = 0) that is the final σ — D1 σ-sacrosanct holds
 *      verbatim. For FLAGGED accounts (f > 0) the DEC-A boosting freeze (§5.5) blends
 *      the shrink back toward σ_before by (1 − f): the M4 σ-laundering countermeasure.
 *      σ never increases under either path, so amended I1 (σ_after ≤ sqrt(σ²+τ²)) holds.
 *      CR_after = toCR(μ_after, σ_after). crDelta = after − before.
 *   5. Ineligible players freeze: Δμ=0, σ unchanged, crDelta=0, modifiers zeroed (D3/I3).
 *      All-ineligible ⇒ voided=true, every player frozen (D3/I4).
 *
 * Pure & deterministic: no Date.now / Math.random / I/O. The input is never mutated.
 */
export function rate(match: MatchInput): RatingResult {
  const { matchId, params } = match;
  const teamCount = match.teams.length;

  // §9 / §12 — validate the caller-supplied params at the door, BEFORE any
  // numeric work. params is untrusted (season-tunable, JSONB-loaded per §12):
  // a non-finite scalar silently disables a guard (e.g. maxDeltaMu=NaN voids
  // the I7 cap) and a NaN in a placementWeights curve poisons every eligible
  // player's output (breaking I9). This is the same finiteness door-check that
  // guards every participant scalar, applied to params.
  assertParamsValid(params);

  // §9 — a match needs at least two teams to rank against each other. An
  // unopposed (<2 team) "match" has no ranking signal, yet the PL τ-dynamics
  // step would still mutate σ and CR (σ ticks 200→200.03, crDelta ≠ 0) for a
  // lone participant. Reject it instead of silently mutating ratings.
  if (teamCount < 2) {
    throw new Error(`rate: a match requires at least 2 teams, got ${teamCount}`);
  }

  // §9 — an empty (zero-participant) team is a phantom: it still occupies a rank
  // slot and adds β² to the normalizer c, so a real opponent would "lose" to
  // nobody and get a finite-but-corrupt update. Reject it up front.
  //
  // §8 — playerIds must be unique across the WHOLE match: rate() back-associates
  // each PL base result by playerId (`baseById.get(...)`), so a duplicate would
  // silently clobber that map and let one participant inherit another's delta.
  // Validate both in a single pass before any numeric work.
  //
  // §9 — every structural numeric input must be FINITE. The check runs over ALL
  // participants (eligible AND frozen): a frozen player still feeds the PL
  // aggregate (D3/I3), so a non-finite μ there poisons opponents just as much.
  //
  // §9 — party-of-size > team-size. A party is the set of premade participants
  // (`isPremade === true`) sharing one `partyId`. A party is formed by queueing
  // together and MUST therefore be contained in a single team and be no larger
  // than that team's roster. We accumulate, per partyId, the total member count
  // and the distinct teams its members appear on, then reject any party that
  // either spans more than one team or out-sizes the team it sits on — both of
  // which are exactly the "party of size > team size" corruption (§9). Until
  // this guard `partyId`/`isPremade` were declared but never read.
  const seenPlayerIds = new Set<string>();
  const parties = new Map<string, { size: number; teamIds: Set<number>; teamSize: number }>();
  for (const team of match.teams) {
    if (team.participants.length === 0) {
      throw new Error(`rate: empty team ${team.teamId} (zero participants)`);
    }
    assertFinite(team.placement, `team ${team.teamId} placement`);
    assertFinite(team.teamId, `teamId`);
    for (const participant of team.participants) {
      if (seenPlayerIds.has(participant.playerId)) {
        throw new Error(`rate: duplicate playerId "${participant.playerId}"`);
      }
      seenPlayerIds.add(participant.playerId);

      // Party bookkeeping: a participant belongs to a party only when it is a
      // premade WITH a partyId. Solo players (no partyId) are never grouped, so
      // an undefined partyId can never form a phantom cross-team "party".
      if (participant.isPremade && participant.partyId !== undefined) {
        const entry = parties.get(participant.partyId);
        if (entry === undefined) {
          parties.set(participant.partyId, {
            size: 1,
            teamIds: new Set([team.teamId]),
            teamSize: team.participants.length,
          });
        } else {
          entry.size += 1;
          entry.teamIds.add(team.teamId);
          // The party's "home" team is the smallest team any member sits on;
          // a party larger than the smallest team it touches cannot fit.
          entry.teamSize = Math.min(entry.teamSize, team.participants.length);
        }
      }

      const id = participant.playerId;
      const { state } = participant;
      assertFinite(participant.championId, `player "${id}" championId`);
      assertFinite(participant.boostingPenaltyFactor, `player "${id}" boostingPenaltyFactor`);
      assertFinite(state.mu, `player "${id}" mu`);
      assertFinite(state.sigma, `player "${id}" sigma`);
      assertFinite(state.cr, `player "${id}" cr`);
      assertFinite(state.currentStreak, `player "${id}" currentStreak`);
      assertFinite(state.matchesPlayed, `player "${id}" matchesPlayed`);
      assertFinite(state.placementMatchesRemaining, `player "${id}" placementMatchesRemaining`);
      assertFinite(state.peakCr, `player "${id}" peakCr`);
    }
  }

  // §9 — reject any party that does not fit a single team. A party spanning >1
  // team, or whose member count exceeds the team it sits on, is "party of size
  // > team size": structurally impossible for a real lobby and would let a
  // premade group corrupt the per-team aggregate.
  for (const [partyId, entry] of parties) {
    if (entry.teamIds.size > 1 || entry.size > entry.teamSize) {
      throw new Error(
        `rate: party "${partyId}" of size ${entry.size} exceeds its team size ${entry.teamSize}`,
      );
    }
  }

  // §8 — deterministic ordering before any numeric work.
  const teams = sortTeamsDeterministically(match.teams);

  // I4 — void when EVERY participant is ineligible. Computed over all teams.
  const anyEligible = teams.some((t) =>
    t.participants.some((p) => p.eligibleForProgression),
  );
  const voided = !anyEligible;

  // §4 — Plackett-Luce base update over ALL teams (ineligible players included
  // in their team aggregate, D3/I3). Indexed by playerId for back-association.
  const base = ratePlackettLuce(teams, params);
  const baseById = new Map(base.map((b) => [b.playerId, b]));

  const players: PlayerRatingResult[] = [];

  for (const team of teams) {
    // isWin: top-half finish (spec §5.3). floor(teamCount / 2).
    const isWin = team.placement <= Math.floor(teamCount / 2);

    for (const participant of team.participants) {
      const { state } = participant;
      const muBefore = state.mu;
      const sigmaBefore = state.sigma;
      const crBefore = state.cr;

      // ratePlackettLuce returns exactly one entry per participant (same players,
      // same ids), so the lookup is total — see oracle.test.ts parity. The
      // non-null assertion is the invariant; no unreachable fallback branch.
      const pl = baseById.get(participant.playerId)!;
      const plBaseDeltaMu = pl.deltaMu;
      const sigmaAfterPl = pl.sigmaAfter;

      // --- FROZEN: ineligible player or voided match (D3/I3/I4). --------------
      if (voided || !participant.eligibleForProgression) {
        players.push({
          playerId: participant.playerId,
          muBefore,
          muAfter: muBefore, // Δμ = 0
          sigmaBefore,
          sigmaAfter: sigmaBefore, // σ unchanged (D1)
          crBefore,
          crAfter: crBefore,
          crDelta: 0,
          eligible: participant.eligibleForProgression,
          isWin,
          // Streak still advances for an eligible player in a voided match? No:
          // void = nobody moves. We freeze the streak too (no progression).
          newStreak: state.currentStreak,
          modifiers: { ...ZEROED_MODIFIERS },
        });
        continue;
      }

      // --- ELIGIBLE: full modifier pipeline (spec §5), EXACT order. ----------
      const wPlacement = placementWeight(team.placement, teamCount, params);
      const wAmp = placementAmp(state, params);

      // Running Δμ after the two positive scalars; its sign drives the streak
      // multiplier (sign(Δμ) per §5). placementWeight/placementAmp are > 0, so
      // the sign here equals sign(plBaseDeltaMu).
      let delta = plBaseDeltaMu * wPlacement * wAmp;
      const wStreak = streakMultiplier(state.currentStreak, Math.sign(delta), params);
      delta *= wStreak;

      // Soft-cap and boosting penalty attenuate the POSITIVE side only (D2): the
      // modifier fns gate on deltaMu > 0 internally, so a loss passes 1.0.
      const wSoftCap = softCapFactor(crBefore, delta, params);
      delta *= wSoftCap;

      const wBoosting = boostingPenalty(delta, participant.boostingPenaltyFactor);
      delta *= wBoosting;

      // §5.6 — dispersion cap LAST (structural guarantor of I7). Trinity C1:
      // the cap is σ-SCALED, so it must see the player's PRE-UPDATE σ. A
      // high-σ (newcomer/provisional) player legitimately needs larger steps;
      // passing sigmaBefore widens `effectiveCap = maxDeltaMu·max(1, σ/ref)` so
      // the PL signal — not a σ-blind flat cap — drives the placement climb.
      const capped = dispersionCap(delta, params, sigmaBefore);
      const finalDeltaMu = capped.value;

      const muAfter = muBefore + finalDeltaMu;

      // σ pipeline (spec §4 PL result → DEC-A flagged-only freeze §5.5).
      //
      // First clamp the raw PL σ to σ_before: the τ²-dynamics step (§4.1) first
      // INFLATES variance and only then shrinks it, so for a low-information
      // player (tiny variance share — e.g. a low-σ member of a high-σ team, or a
      // large tie-group) the post-dynamics `sigmaAfterPl` can exceed σ_before
      // (verified: σ=6 on a team with σ=400 → 6.946). This is openskill's
      // documented `preventSigmaIncrease` (LIMIT_SIGMA) semantics, applied at
      // rate()'s boundary; the base port stays faithful to openskill's default
      // (limitSigma off) so I10 oracle parity is untouched. The result is the
      // honest §4 PL shrink, never an increase.
      const sigmaPlClamped = Math.min(sigmaAfterPl, sigmaBefore);

      // DEC-A (Trinity M4 σ-laundering countermeasure, §5.5): for FLAGGED
      // accounts only (f = clamp(boostingPenaltyFactor, 0, 1) > 0) freeze the
      // σ-shrink proportional to f, blending the PL result back toward σ_before:
      //
      //   σ_after = σ_before − (1 − f)·(σ_before − σ_afterPL)
      //
      //   f = 0 (clean): σ_after = σ_afterPL — D1 σ-sacrosanct fully preserved,
      //                  the engine never touches a clean player's σ.
      //   f = 1 (max-flagged booster): σ_after = σ_before — σ fully frozen,
      //                  denying the CR uplift that σ-shrink would otherwise grant.
      //
      // The blend lies in [σ_afterPL, σ_before] with σ_afterPL ≤ σ_before, so σ
      // never INCREASES under this rule and the amended I1 bound still holds.
      const f =
        participant.boostingPenaltyFactor < 0
          ? 0
          : participant.boostingPenaltyFactor > 1
            ? 1
            : participant.boostingPenaltyFactor;
      const sigmaAfter =
        f > 0
          ? sigmaBefore - (1 - f) * (sigmaBefore - sigmaPlClamped)
          : sigmaPlClamped;

      const crAfter = toCR(muAfter, sigmaAfter, params);
      const crDelta = crAfter - crBefore;

      const modifiers: AppliedModifiers = {
        plBaseDeltaMu,
        placementWeight: wPlacement,
        placementAmp: wAmp,
        streakMult: wStreak,
        softCapFactor: wSoftCap,
        boostingFactor: wBoosting,
        dispersionClamped: capped.clamped,
        finalDeltaMu,
      };

      players.push({
        playerId: participant.playerId,
        muBefore,
        muAfter,
        sigmaBefore,
        sigmaAfter,
        crBefore,
        crAfter,
        crDelta,
        eligible: true,
        isWin,
        newStreak: nextStreak(state.currentStreak, isWin),
        modifiers,
      });
    }
  }

  return { matchId, voided, players };
}
