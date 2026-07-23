# CRS Rating Engine — Design Spec

> Slice 1 of the Casual Ranked System (CRS). Source of truth: `casual_ranked_proposal.md`.
> Status: **APPROVED (D1–D6)** by Clesio on 2026-06-14. Trinity math-model meta-validation (Track 4) **complete** (2026-06-14, `claw_max`, conf 0.90 — 6 findings C1/C2/M3/M4/M5/M6, decisions DEC-A/DEC-B; see "Trinity validation" section).
> Package: `@crs/rating-engine`. Pure, stateless, deterministic, zero runtime deps, 100% test coverage.

---

## 1. Scope & non-goals

**In scope (this slice):** the deterministic rating math as a standalone TypeScript package:
- Weng-Lin Plackett-Luce base update (multi-team free-for-all placement).
- CRS modifier pipeline (placement weight, placement-match amplification, streak, soft cap, boosting penalty, dispersion cap).
- Conservative CR display function and season soft-reset.
- Full type contracts that upstream/downstream slices fill.
- Exhaustive test suite (oracle, unit, property, snapshot, simulation).

**Out of scope (later slices):** Riot client, ingestion, processor, DB/Prisma, API, frontend, integrity RDS computation. The engine **consumes** integrity outputs (`boostingPenaltyFactor`, `eligibleForProgression`, `isPremade`, `partyId`) but never computes them.

---

## 2. Locked decisions (D1–D6)

| # | Decision |
|---|---|
| **D1** | **CR is derived, not accumulated.** `CR = (μ − 3σ)·scaleFactor + baseOffset`, always. The `cr`/`cr_*` DB columns are materializations/snapshots. Modifiers scale the **μ movement**; CR falls out by derivation. **σ is sacrosanct for clean accounts** — only pure Plackett-Luce changes it under `rate()`; only `softReset` increases it. *Carve-out (Trinity DEC-A):* for accounts **already flagged** upstream (`boostingPenaltyFactor f > 0`) the boosting penalty additionally freezes σ-shrink proportional to `f` (§5.5); at `f = 0` this is a no-op, so clean accounts are unaffected and D1 holds verbatim for them. |
| **D2** | Modifiers compose **multiplicatively** on `Δμ` in the order from proposal §13.2. Soft-cap and boosting-penalty attenuate the **positive side only** (never turn a loss into a gain). |
| **D3** | Ineligible player (AFK) → frozen output (Δμ=0, σ unchanged, crDelta=0) **but still participates in the PL ranking** so other teams update correctly. All-ineligible match → **void** (nobody moves). |
| **D4** | `scaleFactor=1.0`, `baseOffset=250` (proposal omitted these). Anchors the median established player ≈ 1000 CR; fresh player ≈ 200 (rises as σ resolves). Season-tunable. |
| **D5** | `placementWeights` default = mild symmetric emphasis on extremes, **zero net drift** (renormalized to per-curve mean 1.0 per Trinity M3; previously "near-zero", simulation-guarded). Top-heavy alternative documented. |
| **D6** | **Zero runtime third-party deps** (no zod inside the engine; hand-rolled param guards). `openskill` is a **test-only** oracle dependency. |

---

## 3. Domain model & invariants (authoritative)

Two coupled quantities per player-season:

1. **Latent skill `(μ, σ)`** — Bayesian state. `μ` is a *gamified* skill score (deliberately distorted by streak/boosting/placement modifiers — the proposal wants engagement mechanics). `σ` is *honest uncertainty*: only PL shrinks it; gamification never touches it (keeps future smurf-detection valid).
2. **CR** — the conservative public rating, **purely derived**: `CR = (μ − 3σ)·scaleFactor + baseOffset`.

### Invariants (MUST hold; encoded as property tests; Trinity validation targets)

