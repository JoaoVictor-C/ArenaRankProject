import type { RatingParams } from './types.js';

/**
 * DEFAULT_PARAMS — values from spec §7 table; placementWeights curves from §5.1.
 *
 * CR anchor sanity (scaleFactor=1, baseOffset=250):
 *   fresh 1000/350 → 200; post-placements 1000/150 → 800;
 *   established 1000/85 → ~1000; strong 1300/80 → 1310; elite 1800/70 → 1840.
 */
export const DEFAULT_PARAMS: RatingParams = {
  // mu0 / sigma0 — DB schema
  mu0: 1000,
  sigma0: 350,
  // beta / tau / kappa — TrueSkill ratio (σ0/2, σ0/100)
  beta: 175,
  tau: 3.5,
  kappa: 1e-4,
  // scaleFactor / baseOffset — D4
  scaleFactor: 1.0,
  baseOffset: 250,
  // placementWeights — §5.1 curves (D5): mild, symmetric, renormalized to mean 1.0
  placementWeights: {
    8: [1.0934, 1.0205, 0.9658, 0.9203, 0.9203, 0.9658, 1.0205, 1.0934], // Duos
    6: [1.0793, 0.9878, 0.9329, 0.9329, 0.9878, 1.0793], // Trios
  },
  // placementAmp / placementMatchCount — proposal §3.1
  placementAmp: 2.0,
  placementMatchCount: 10,
  // streakLossFloor / streakWinCeil / streakThreshold — §3.2
  streakLossFloor: 0.25,
  streakWinCeil: 1.35,
  streakThreshold: 3,
  // softCapThreshold / softCapScale — §3.1 (scale inferred)
  softCapThreshold: 5000,
  softCapScale: 1000,
  // maxDeltaMu — inferred; simulation-tuned
  maxDeltaMu: 150,
  // dispersionSigmaRef — §5/§7 contract; reference σ for dispersion cap
  dispersionSigmaRef: 85,
  // resetAnchor / resetFactor — §13.3
  resetAnchor: 1000,
  resetFactor: 0.5,
  // sigmaResetMult / sigmaResetCap — §13.3
  sigmaResetMult: 1.5,
  sigmaResetCap: 350,
};

/**
 * validateParams — zero-dependency, hand-rolled guards (D6: no zod).
 *
 * Throws an Error on the violations enumerated in spec §7:
 *   - non-positive σ0/β;
 *   - kappa ∉ (0, 1);
 *   - factors out of [0, 1] where bounded;
 *   - missing default-mode weight arrays;
 *   - streakLossFloor > 1 or streakWinCeil < 1;
 *   - any non-finite (NaN/±Infinity) numeric param, or non-finite
 *     placementWeights entry;
 *   - dispersionSigmaRef <= 0.
 */
export function validateParams(p: RatingParams): void {
  // Finiteness: every scalar numeric param must be a finite number.
  const numericParams: Array<[string, number]> = [
    ['mu0', p.mu0],
    ['sigma0', p.sigma0],
    ['beta', p.beta],
    ['tau', p.tau],
    ['kappa', p.kappa],
    ['scaleFactor', p.scaleFactor],
    ['baseOffset', p.baseOffset],
    ['placementAmp', p.placementAmp],
    ['placementMatchCount', p.placementMatchCount],
    ['streakLossFloor', p.streakLossFloor],
    ['streakWinCeil', p.streakWinCeil],
    ['streakThreshold', p.streakThreshold],
    ['softCapThreshold', p.softCapThreshold],
    ['softCapScale', p.softCapScale],
    ['maxDeltaMu', p.maxDeltaMu],
    ['dispersionSigmaRef', p.dispersionSigmaRef],
    ['resetAnchor', p.resetAnchor],
    ['resetFactor', p.resetFactor],
    ['sigmaResetMult', p.sigmaResetMult],
    ['sigmaResetCap', p.sigmaResetCap],
  ];
  for (const [name, value] of numericParams) {
    if (!Number.isFinite(value)) {
      throw new Error(`validateParams: ${name} must be a finite number`);
    }
  }
  // Finiteness: every entry of every placementWeights array must be finite.
  for (const [key, weights] of Object.entries(p.placementWeights)) {
    if (!Array.isArray(weights)) {
      continue;
    }
    for (let i = 0; i < weights.length; i++) {
      if (!Number.isFinite(weights[i])) {
        throw new Error(
          `validateParams: placementWeights[${key}][${i}] must be a finite number`,
        );
      }
    }
  }

  if (!(p.sigma0 > 0)) {
    throw new Error('validateParams: sigma0 must be > 0');
  }
  if (!(p.beta > 0)) {
    throw new Error('validateParams: beta must be > 0');
  }
  if (!(p.kappa > 0 && p.kappa < 1)) {
    throw new Error('validateParams: kappa must be in (0, 1)');
  }
  if (!(p.resetFactor >= 0 && p.resetFactor <= 1)) {
    throw new Error('validateParams: resetFactor must be in [0, 1]');
  }
  if (p.streakLossFloor > 1) {
    throw new Error('validateParams: streakLossFloor must be <= 1');
  }
  if (p.streakWinCeil < 1) {
    throw new Error('validateParams: streakWinCeil must be >= 1');
  }
  if (!(p.dispersionSigmaRef > 0)) {
    throw new Error('validateParams: dispersionSigmaRef must be > 0');
  }
  if (!Array.isArray(p.placementWeights[8])) {
    throw new Error('validateParams: missing placementWeights for 8 teams (DUOS)');
  }
  if (!Array.isArray(p.placementWeights[6])) {
    throw new Error('validateParams: missing placementWeights for 6 teams (TRIOS)');
  }
}
