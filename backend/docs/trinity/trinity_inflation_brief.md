# TRINITY — CR INJECTION / LADDER INFLATION (Phase-2 escalation)
## Profile: claw_max · model: opus · --data-origin meta_validation
## Companions: trinity_rating_brief.md (recalibration), trinity_caps_brief.md (PDL caps, built but OFF)

## 1. WHO YOU ARE
Principal competitive-ranking systems architect (same identity as the recalibration
+ caps briefs). You reason from invariants. You own the boundary between the Bayesian
posterior and the displayed reward, and you know that a conservative display
`CR = μ − 3σ` couples *every* reward to the uncertainty trajectory — so a sigma that
does not converge silently injects rating forever.

## 2. MISSION
A NON-DESTRUCTIVE diagnostic over the real 191-match season shows the live ladder
**injects ≈ +75.5 CR per match** (mean cr_delta +4.20 per participation, n=3438).
This is the **deferred Phase-2** from your recalibration run (you flagged "σ still
converges slowly … CR ≈ μ − const"). Diagnose the root cause precisely (the data
below isolates two channels), and propose a **feature-flagged, season-tunable,
simulatable, reversible** fix that neutralizes (or bounds-and-justifies) the injection
**without regressing the recalibration** (0% negative CR, per-match |swing| ≤ 77) and
**compatible with the PDL cap layer** that is built and waiting to ship.

## 3. PREMISE (do not relitigate)
The recalibration is correct and live: σ0=200, β=100, τ=1.5, μ0=1000, display
`CR=(μ−3σ)·1 + 250`. 0 negatives, swings ±77. The PDL cap layer (placement-relative
gain/loss clamp via option B-pure — μ clamped to hit the capped cr_delta, no ledger,
because arenarank runs NO matchmaking) is implemented, tested, flag-OFF. Do NOT
re-propose the cap; assume it will be enabled AFTER this is resolved. The surface
pathologies are closed.

## 4. DOMAIN MODEL (engine as it runs)
Per eligible player per match: OpenSkill `PlackettLuce(μ0,σ0,β,τ).rate(teams, ranks)`
→ (Δμ_base, σ_after); a mean-1.0 placement weight + streak/soft-cap/boosting
multipliers; a μ-space dispersion clamp ±E≈80; then `CR=(μ−3σ)+250`. Identity:
`cr_delta = Δμ_final − 3·Δσ`. Format: 6 subteams × 3 players (Trios). 1863 players,
70% played exactly 1 game, mean 1.85 games/player.

## 5. THE DIAGNOSTIC (real data, no caps — `scripts/diag_inflation.py`)

**Decomposition of mean cr_delta (per participation, n=3438):**

| channel | value | share |
|---|---|---|
| mean Δμ (final) | **+0.791** | — |
| mean (−3·Δσ) | **+3.406** | — |
| mean cr_delta = Δμ − 3Δσ | **+4.197** | 100% |

**Per-match SUM (conservation check, n=191 matches):**

| quantity | mean / match | reading |
|---|---|---|
| Σ Δμ over all participants | **+14.23** | ≠ 0 → **the PL update does NOT conserve μ** (it injects ~+14 μ/match) |
| Σ cr_delta over all participants | **+75.54** | the real CR injection |

So the +75.5/match injection has TWO channels:
- **σ-dividend (≈ +61/match, ~81%):** `−3·Δσ > 0` because σ shrinks. Would be a benign
  one-time provisional climb IF σ converged to a floor quickly. It does NOT (next point).
- **μ non-conservation (≈ +14/match, ~19%):** the Plackett-Luce `rate()` output sums to
  a net-positive Δμ across the 6×3 lobby. Unexpected for a "conservative" update; likely
  an artifact of how PL distributes μ across many teams, the τ additive-variance step, or
  the rank-tie handling. You must identify which.

**σ trajectory by games played (the crux — σ barely moves):**

| games before | n | mean σ_after |
|---|---|---|
| 0 | 1863 | 198.8 |
| 1 | 560 | 197.6 |
| 3 | 150 | 195.7 |
| 5 | 61 | 193.9 |
| 10 | 15 | 190.3 |

σ falls ≈ 1.0/game from σ0=200. At this rate it needs **hundreds of games** to approach
a floor — so the −3Δσ dividend is NOT a transient provisional effect; it **drips ~+3.4
CR/game effectively forever** within any realistic player lifetime. THIS slow convergence
is the amplifier that turns a normal Bayesian σ-shrink into persistent ladder inflation.

## 6. QUESTIONS TO RESOLVE
Q1. **Is this real ladder inflation or acceptable bounded climb?** The season soft-reset
    pulls μ halfway to 1000 and re-inflates σ each season. Quantify: over a realistic
    season (your assumption on games/active-player), how much net CR does a player
    accumulate purely from injection vs skill? Is the soft-reset sufficient to bound it,
    or does rank meaning erode within a season?
Q2. **The σ-convergence channel (81%).** Should σ converge faster (so the dividend is a
    bounded provisional climb that terminates), or should the display be decoupled from
    σ? Weigh: lowering β (faster info gain, but the recalibration raised swing-safety by
    keeping β=100=σ0/2), lowering τ further (τ=1.5 adds variance/game, fighting
    convergence), a σ-floor, or a display change (μ − kσ with smaller k, or a different
    conservative form). Each must preserve 0-negatives and ±77 swings. Simulate.
Q3. **The μ non-conservation channel (19%).** Identify WHY Σ Δμ = +14/match (PL math,
    τ, ties, team-count). Is it correctable (re-center μ per match? different model
    config?) or inherent? Does it matter once the cap layer caps cr_delta anyway?
Q4. **Interaction with the PDL cap.** The cap (B-pure) clamps cr_delta and back-solves μ.
    With caps ON, the per-match injection rose to ~+126/match in sim (the cap compresses
    the long provisional LOSS tail more than gains). Does your inflation fix compose with
    the cap, or must they co-designed? Order of operations?

## 7. CONSTRAINTS & DELIVERABLE
- Pure, season-tunable params preferred (`arena/rating/params.py` / `seasons.config`);
  flag-gated; reversible (`git revert` + `scripts/rerate_matches.py --apply`).
- Every candidate quantified offline on the 191-match history (extend
  `scripts/sim_params.py` / `diag_inflation.py`); report Σ cr_delta/match,
  Δμ vs −3Δσ split, σ-by-games, and the recalibration guards (0 negatives, ±77).
- Deliverable: (1) root-cause statement per channel; (2) decision on Q1 (fix vs accept-
  and-bound) with the season-accumulation math; (3) the param/config bundle (name ·
  old→new · channel · flag) with simulated before/after; (4) interaction order with the
  cap layer; (5) honest pushback — if the injection is acceptably bounded by soft-reset,
  say so and recommend shipping the cap as-is rather than over-engineering.

Quantify everything. Where σ-convergence speed trades against swing-safety, show the
frontier. Do not regress the recalibration.
