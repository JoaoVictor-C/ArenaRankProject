# `@crs/rating-engine`

Deterministic, pure, zero-runtime-dependency rating math for the Casual Ranked
System (CRS). Slice 1 of the proposal: the Weng-Lin Plackett-Luce base update plus
the CRS modifier pipeline, the conservative CR display function, and the season
soft-reset. Stateless in, stateless out — the processor/DB/API slices wrap it.

Spec of record: [`docs/superpowers/specs/2026-06-14-rating-engine-design.md`](../../docs/superpowers/specs/2026-06-14-rating-engine-design.md).

---

## Install / build

Part of the monorepo workspace. No runtime third-party deps (D6). Dev deps only:
`typescript`, `tsx`, `vitest`, `@vitest/coverage-v8`, `fast-check`, `openskill`
(the last is a **test-only** oracle).

```bash
npm test      -w @crs/rating-engine     # full suite (vitest run)
npm run test:cov   -w @crs/rating-engine # + 100% coverage gate
npm run typecheck  -w @crs/rating-engine
```

---

## Usage

```ts
import { rate, toCR, softReset, DEFAULT_PARAMS } from '@crs/rating-engine';
import type { MatchInput } from '@crs/rating-engine';

const match: MatchInput = {
  matchId: 'NA1_123',
  mode: 'DUOS',
  params: DEFAULT_PARAMS,
  teams: [
    {
      teamId: 0,
      placement: 1, // 1 = best; ties allowed
      participants: [
        {
          playerId: 'p1',
          state: { playerId: 'p1', mu: 1000, sigma: 140, cr: 830,
                   currentStreak: 2, matchesPlayed: 40,
                   placementMatchesRemaining: 0, peakCr: 900 },
          championId: 42,
          eligibleForProgression: true, // integrity slice decides this
          isPremade: false,
          boostingPenaltyFactor: 0,     // 0..1 from integrity slice
        },
      ],
    },
    // ...more teams (generic over N teams × M players)
  ],
};

const result = rate(match);
// result.players[i] = { muBefore, muAfter, sigmaBefore, sigmaAfter,
//                       crBefore, crAfter, crDelta, eligible, isWin,
//                       newStreak, modifiers: { ...full breakdown } }
```

`rate()` never mutates its input and performs no I/O, `Date.now`, or `Math.random`.

---

## Formulas

### Conservative rating (CR) — derived, never accumulated (D1)

```
CR = (μ − 3σ)·scaleFactor + baseOffset
```

`toCR(mu, sigma, params)`. Strictly increasing in μ, strictly decreasing in σ (I8).
Anchors (scaleFactor=1, baseOffset=250): `1000/350 → 200`, `1000/85 → 995`,
`1300/80 → 1310`, `1800/70 → 1840`.

### Base update — Weng-Lin Plackett-Luce (`ratePlackettLuce`)

A faithful port of the `openskill` `PlackettLuce` model plus the additive
`rate({ tau })` dynamics, configured with our `{ beta, tau, kappa }`:

1. Dynamics: `σ²ᵢ ← σ²ᵢ + τ²` (prevents σ from freezing).
2. Team aggregate: `μ_team = Σ μᵢ`, `σ²_team = Σ σ²ᵢ`.
3. Normalizer: `c = √(Σ_teams (σ²_team + β²))`.
4. Plackett-Luce ranking terms `Ω_team`, `Δ_team` (Weng-Lin tie convention `÷ a`).
5. Variance-weighted back-distribution to players:
   - `Δμᵢ = (σ²ᵢ / σ²_team) · Ω_team`
   - `σ²ᵢ,after = σ²ᵢ · max(1 − (σ²ᵢ/σ²_team)·Δ_team, κ)`

Parity with `openskill.rate()` is asserted to `1e-9` over ≥15 fixtures (I10,
`oracle.test.ts`).

### Modifier pipeline (per eligible player) — spec §5

