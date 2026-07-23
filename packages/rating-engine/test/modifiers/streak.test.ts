import { describe, expect, it } from 'vitest';
import fc from 'fast-check';
import { streakMultiplier, nextStreak } from '../../src/modifiers/streak.js';
import { DEFAULT_PARAMS } from '../../src/params.js';
import type { RatingParams } from '../../src/types.js';

const P = DEFAULT_PARAMS;
// threshold = 3, winCeil = 1.35, lossFloor = 0.25
const T = P.streakThreshold; // 3
const CEIL = P.streakWinCeil; // 1.35
const FLOOR = P.streakLossFloor; // 0.25

describe('streakMultiplier — gain side (deltaMuSign > 0, currentStreak > 0)', () => {
  it('streak 1 win → 1 + (1/3)*(0.35)', () => {
    expect(streakMultiplier(1, 1, P)).toBeCloseTo(1 + (1 / T) * (CEIL - 1), 12);
  });

  it('streak 2 wins → 1 + (2/3)*(0.35)', () => {
    expect(streakMultiplier(2, 1, P)).toBeCloseTo(1 + (2 / T) * (CEIL - 1), 12);
  });

  it('streak 3 wins (== threshold) → saturates at winCeil 1.35', () => {
    expect(streakMultiplier(3, 1, P)).toBeCloseTo(CEIL, 12);
  });

  it('streak > threshold stays saturated at ceil 1.35 (min cap on streak)', () => {
    expect(streakMultiplier(4, 1, P)).toBeCloseTo(CEIL, 12);
    expect(streakMultiplier(50, 1, P)).toBeCloseTo(CEIL, 12);
    expect(streakMultiplier(10_000, 1, P)).toBeCloseTo(CEIL, 12);
  });

  it('exactly reaches ceil at threshold and never exceeds it', () => {
    for (let cs = T; cs <= T + 20; cs++) {
      expect(streakMultiplier(cs, 1, P)).toBeLessThanOrEqual(CEIL + 1e-12);
      expect(streakMultiplier(cs, 1, P)).toBeCloseTo(CEIL, 12);
    }
  });
});

describe('streakMultiplier — loss side (deltaMuSign < 0, currentStreak < 0)', () => {
  it('streak -1 loss → 1 - (1/3)*(1-0.25)', () => {
    expect(streakMultiplier(-1, -1, P)).toBeCloseTo(1 - (1 / T) * (1 - FLOOR), 12);
  });

  it('streak -2 losses → 1 - (2/3)*(1-0.25)', () => {
    expect(streakMultiplier(-2, -1, P)).toBeCloseTo(1 - (2 / T) * (1 - FLOOR), 12);
  });

  it('streak -3 losses (== threshold) → saturates at lossFloor 0.25', () => {
    expect(streakMultiplier(-3, -1, P)).toBeCloseTo(FLOOR, 12);
  });

  it('streak more negative than -threshold stays saturated at floor 0.25', () => {
    expect(streakMultiplier(-4, -1, P)).toBeCloseTo(FLOOR, 12);
    expect(streakMultiplier(-50, -1, P)).toBeCloseTo(FLOOR, 12);
    expect(streakMultiplier(-10_000, -1, P)).toBeCloseTo(FLOOR, 12);
  });

  it('uses |currentStreak| magnitude (abs) on the loss side', () => {
    for (let cs = -T; cs >= -(T + 20); cs--) {
      expect(streakMultiplier(cs, -1, P)).toBeGreaterThanOrEqual(FLOOR - 1e-12);
      expect(streakMultiplier(cs, -1, P)).toBeCloseTo(FLOOR, 12);
    }
  });
});

describe('streakMultiplier — neutral / mismatched sign → 1.0', () => {
  it('zero streak → 1.0 regardless of sign', () => {
    expect(streakMultiplier(0, 1, P)).toBe(1.0);
    expect(streakMultiplier(0, -1, P)).toBe(1.0);
    expect(streakMultiplier(0, 0, P)).toBe(1.0);
  });

  it('gain while NOT on a win streak (cs <= 0) → 1.0 (no boost on flip)', () => {
    expect(streakMultiplier(-3, 1, P)).toBe(1.0); // losing streak, but won
    expect(streakMultiplier(-1, 1, P)).toBe(1.0);
    expect(streakMultiplier(0, 1, P)).toBe(1.0);
  });

  it('loss while NOT on a losing streak (cs >= 0) → 1.0 (no penalty on flip)', () => {
    expect(streakMultiplier(3, -1, P)).toBe(1.0); // winning streak, but lost
    expect(streakMultiplier(1, -1, P)).toBe(1.0);
    expect(streakMultiplier(0, -1, P)).toBe(1.0);
  });

  it('deltaMuSign == 0 (no movement) → always 1.0', () => {
    expect(streakMultiplier(5, 0, P)).toBe(1.0);
    expect(streakMultiplier(-5, 0, P)).toBe(1.0);
  });

  it('positive streak with positive sign but treats only sign>0 as gain', () => {
    // sanity: a large positive sign value is still "gain"
    expect(streakMultiplier(1, 12.7, P)).toBeCloseTo(1 + (1 / T) * (CEIL - 1), 12);
    // a large negative sign value is still "loss"
    expect(streakMultiplier(-1, -12.7, P)).toBeCloseTo(1 - (1 / T) * (1 - FLOOR), 12);
  });
});