- **I1** — Under `rate()`, `σ_after ≤ sqrt(σ_before² + τ²)` (information is non-negative beyond the τ-dynamics injection). `σ` strictly shrinks when a player's variance-share is non-negligible; a low-variance-share player on a high-σ team may see `σ` rise by at most the τ-dynamics term — this matches openskill (I10) and is correct TrueSkill behavior, **NOT** a violation. `σ` increases beyond the τ-dynamics term only via `softReset`.
- **I2** — Determinism: `rate(x)` deep-equals `rate(x)`; **invariant to input permutation** of team order and intra-team player order.
- **I3** — Ineligible player ⇒ exactly zero movement; but its team's aggregate still informs other teams' PL update.
- **I4** — All players ineligible ⇒ void (zero movement for everyone).
- **I5** — Ceteris paribus, better placement ⇒ `Δμ_base ≥` worse placement's `Δμ_base` (monotonic at the base-PL layer).
- **I6** — `streakMult ∈ [lossFloor, winCeil] = [0.25, 1.35]`.
- **I7** — `|Δμ_final| ≤ effectiveCap` (σ-scaled dispersion cap, §5.6: `effectiveCap = maxDeltaMu·max(1, σ_before/dispersionSigmaRef)`) for every player.
- **I8** — `toCR` strictly increasing in μ, strictly decreasing in σ.
- **I9** — No `NaN`/`Infinity` output for any structurally valid input.
- **I10** — Base PL update equals the `openskill` reference (PlackettLuce, same hyperparams) within `1e-9`.
- **I11** — Over a balanced Monte-Carlo simulation, mean CR drift per synthetic season is bounded (no systematic inflation/deflation). Tuning guardrail, not a hard fail; surfaces in `simulation.test.ts`.

**Trinity validation question (Track 4):** do the modifiers — scaling `Δμ` by gamification multipliers, soft-cap on μ while CR is derived from `μ−3σ`, the interaction of provisional `2.0×` amplification with the naturally-fast `μ−3σ` climb as σ resolves, and the compounding of streak loss-protection with placement-weight loss-dampening — violate any intended invariant or create a pathology (rank instability, runaway inflation, frozen legitimate climbers)? Identify pathologies and propose parameter or structural corrections.

---

## Trinity validation (2026-06-14, claw_max, conf 0.90)

Track-4 meta-validation run (`claw_max`, confidence 0.90) surfaced **6 findings** against the D1–D6 engine and the amended I1. Findings are grouped as **C** (correctness/invariant) and **M** (mechanism/exploit-surface).

| # | Finding | Summary |
|---|---|---|
| **C1** | **Provisional cap-bite** | The provisional `2.0×` amplification (§5.2) routinely drives `Δμ_base × placementAmp` past `maxDeltaMu=150`, so the dispersion cap (§5.6) *bites every placement match* for high-variance newcomers. The cap — not the PL signal — sets their climb rate, flattening the very placement period it is meant to accelerate. Root cause: a fixed (σ-blind) cap applied after a σ-correlated amplifier. |
| **C2** | **σ-collapse ratchet** | Because gamification never touches σ (D1) but `Δμ_base` and the σ-shrink both scale with variance-share, a player who is repeatedly back-distributed a *small* variance-share (low-share player on high-σ teams) ratchets toward a frozen σ slower than μ moves — μ can run well ahead of a still-wide σ, so CR (`μ−3σ`) lags real skill for an extended window. Not an I1 violation under the amended bound, but a convergence-speed pathology. |
| **M3** | **Weight inflation** | Placement weights (§5.1) had per-curve means **> 1.0** (e.g. the 8-team curve sums to 8.78, mean 1.0975), injecting a small positive net `Δμ` drift on every match independent of placement — slow ladder-wide inflation that I11's balanced sim only weakly detects. Fix: renormalize each curve to **mean 1.0** (see §7). |
| **M4** | **σ-laundering** | A coordinated lobby can *launder* a booster's σ: stack the boosted account on teams whose aggregate σ is high so its individual variance-share (hence σ-shrink) stays small, keeping σ artificially wide → CR (`μ−3σ`) suppressed while μ is farmed, then cash the gap later. Detection (lobby σ-ratio + σ-trajectory anomaly) is **out of engine scope** — it belongs to the future integrity slice (see §12). The engine cannot and should not self-police this. |
| **M5** | **Streak asymmetry** | Streak loss-floor `0.25` vs win-ceil `1.35` (§5.3) is deliberately asymmetric (loss-protection > win-amplification), but combined with placement-weight loss-dampening it can over-insulate a tilting account from CR decay, slowing legitimate down-ranking. Judged **acceptable** (engagement-positive, bounded) — keep with monitoring. |
| **M6** | **Soft-cap compression** | The soft cap (§5.4) `1/(1 + (cr−thr)/scale)` with `thr=5000, scale=1000` compresses high-CR Δμ so hard that, above ~8000 CR, distinct skill levels map to near-identical climb rates → rank compression at the top. Flagged for future re-tuning; **no change this slice** (threshold is far above current ladder ceiling). |

