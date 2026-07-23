import type { RatingParams } from '../types.js';

/**
 * streakMultiplier — spec §5.3. Result in [lossFloor, winCeil] = [0.25, 1.35] (I6).
 *
 * Gain (`deltaMuSign > 0`) while on a win streak (`currentStreak > 0`):
 *   1 + (min(currentStreak, threshold) / threshold) · (winCeil − 1)   → capped at winCeil.
 * Loss (`deltaMuSign < 0`) while on a losing streak (`currentStreak < 0`):
 *   1 − (min(|currentStreak|, threshold) / threshold) · (1 − lossFloor) → floored at lossFloor.
 * Otherwise (no streak in the direction of movement, or no movement): 1.0.
 *
 * Pure & deterministic: no Date.now / no Math.random. The interpolation already
 * saturates exactly at the bound when |currentStreak| ≥ threshold, so the multiplier
 * is intrinsically within [lossFloor, winCeil] for any sane params (I6).
 */
export function streakMultiplier(
  currentStreak: number,
  deltaMuSign: number,
  params: RatingParams,
): number {
  const { streakThreshold, streakWinCeil, streakLossFloor } = params;

  // Gain while riding a win streak: scale up toward winCeil.
  if (deltaMuSign > 0 && currentStreak > 0) {
    const ramp = Math.min(currentStreak, streakThreshold) / streakThreshold;
    return 1 + ramp * (streakWinCeil - 1);
  }

  // Loss while sinking on a losing streak: scale down toward lossFloor.
  if (deltaMuSign < 0 && currentStreak < 0) {
    const ramp = Math.min(Math.abs(currentStreak), streakThreshold) / streakThreshold;
    return 1 - ramp * (1 - streakLossFloor);
  }

  // No streak aligned with the movement direction (incl. flips, zero streak,
  // zero movement) → no streak effect.
  return 1.0;
}

/**
 * nextStreak — spec §5.3. Advance the streak counter after a match.
 *   win  → cs ≥ 0 ? cs + 1 : 1   (extend a win streak, or reset a loss streak to +1)
 *   loss → cs ≤ 0 ? cs − 1 : −1  (extend a loss streak, or reset a win streak to −1)
 */
export function nextStreak(currentStreak: number, isWin: boolean): number {
  if (isWin) {
    return currentStreak >= 0 ? currentStreak + 1 : 1;
  }
  return currentStreak <= 0 ? currentStreak - 1 : -1;
}