Multiplicative on the base `Δμ`, in this **exact** order, dispersion cap **last**:

```
Δμ = Δμ_base
   × placementWeight(placement, teamCount)   // §5.1 mild symmetric extremes-emphasis
   × placementAmp(state)                      // §5.2  2.0× while provisional
   × streakMultiplier(streak, sign(Δμ))       // §5.3  ∈ [0.25, 1.35]
   × softCapFactor(cr, Δμ)                     // §5.4  positive side only, (0,1]
   × boostingPenalty(Δμ, boostingPenaltyFactor)// §5.5  positive side only
Δμ_final = dispersionCap(Δμ)                   // §5.6  clamp to ±maxDeltaMu  (I7)

μ_after = μ_before + Δμ_final
σ_after = σ from the PL update    // modifiers NEVER touch σ (D1)
CR_after = toCR(μ_after, σ_after)
crDelta  = CR_after − CR_before
```

`isWin = placement ≤ floor(teamCount / 2)` (top half). `newStreak = nextStreak(streak, isWin)`:
win → `cs ≥ 0 ? cs+1 : 1`; loss → `cs ≤ 0 ? cs−1 : −1`.

### Season soft-reset (`softReset`) — the ONLY op that may raise σ

```
μ' = resetAnchor + (μ − resetAnchor)·resetFactor
σ' = min(σ·sigmaResetMult, sigmaResetCap)
```

Returns a fresh `PlayerState` (μ', σ', CR' derived, streak/matches reset,
`placementMatchesRemaining = placementMatchCount`, peak rebased).

---

## Parameters — `DEFAULT_PARAMS`

| Param | Default | Notes |
|---|---|---|
| `mu0` / `sigma0` | 1000 / 350 | DB schema |
| `beta` / `tau` / `kappa` | 175 / 3.5 / 1e-4 | TrueSkill ratios; κ = σ²-floor |
| `scaleFactor` / `baseOffset` | 1.0 / 250 | D4 (CR anchors) |
| `placementWeights[8]` | `[1.20,1.12,1.06,1.01,1.01,1.06,1.12,1.20]` | Duos, symmetric (D5) |
| `placementWeights[6]` | `[1.18,1.08,1.02,1.02,1.08,1.18]` | Trios |
| `placementAmp` / `placementMatchCount` | 2.0 / 10 | provisional amplification |
| `streakLossFloor` / `streakWinCeil` / `streakThreshold` | 0.25 / 1.35 / 3 | I6 bounds |
| `softCapThreshold` / `softCapScale` | 5000 / 1000 | positive-side attenuation |
| `maxDeltaMu` | 150 | dispersion cap (I7) |
| `resetAnchor` / `resetFactor` | 1000 / 0.5 | soft-reset μ regression |
| `sigmaResetMult` / `sigmaResetCap` | 1.5 / 350 | soft-reset σ re-inflation |

`validateParams(params)` (zero-dep, hand-rolled) throws on: non-positive σ0/β,
`kappa ∉ (0,1)`, `resetFactor ∉ [0,1]`, `streakLossFloor > 1`, `streakWinCeil < 1`,
or a missing default-mode (8/6) weight curve.

---

## Determinism guarantees (I2)

- No `Date.now`, `Math.random`, or I/O anywhere in `src/`.
- Before any summation, teams are sorted by `(placement, teamId)` and players by
  `playerId`, fixing f64 op order.
- `rate(x)` deep-equals `rate(x)`, and is **invariant to input permutation** of
  team order and intra-team player order (property-tested, `properties.test.ts`).
- The simulation suite uses a self-implemented seeded PRNG (mulberry32), never the
  global RNG, so it is fully reproducible.

---

## Invariants & a known boundary

Property-tested in `properties.test.ts` / `simulation.test.ts` (spec §3):