### Decisions

- **DEC-A — Boosting freeze, hybrid minimal.** Keep **D1 σ-sacrosanct** and CR-derived behavior unchanged for clean accounts (`boostingPenaltyFactor f = 0`). For **flagged accounts only** (`f > 0`), the boosting penalty additionally *freezes σ-shrink proportional to `f`*: instead of accepting the full PL σ-shrink, blend it back toward `σ_before` by the penalty fraction:
  ```
  σ_after = σ_before − (1 − f)·(σ_before − σ_afterPL)
  ```
  where `σ_afterPL` is the unmodified §4 PL result. At `f = 0` this is exactly `σ_afterPL` (clean accounts untouched, D1 preserved); at `f = 1` σ is fully frozen (`σ_after = σ_before`), denying a flagged booster the CR uplift that σ-shrink would grant. This is the minimal structural change that directly counters M4 σ-laundering *on the engine side for already-flagged accounts*, without weakening σ's honesty for the clean population. (Detection of *who* is flagged remains upstream in integrity — see §12.)
- **DEC-B — Streak loss-floor.** Keep the streak loss-floor at **0.25** and **monitor** (addresses M5 by observation rather than change; asymmetry is intended and bounded).

C1 is addressed by the σ-scaled dispersion cap (§5.6); M3 by renormalized weights (§5.1, §7); M4/DEC-A by the flagged-only σ-freeze (§5.5); M5/DEC-B by monitoring. C2 and M6 are tracked for future tuning (no this-slice change).

---

## 4. Core algorithm — Weng-Lin Plackett-Luce

Function: `ratePlackettLuce(teams, params) → Array<{ playerId, deltaMu, sigmaAfter }>`.

Model: Weng & Lin (2011), *A Bayesian Approximation Method for Online Ranking*, §4 (Plackett-Luce full ranking). Reference oracle: the `openskill` npm package's `PlackettLuce` model.

**Steps:**
1. **Dynamics:** inflate each player's variance before the update: `σ_i² ← σ_i² + τ²` (prevents σ from freezing).
2. **Team aggregation:** `μ_team = Σ_{i∈team} μ_i`, `σ²_team = Σ_{i∈team} σ_i²`.
3. **Match normalizer:** `c = sqrt( Σ_{all teams} (σ²_team + β²) )`.
4. **PL ranking update:** compute team-level mean adjustment `Ω_team` and variance adjustment `Δ_team` from the Plackett-Luce ranking terms (per the reference). Ties (equal `placement`) handled per Weng-Lin tie convention.
5. **Back-distribution to players (proportional to individual variance share):**
   - `Δμ_i = (σ_i² / c) · Ω_team`
   - `σ_i²_after = σ_i² · max(1 − (σ_i²/c²)·Δ_team, κ)` ; `σ_i_after = sqrt(σ_i²_after)`
6. Return `{ playerId, deltaMu: Δμ_i, sigmaAfter: σ_i_after }` per player. (Players that share a team get equal `Ω/Δ` but variance-weighted individual deltas.)

**Correctness gate (I10):** `oracle.test.ts` configures `openskill` with our `{mu, sigma, beta, tau, kappa}` defaults, runs ≥15 fixtures (8-team Duos, 6-team Trios, ties, lopsided rosters), and asserts our base output equals openskill's `rate()` within `1e-9`. The implementer **reads openskill's PlackettLuce source from `node_modules`** to port it faithfully.

---

## 5. Modifier pipeline (per eligible player i, team k)

Order per proposal §13.2; multiplicative on `Δμ_base` from §4:

```
Δμ = Δμ_base
   × placementWeight(placement_k, teamCount, params)        // §5.1
   × placementAmp(state_i, params)                          // §5.2  (2.0× while provisional)
   × streakMultiplier(state_i.currentStreak, sign(Δμ), params) // §5.3 [0.25, 1.35]
   × softCapFactor(cr_i, Δμ, params)                        // §5.4  (positive side only)
   × boostingPenalty(Δμ, participant.boostingPenaltyFactor) // §5.5  (positive side only)
Δμ_final, clamped = dispersionCap(Δμ, σ_before, params)     // §5.6  last (σ-scaled cap)
μ_after  = μ_before + Δμ_final
σ_after  = sigmaAfter from §4, then DEC-A flagged-only freeze (§5.5)   // modifiers touch σ ONLY for flagged f>0 — D1 holds for clean accounts
CR_after = toCR(μ_after, σ_after, params)
crDelta  = CR_after − CR_before
```