describe('streakMultiplier — respects tunable params (not hard-coded)', () => {
  it('honours a custom threshold', () => {
    const custom: RatingParams = { ...P, streakThreshold: 5 };
    expect(streakMultiplier(5, 1, custom)).toBeCloseTo(CEIL, 12);
    expect(streakMultiplier(4, 1, custom)).toBeCloseTo(1 + (4 / 5) * (CEIL - 1), 12);
  });

  it('honours a custom winCeil / lossFloor', () => {
    const custom: RatingParams = { ...P, streakWinCeil: 1.5, streakLossFloor: 0.1 };
    expect(streakMultiplier(3, 1, custom)).toBeCloseTo(1.5, 12);
    expect(streakMultiplier(-3, -1, custom)).toBeCloseTo(0.1, 12);
  });
});

describe('streakMultiplier — property: ALWAYS within [lossFloor, winCeil]', () => {
  it('I6: result ∈ [0.25, 1.35] for any streak/sign with DEFAULT_PARAMS', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: -10_000, max: 10_000 }),
        fc.integer({ min: -5, max: 5 }),
        (cs, sign) => {
          const m = streakMultiplier(cs, sign, P);
          return (
            Number.isFinite(m) && m >= FLOOR - 1e-12 && m <= CEIL + 1e-12
          );
        },
      ),
    );
  });

  it('property holds for randomized (but valid) params too', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: -10_000, max: 10_000 }),
        fc.integer({ min: -5, max: 5 }),
        fc.double({ min: 1.0, max: 3.0, noNaN: true }), // winCeil >= 1
        fc.double({ min: 0.0, max: 1.0, noNaN: true }), // lossFloor <= 1
        fc.integer({ min: 1, max: 20 }), // threshold > 0
        (cs, sign, winCeil, lossFloor, threshold) => {
          const params: RatingParams = {
            ...P,
            streakWinCeil: winCeil,
            streakLossFloor: lossFloor,
            streakThreshold: threshold,
          };
          const m = streakMultiplier(cs, sign, params);
          return (
            Number.isFinite(m) &&
            m >= lossFloor - 1e-9 &&
            m <= winCeil + 1e-9
          );
        },
      ),
    );
  });
});

describe('nextStreak — win transitions', () => {
  it('win extends a positive streak: cs >= 0 ? cs + 1', () => {
    expect(nextStreak(0, true)).toBe(1);
    expect(nextStreak(1, true)).toBe(2);
    expect(nextStreak(7, true)).toBe(8);
  });

  it('win resets a losing streak to +1 (flip)', () => {
    expect(nextStreak(-1, true)).toBe(1);
    expect(nextStreak(-5, true)).toBe(1);
  });
});

describe('nextStreak — loss transitions', () => {
  it('loss extends a non-positive streak: cs <= 0 ? cs - 1', () => {
    expect(nextStreak(0, false)).toBe(-1);
    expect(nextStreak(-1, false)).toBe(-2);
    expect(nextStreak(-7, false)).toBe(-8);
  });

  it('loss resets a winning streak to -1 (flip)', () => {
    expect(nextStreak(1, false)).toBe(-1);
    expect(nextStreak(5, false)).toBe(-1);
  });
});

describe('nextStreak — property: magnitude never grows past +/-1 per step & sign matches outcome', () => {
  it('win → result >= 1; loss → result <= -1; |Δmagnitude| <= 1 except on flip', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: -1000, max: 1000 }),
        fc.boolean(),
        (cs, isWin) => {
          const n = nextStreak(cs, isWin);
          if (isWin) {
            return Number.isInteger(n) && n >= 1;
          }
          return Number.isInteger(n) && n <= -1;
        },
      ),
    );
  });
});
