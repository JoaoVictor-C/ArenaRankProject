import type { RatingParams } from './types.js';

/**
 * toCR — conservative public rating, purely derived (D1, spec §5/§7):
 *   CR = (μ − 3σ) · scaleFactor + baseOffset.
 *
 * Pure and deterministic (no Date.now / Math.random). Strictly increasing in
 * μ and strictly decreasing in σ (I8): with scaleFactor > 0, ∂CR/∂μ = +scale
 * and ∂CR/∂σ = −3·scale, both nonzero. Anchors (scaleFactor=1, baseOffset=250):
 *   1000/350 → 200, 1000/85 → 995 (~1000), 1300/80 → 1310, 1800/70 → 1840.
 */
export function toCR(mu: number, sigma: number, params: RatingParams): number {
  return (mu - 3 * sigma) * params.scaleFactor + params.baseOffset;
}