### 5.1 `placementWeight(placement, teamCount, params)`
Return `params.placementWeights[teamCount]?.[placement-1] ?? 1.0`. Default curves (mild, symmetric, **renormalized to per-curve mean 1.0** per Trinity M3 — the pre-validation curves had mean ≈1.097/1.093, injecting a slow positive Δμ drift on every match):
- 8 teams (Duos): `[1.0934, 1.0205, 0.9658, 0.9203, 0.9203, 0.9658, 1.0205, 1.0934]` (mean 1.0)
- 6 teams (Trios): `[1.0793, 0.9878, 0.9329, 0.9329, 0.9878, 1.0793]` (mean 1.0)

(Shape — symmetric emphasis on the extremes — is preserved; only the level is divided by the old mean. Net per-match weight drift is now zero by construction, strengthening I11.)

### 5.2 `placementAmp(state, params)`
`state.placementMatchesRemaining > 0 ? params.placementAmp : 1.0`.

### 5.3 `streakMultiplier(currentStreak, deltaMuSign, params)` + `nextStreak(currentStreak, isWin)`
- Gain (`deltaMuSign > 0`) while `currentStreak > 0`: `1 + (min(currentStreak, threshold)/threshold)·(winCeil − 1)`, capped at `winCeil = 1.35`.
- Loss (`deltaMuSign < 0`) while `currentStreak < 0`: `1 − (min(|currentStreak|, threshold)/threshold)·(1 − lossFloor)`, floored at `lossFloor = 0.25`.
- Otherwise `1.0`. (`isWin` = `placement ≤ floor(teamCount/2)`, top-half.)
- `nextStreak`: win → `cs ≥ 0 ? cs+1 : 1`; loss → `cs ≤ 0 ? cs−1 : −1`.

### 5.4 `softCapFactor(cr, deltaMu, params)`
`deltaMu > 0 && cr > softCapThreshold` → `1 / (1 + (cr − softCapThreshold)/softCapScale)`, else `1.0`. Always in `(0, 1]`. No hard ceiling.

### 5.5 `boostingPenalty(deltaMu, factor)` + flagged σ-freeze (DEC-A)
**Δμ side (unchanged):** `deltaMu > 0 ? (1 − clamp(factor, 0, 1)) : 1.0`. (Returns the multiplier; booster gains less.)

**σ side (new, DEC-A — flagged accounts only):** let `f = clamp(boostingPenaltyFactor, 0, 1)` and `σ_afterPL` be the unmodified §4 PL σ. For **`f > 0` only**, freeze σ-shrink proportional to `f`:
```
σ_after = σ_before − (1 − f)·(σ_before − σ_afterPL)
```
- `f = 0` (clean account): `σ_after = σ_afterPL` — **D1 σ-sacrosanct fully preserved**; the engine never touches a clean player's σ.
- `f = 1` (max-flagged booster): `σ_after = σ_before` — σ fully frozen, denying the CR uplift that σ-shrink would otherwise grant.

This is the engine-side half of the M4 σ-laundering countermeasure: it only acts on accounts already flagged upstream by `integrity` (the engine never decides *who* is flagged — see §12). σ never **increases** under this rule (the blend lies in `[σ_afterPL, σ_before]`, and `σ_afterPL ≤ σ_before` modulo τ-dynamics), so the amended I1 bound continues to hold.

### 5.6 `dispersionCap(deltaMu, sigmaBefore, params)`
The cap is **σ-scaled** (addresses Trinity C1: a fixed, σ-blind cap bit every provisional placement match). A high-σ player legitimately needs larger steps, so widen the cap proportionally to current σ:
```
effectiveCap = maxDeltaMu × max(1, sigmaBefore / dispersionSigmaRef)
{ value: clamp(deltaMu, −effectiveCap, +effectiveCap), clamped: |deltaMu| > effectiveCap }
```
with `dispersionSigmaRef = 85` (the "established" σ anchor from §7 — at or below it the cap is exactly `maxDeltaMu`; a fresh `σ=350` player gets a ≈4.1× wider cap, so the PL signal — not the cap — drives the placement climb). I7's bound becomes `|Δμ_final| ≤ effectiveCap`.