| | Statement | Status |
|---|---|---|
| I2 | determinism + permutation invariance | holds (property test) |
| I5 | better placement ⇒ ≥ base Δμ (ceteris paribus) | holds |
| I6 | `streakMult ∈ [0.25, 1.35]` | holds |
| I7 | `|Δμ_final| ≤ maxDeltaMu` | holds (cap is last) |
| I8 | `toCR` ↑ in μ, ↓ in σ | holds |
| I9 | no `NaN`/`Inf` for valid input | holds |
| I10 | base PL = `openskill` within 1e-9 | holds (oracle) |

**I1 — σ under `rate()` (τ-dynamics boundary, a real finding).** The spec's literal
I1 ("σ_after ≤ σ_before for every player") does **not** hold universally, because
the mandated dynamics step (§4.1) first inflates variance by τ² and only then
shrinks it. The PL multiplier `max(1 − share·Δ, κ) ≤ 1` guarantees the universal
bound

```
σ_after ≤ √(σ_before² + τ²)        ← always true; this is what we assert
```

i.e. PL never inflates **beyond** the τ step (modifiers never touch σ at all — D1;
frozen players keep σ exactly). For a low-information player (small variance share
of an informative comparison, or a large tie-group), the fixed τ re-inflation can
exceed the PL shrink and σ ticks **up** by ≤ a few ×10⁻². This is intrinsic to the
conservative PL family (it matches `openskill` exactly), a τ/κ/σ-floor tuning
boundary — not a bug. The intended *direction* (σ trends **down** as skill
resolves) is verified by the simulation suite: mean σ falls season over season.

**I11 — mean-CR drift (guardrail, not a hard fail).** The Weng-Lin PL update is
zero-sum in μ **only when σ is homogeneous** across the field. While fresh players
(σ=350) resolve at different rates, the variance-weighted back-distribution makes
total μ drift **upward**; CR climbs further because the conservative `μ − 3σ`
estimate catches up as σ shrinks. Isolating the modifiers (flat weights, no amp)
leaves most of this drift in place, so it is a property of the base model, not the
gamification layer. The simulation asserts the drift is **decelerating /
converging** (each season-quarter adds strictly less μ than the previous one) and
finite — i.e. **no runaway/exponential inflation** — rather than asserting an
artificially tight bound the dynamics do not meet.

> These two findings answer the spec §3 Trinity validation question directly:
> the modifiers do **not** create the inflation (the base PL dynamics do, via σ
> heterogeneity), and σ's "honest uncertainty" is preserved by the modifiers (D1)
> but is subject to a small τ-driven floor in low-information matches. Candidate
> corrections for a future slice: a smaller `tau`, a per-match σ-homogenization,
> or tracking an unmodified "true-skill" μ in parallel (spec §12).

---

## Eligibility & edge cases (D3/I3/I4)

- `eligibleForProgression = false` → player **frozen** (`Δμ = 0`, σ unchanged,
  `crDelta = 0`, `newStreak` unchanged, `modifiers` zeroed) **but still enters the
  PL aggregate** so eligible opponents update correctly.
- **All** participants ineligible → `RatingResult.voided = true`, everyone frozen.
- Ties (equal `placement`), uneven roster sizes, single eligible player, and the
  2-team minimum are all covered by the oracle / rate / property suites.

---

## Test layout

```
test/
  oracle.test.ts        I10 — base PL vs openskill (≥15 fixtures, 1e-9)
  cr.test.ts            toCR formula + I8 sweeps
  season.test.ts        softReset
  params.test.ts        validateParams guards
  modifiers/*.test.ts   each modifier in isolation, boundaries
  rate.test.ts          8×2 Arena snapshot + freeze/void/amp/streak/soft-cap/clamp
  properties.test.ts    I1 (bounded), I2, I5, I6, I7, I8, I9 (fast-check)
  simulation.test.ts    seeded Monte-Carlo: convergence, spread, I11 drift
```

Coverage gate: 100% lines/branches/functions/statements (`vitest.config.ts`).
