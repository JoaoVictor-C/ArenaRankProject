# MISSION BRIEF — Recalibrate a gamified OpenSkill ladder that is emitting negative & wildly volatile ratings

## 1. WHO YOU ARE (identity, system-prompt level)

You are a **Principal Rating-Systems Architect & competitive-integrity statistician**. You have shipped TrueSkill/OpenSkill-derived ladders at scale (chess Glicko, TrueSkill2, Plackett-Luce multiteam). You think in terms of **invariants, convergence dynamics, and player-perceived legibility** — not surface patches. You reason about the *interaction* between a Bayesian skill posterior (μ, σ) and a **conservative display transform**, and you know that a display that subtracts a multiple of σ is only sound if σ actually converges in the realized games-per-player regime. You are skeptical of your own past fixes when production data contradicts them. You quantify every recommendation (predicted effect on the distributions below) and you make each change **independently reversible**.

This is NOT a security task. It is a **rating-calibration / mechanism-design** task. Do not propose surface classes; reason from the engine math and the production evidence.

## 2. SYSTEM UNDER REVIEW (verbatim math)

Per-match pipeline (Python, pure). For each eligible player in a match of `team_count` teams (Arena: TRIOS=6 teams, DUOS=8 teams), the **OpenSkill PlackettLuce** model is run on the prior (μ,σ) of every player; then a gamified modifier layer is applied to the **raw μ-delta**:

```
model = PlackettLuce(mu0=1000, sigma0=350, beta=175, tau=3.5, kappa=1e-4)
updated = model.rate(teams_with_prior_mu_sigma, ranks=placements)

delta_mu_base = updated.mu - prior.mu            # raw PL μ move for this player
delta = delta_mu_base * placement_weight         # ~[0.99 .. 1.08], mean 1.0 (renormalized)
                       * placement_amp            # 2.0 while placement_matches_remaining>0 (first 10 games), else 1.0
                       * streak_mult              # win-streak: up to 1.35 ; loss-streak: down to 0.25 ; else 1.0
                       * soft_cap_factor          # <1 only when cr>5000 and delta>0 ; else 1.0
                       * boosting_factor          # <1 only for integrity-flagged accounts ; else 1.0
delta_final = clamp(delta, -E, +E)               # dispersion cap, E below
mu_after    = prior.mu + delta_final
sigma_after = updated.sigma                       # pure PL (σ-freeze only for flagged accounts)
cr_after    = (mu_after - 3*sigma_after) * 1.0 + 250        # CONSERVATIVE DISPLAY
cr_delta    = cr_after - prior.cr
```

Dispersion cap (this is a PRIOR TRINITY FIX, "C1", σ-scaled):
```
E = max_delta_mu * max(1.0, sigma_before / dispersion_sigma_ref)
  = 150 * max(1.0, sigma_before / 85)
# At sigma_before=350 (the regime almost every player is in): E = 150*(350/85) = 617.6
```

CR display transform: `CR = (μ - 3σ) + 250`. A brand-new player (μ=1000, σ=350) displays `CR = (1000-1050)+250 = 200`.

Key identity (derived): since `cr = (μ-3σ)+250`,
```
cr_delta = delta_final - 3*(sigma_after - sigma_before) = delta_final - 3*Δσ
```
Because PL always shrinks σ (Δσ ≤ 0), the term `-3*Δσ ≥ 0` adds CR to EVERY match outcome, winner or loser, proportional to how fast σ is shrinking.

## 3. YOUR OWN PRIOR DECISIONS ON THIS ENGINE (now suspect — reconcile)

A previous Trinity audit of this exact engine produced:
- **DEC-A**: σ-freeze (no σ-shrink) for integrity-flagged accounts only.
- **DEC-B**: keep streak loss-floor at 0.25 (a loss-streak dampens losses to ≤25%).
- **C1**: make the dispersion cap **σ-scaled** (`E = 150 * max(1, σ/85)`), rationale "high uncertainty ⇒ allow bigger moves so legit fast-climbers and deserved provisional losses aren't flattened."
- **M3**: renormalize placement-weight curves to mean 1.0 (no net μ drift).

**C1 is now implicated**: because almost every player sits at σ≈350, the cap evaluates to ≈617, so it essentially never binds for the provisional players who produce the worst swings. Re-examine C1 honestly.

## 4. PRODUCTION EVIDENCE (real data — 1,863 players, 191 Arena matches, 3,438 participations since season start)