---

## 6. Contracts (`src/types.ts`)

```ts
export interface PlayerState {
  playerId: string;
  mu: number; sigma: number; cr: number;     // cr = materialized toCR(mu,sigma)
  currentStreak: number;                       // + wins / − losses
  matchesPlayed: number;
  placementMatchesRemaining: number;
  peakCr: number;
}
export interface ParticipantInput {
  playerId: string;
  state: PlayerState;
  championId: number;                          // pass-through for snapshot
  eligibleForProgression: boolean;
  isPremade: boolean;
  partyId?: string;
  boostingPenaltyFactor: number;               // 0..1, from `integrity` (upstream)
}
export interface TeamInput {
  teamId: number;
  placement: number;                           // 1..T (1 = best); ties allowed
  participants: ParticipantInput[];
}
export type RatingMode = 'DUOS' | 'TRIOS';
export interface MatchInput {
  matchId: string;
  mode: RatingMode;
  teams: TeamInput[];                          // generic over N teams × M players
  params: RatingParams;
}
export interface AppliedModifiers {
  plBaseDeltaMu: number;
  placementWeight: number;
  placementAmp: number;
  streakMult: number;
  softCapFactor: number;
  boostingFactor: number;
  dispersionClamped: boolean;
  finalDeltaMu: number;
}
export interface PlayerRatingResult {
  playerId: string;
  muBefore: number; muAfter: number;
  sigmaBefore: number; sigmaAfter: number;
  crBefore: number; crAfter: number; crDelta: number;
  eligible: boolean;
  isWin: boolean;
  newStreak: number;
  modifiers: AppliedModifiers;                 // full transparency breakdown (§3.5 of proposal)
}
export interface RatingResult {
  matchId: string;
  voided: boolean;                             // true when all ineligible (D3/I4)
  players: PlayerRatingResult[];
}
export interface RatingParams {
  mu0: number; sigma0: number; beta: number; tau: number; kappa: number;
  scaleFactor: number; baseOffset: number;
  placementWeights: Record<number, number[]>;
  placementAmp: number; placementMatchCount: number;
  streakLossFloor: number; streakWinCeil: number; streakThreshold: number;
  softCapThreshold: number; softCapScale: number;
  maxDeltaMu: number; dispersionSigmaRef: number;   // σ-scaled dispersion cap (Trinity C1, §5.6)
  resetAnchor: number; resetFactor: number; sigmaResetMult: number; sigmaResetCap: number;
}
```

Public API (`src/index.ts`): `rate(match: MatchInput): RatingResult`, `toCR`, `softReset`, `DEFAULT_PARAMS`, `validateParams`, plus the individual modifier fns (for isolated testing/tooling) and types.

---

## 7. Parameters — `DEFAULT_PARAMS`

| Param | Default | Source |
|---|---|---|
| mu0 / sigma0 | 1000 / 350 | DB schema |
| beta / tau / kappa | 175 / 3.5 / 1e-4 | TrueSkill ratio (σ0/2, σ0/100) |
| scaleFactor / baseOffset | 1.0 / 250 | D4 |
| placementWeights | §5.1 curves (renormalized, per-curve mean **1.0**) | D5 + Trinity M3 |
| placementAmp / placementMatchCount | 2.0 / 10 | proposal §3.1 |
| streakLossFloor / streakWinCeil / streakThreshold | 0.25 / 1.35 / 3 | §3.2 + Trinity DEC-B (keep + monitor) |
| softCapThreshold / softCapScale | 5000 / 1000 | §3.1 (scale inferred) |
| maxDeltaMu | 150 | inferred; simulation-tuned |
| dispersionSigmaRef | 85 | Trinity C1 (σ-scaled cap, §5.6); = established-σ anchor |
| resetAnchor / resetFactor | 1000 / 0.5 | §13.3 |
| sigmaResetMult / sigmaResetCap | 1.5 / 350 | §13.3 |

CR anchor sanity (scaleFactor=1, baseOffset=250): fresh 1000/350→**200**; post-placements 1000/150→800; established 1000/85→**~1000**; strong 1300/80→1310; elite 1800/70→1840.

`validateParams` (zero-dep) throws on: non-positive σ0/β; **non-positive `dispersionSigmaRef`** (division guard for the §5.6 σ-scaled cap); kappa∉(0,1); factors out of `[0,1]` where bounded; missing default-mode weight arrays; `streakLossFloor>1` or `streakWinCeil<1`.

---

## 8. Determinism (I2)

No `Date.now`/`Math.random`/I/O. Before any summation: sort teams by `(placement, teamId)`, players by `playerId`. Fixed f64 op order ⇒ reproducible. `rate()` output identical across runs and across permutations of input team/player order.

## 9. Eligibility & edge cases (D3/I3/I4)

- `eligibleForProgression=false`: player frozen (`muAfter=muBefore`, `sigmaAfter=sigmaBefore`, `crDelta=0`, `modifiers` zeroed) but its team aggregate **still enters** the PL computation for others.
- All participants ineligible ⇒ `RatingResult.voided=true`, every player frozen.
- Validate & test: <2 teams, empty team, duplicate placements (ties), `NaN`/`Infinity` inputs (reject), single eligible player, party of size > team size.

## 10. Package structure

```
packages/rating-engine/
  src/ index.ts · types.ts · params.ts
      model/plackett-luce.ts
      modifiers/{placement-weight,placement-amp,streak,soft-cap,dispersion-cap,boosting-penalty}.ts
      cr.ts · season.ts · rate.ts
  test/ fixtures/ · oracle.test.ts · cr.test.ts · season.test.ts
       modifiers/*.test.ts · rate.test.ts · properties.test.ts · simulation.test.ts
  package.json (zero runtime deps; dev: typescript, tsx, vitest, @vitest/coverage-v8, fast-check, openskill)
  vitest.config.ts (100% thresholds) · tsconfig.json · README.md
```

## 11. Test strategy

- **Oracle** (`oracle.test.ts`): base PL vs `openskill` PlackettLuce, ≥15 fixtures, tol 1e-9 (I10).
- **Unit**: each modifier + `toCR` + `softReset` in isolation, boundary values.
- **Property** (`properties.test.ts`, fast-check): I1 (amended bound `σ_after ≤ sqrt(σ_before² + τ²)`, not the old `σ_after ≤ σ_before`), I2, I5, I6, I7, I8, I9.
- **Snapshot** (`rate.test.ts`): realistic 8×2 Arena fixture → locked `RatingResult`.
- **Simulation** (`simulation.test.ts`): Monte-Carlo of N synthetic seasons → convergence, sane ladder spread, no NaN/Inf, bounded drift (I11). Doubles as the proposal's "simulation tooling." **Trinity-driven extension (C2):** the sim now **decomposes the CR-from-σ term `E[−3·Δσ]`** (the conservative-rating contribution of σ-shrink) **by tenure cohort and by week**, rather than reporting a single season-mean. For each `(cohort, week)` cell it reports `E[−3·Δσ]`, asserts **stationarity** (the per-week series flattens as σ converges — no cohort stuck with a persistently large `−3·Δσ`, which would be the C2 σ-collapse-ratchet signature), and tracks a **Gini coefficient** over end-of-season CR to guard against σ-driven over-compression or over-dispersion of the ladder.
- **Coverage gate**: 100% lines/branches/functions/statements enforced in `vitest.config.ts`.

## 12. Future hooks (noted, YAGNI now)

- Track un-modified PL `μ` separately for a "true skill" estimate (smurf detection, Phase 2/3).
- `placementWeights` top-heavy alternative for engagement A/B.
- Per-season param overrides feed `RatingParams` from `seasons.config` JSONB.
- **M4 σ-laundering *detection*** (Trinity) lives in the **future integrity slice, not this engine.** The engine's job is only to *consume* a flag (`boostingPenaltyFactor`) and apply the DEC-A flagged-only σ-freeze (§5.5). *Deciding who is laundering* requires cross-match, cross-lobby signal the stateless engine deliberately cannot see. The integrity slice should compute, per account/lobby: (a) a **lobby σ-ratio** — the boosted account's individual variance-share vs. the lobby aggregate, flagging persistently-suppressed shares — and (b) a **σ-trajectory anomaly** — σ staying anomalously wide while μ climbs across matches (the laundering signature). Those signals feed `boostingPenaltyFactor` upstream; the engine never recomputes them.