**CR distribution (player_seasons.cr):**
- n=1863, min=**-360.4**, max=1731.0, avg=216.2
- **295 players (15.8%) have CR < 0** ("negative PDL" — the #1 user complaint)
- percentiles: p01=-146, p05=-40, p25=130, p50=233, p75=312, p95=454, p99=703

**μ / σ distribution:**
- μ: min=424, max=2278, avg=1005
- σ: min=265, max=350, **avg=346** ← σ barely below σ0=350 for the whole population

**σ does NOT converge with games** (avg σ and avg CR by games played):
```
games |   n  | avg_σ | avg_cr | #neg
  1   | 1303 | 347.8 | 190.9  | 239
  2   |  289 | 345.9 | 223.4  |  27
  3   |  121 | 344.0 | 251.9  |  19
  4   |   57 | 342.3 | 286.0  |   3
  5   |   32 | 340.5 | 337.6  |   4
  6   |   20 | 339.0 | 336.8  |   3
  7   |   13 | 337.4 | 465.0  |   0
 10   |    2 | 334.4 | 695.8  |   0
 12   |    1 | 331.1 | 585.4  |   0
```
After 12 games σ fell only 350→331 (~1.6/game). The −3σ penalty (~−1020) is effectively **permanent**, so the conservative display never "unwinds." **70% of players have exactly 1 game; mean games/player = 1.85.** The realized regime is almost entirely un-converged.

**cr_delta (per-match CR change) distribution:**
- n=3438, min=**-572.5**, max=+203.9, avg=**+8.80** (systematic positive drift), stddev=**119.6**
- |Δ|>50: 69% of matches · |Δ|>100: 43% · |Δ|>200: 12% · |Δ|>500: 1 match

**Worst loss (real row):** placement=6 (last of 6), cr_before=212.0 → cr_after=**-360.4**, cr_delta=-572.5.
`plBaseDeltaMu=-269.9, placementWeight=1.079, placementAmp=2.0, streakMult=1.0, finalDeltaMu=-582.6, dispersionClamped=false`.
→ The raw PL μ-move was already −270 in ONE game (because σ is huge ⇒ PL step is huge); placement_amp=2.0 doubled it to −583; the σ-scaled cap (617) did not bind.

**Biggest gain (real row):** placement=1, cr_before=454.9 → cr_after=658.8, cr_delta=+203.9.
`plBaseDeltaMu=+69.6, placementWeight=1.079, placementAmp=2.0, streakMult=1.35, finalDeltaMu=+202.9`.
→ Note asymmetry: max single-game gain +204 vs max single-game loss −572.

## 5. INVARIANTS THE LADDER SHOULD SATISFY (target end-state)

1. **Legible non-negativity**: a legitimately-playing account should essentially never display negative CR. Users read "−360 PDL" as a broken system.
2. **σ must converge** so the conservative penalty unwinds: after ~10–15 games σ should be well below σ0 (e.g. ≲ 0.5·σ0), in the *actual* 1–2-games-dominated regime.
3. **Per-match Δ legible & bounded**: a single match should move CR within a human-legible band (order ±10–40 established; maybe up to ±80–100 provisional). ±572 is unacceptable; the cap must actually bind in the σ-regime players are in.
4. **No systematic drift**: population mean cr_delta ≈ 0 (apart from the intended one-time provisional unwind). +8.8/match compounds into inflation.
5. **Win/loss symmetry**: comparable performance yields roughly symmetric gains/losses.
6. **Provisional amplification must aid convergence, not amplify noise into the DISPLAY** — currently placement_amp=2 doubles μ-moves precisely when σ is largest (worst-converged players get the biggest display swings).
7. **Conservative display must be coherent with realized σ.** μ−3σ is defensible only if σ converges; otherwise reconsider the multiplier (μ−kσ, k<3), σ0, the (β,τ) convergence pair, a CR floor, or a display clamp.

## 6. DELIVERABLE (what to return)

Deliberate deeply, then return a **ranked set of concrete, independently-reversible changes**. For EACH change give:
- **id / name** and the exact knob (param value old→new, or structural code change with the precise pipeline edit).
- **mechanism**: why it fixes a named pathology (tie to §4 evidence and the `cr_delta = Δμ − 3Δσ` identity).
- **predicted effect** on the distributions in §4 (sign + rough magnitude): % negative CR, σ after 10 games, stddev/min/max of cr_delta, mean drift.
- **interactions / risks** with other changes and with prior decisions (DEC-A/DEC-B/C1/M3).
- **reversibility**: how to revert (it should be a param flip or a guarded code path).

Then give a **recommended bundle** (the subset to apply first) and an **ordering**, plus any **validation query** I should run against the data after applying to confirm the predicted effect.

Be decisive. Quantify. Reconcile C1. Distinguish "calibration" (param) fixes from "structural" (transform/pipeline) fixes, and tell me which pathology each class can and cannot solve. If μ−3σ is the wrong display for a 1.85-games-per-player regime, say so and give the replacement.
