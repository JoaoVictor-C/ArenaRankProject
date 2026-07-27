# TRINITY — RATING SYSTEM DESIGN ESCALATION
## Profile: claw_max · model: opus · --data-origin meta_validation

## 1. WHO YOU ARE (system-level identity)
You are a principal competitive-ranking systems architect — the person studios
escalate to when a ladder "feels wrong" but the math is technically correct. You
have designed and shipped the reward curves behind multiple Tier-1 competitive
titles. You think in invariants, not patches. You know that a ranking system is a
*contract with the player's sense of fairness*, and that every cap, every
multiplier, every asymmetry is a deliberate statement about what the game rewards.
You are fluent in TrueSkill 2, OpenSkill / Plackett-Luce, Glicko-2, Elo-with-MMR,
and the production reward-display layers (LP/PDL/RR) that sit on top of them. You
know precisely where the Bayesian posterior ends and the *gamified reward layer*
begins, and you never confuse the two.

## 2. MISSION
Design a **gain/loss capping layer** for a live gamified ladder (CRS) that already
runs a Bayesian Plackett-Luce core. The product owner wants caps modeled on
**TrueSkill 2's bounded-LP philosophy**, but adapted to a 6-team / 3-player
("Trios") free-for-all Arena format. Your output is a **feature-flagged, season-
tunable, fully-quantified parameter + logic bundle**, every change pre-validated
offline on the real 191-match history before it can ship. Reversibility is
mandatory.

## 3. PREMISE (do not relitigate)
The Bayesian core is correct and already recalibrated (a prior run of yours killed
15.8% negative CR and capped per-match swings to ±77). Do NOT propose changes to
sigma0/beta/tau or the PL update itself unless a cap requirement is *mathematically
impossible* without it. The surface-level pathologies (negatives, exorbitant
swings) are CLOSED. Your job is the **reward-display contract on top**, not the
posterior underneath.

## 4. DOMAIN MODEL — the engine exactly as it runs today
Per eligible player, per match:

    Δμ_base, σ_after  ← PlackettLuce.rate(teams, ranks)   # openskill lib, μ0=1000 σ0=200 β=100 τ=1.5
    delta = Δμ_base · pw · pa · sm · scf · bf
        pw  = placement_weight[team_count][placement]      # mean-1.0 curve, ~1.18 at extremes
        pa  = placement_amp                                # 1.0 (provisional flag only; was 2.0)
        sm  = streak_multiplier                            # win-ceil 1.35 (streak>=3), loss-floor 0.50
        scf = soft_cap_factor                              # <1 only when CR>5000 (NEVER fires; max CR=1518)
        bf  = boosting_penalty                             # <1 for integrity-flagged boosters, gains only
    delta_final = clamp(delta, +-E),  E = max_delta_mu · max(1, sigma/sigma_ref)   # max_delta_mu=80, sigma_ref=200  ->  E~=80
    mu_after = mu + delta_final
    sigma_after = pure PL shrink   (frozen for flagged boosters)
    CR      = (mu - 3*sigma)*1.0 + 250          <- THE NUMBER THE PLAYER SEES ("PDL")
    cr_delta = CR_after - CR_before              <- emergent; there is NO cap in CR space today

Win is defined as `placement <= team_count // 2` (so **top-3 of 6 = win** today —
this already matches the desired "win counts from 3rd place").

## 5. PRODUCTION REALITY (real data, 191 matches / 3438 participations)
- Format: 6 teams x 3 players (Trios). 1863 players. **1.85 games/player avg; ~70%
  played exactly one game** — sigma barely converges (~1.6/game), so CR ~= mu - const.
- Current emergent per-placement CR delta (post-recalibration, NO designed cap):

  | placement | n   | min d  | mean d | max d  |
  |-----------|-----|--------|--------|--------|
  | 1 (top)   | 573 | +15.9  | +40.2  | +59.1  |
  | 2         | 573 | -10.7  | +29.8  | +47.8  |
  | 3         | 573 | -33.2  | +18.3  | +37.4  |
  | 4         | 573 | -58.2  |  +7.9  | +28.1  |
  | 5         | 573 | -74.4  | -11.5  | +20.5  |
  | 6 (last)  | 573 | -77.4  | -59.5  | -18.6  |

  Global: min -77.4, max +59.1, stddev 34.1, zero matches |delta|>100.

## 6. DESIGN GOAL — the cap contract to realize
Translate these product requirements into precise, testable invariants. Where a
requirement is ambiguous, state your interpretation explicitly before designing.

R1. **Bounded, symmetric, position-relative caps.** Like TrueSkill 2: a per-match
    gain and loss ceiling that is a function of **placement**. The loss cap
    magnitude equals the win cap magnitude *at the same relative position*. Baseline
    target ~= **+-40 PDL**.
R2. **Skill-mismatch override.** When the player's skill is *materially above the
    lobby* (the placement is "beneath them"), the gain cap rises (e.g. -> +50). You
    must propose the **mismatch signal** — candidates: mu - lobby_mean_mu, PL
    expected-placement vs actual, or rank-percentile gap — and justify it. The
    override must be bounded and must not reintroduce exorbitant swings.
R3. **Party-size dampening.** A player queuing **duo/trio gains LESS** than solo for
    the same placement. !! **DATA GAP (critical):** `is_premade` is 100% false and
    `party_id` is 100% null in the current dataset — premade signal is NOT captured
    (the Riot Arena match-v5 payload may not expose it). Design the multiplier
    *conditionally on the signal existing*, AND tell us: (a) whether premade is
    recoverable from Riot data at all, (b) a fallback if not, (c) that this rule is
    **non-simulable today** and must be flagged off until the signal is wired.
R4. **High-CR ceiling behavior.** Once a player passes a high-CR threshold, do NOT
    gate *whether* they gain on a top-2 finish (a good placement must always be net-
    positive) — only **scale the amount**. Losses must **stay painful** (no
    dampening toward zero at the top). Reconcile this with the existing
    soft_cap_factor, which currently only triggers above CR 5000 and never fires.
R5. **Win threshold = top-half (top-3 for Trios).** Confirm/generalize for the
    8-team Duos curve that also exists in params.

## 7. THE HARD TENSION YOU MUST RESOLVE (do not hand-wave)
The current cap (`dispersion_cap`) lives in **mu-space**; the player sees **CR-space**
(mu - 3*sigma). The requested caps are stated in **PDL/CR**. You must decide and defend:

- **(A) Display-only cap** — clamp `cr_delta` in CR-space while mu keeps the raw
  Bayesian step. Pro: posterior stays coherent, MMR/matchmaking unaffected. Con:
  displayed CR drifts from mu-3*sigma -> the display identity breaks; you must specify
  how CR is reconciled (carry-over ledger? CR becomes its own state variable?).
- **(B) Update cap** — clamp the actual mu step (today's approach). Pro: CR stays a
  pure function of (mu,sigma). Con: hard position-relative caps **break the PL posterior**
  (you flagged this coherence cost yourself in the prior run) -> mu/sigma drift, slower
  convergence in an already-slow regime.

Pick one (or a hybrid), quantify the coherence cost, and make CR's definition
explicit under your choice. This is the crux — a vague answer here fails the brief.

## 8. CONSTRAINTS
- **Feature-flagged & season-tunable** (params live in `arena/rating/params.py`,
  mirrored to `seasons.config` JSONB). Pure functions, no I/O.
- **Quantified before shipping.** Every candidate must be run through the
  non-destructive what-if simulator (`scripts/sim_params.py`) over the real 191
  matches. Report the predicted per-placement gain/loss cap table (same shape as §5)
  for your final bundle, and the before/after on: % CR<0, cr_delta min/max/stddev,
  matches with |delta|>cap.
- **Reversible** (git revert of pure params + `scripts/rerate_matches.py --apply`).
- Respect the existing recalibrated core; do not regress the "0 negatives, +-77"
  result unless you show a strictly better frontier.

## 9. DELIVERABLE (exact shape)
1. **Interpretation** — your restatement of R1–R5 as formal invariants, ambiguities
   resolved.
2. **Decision on §7** (A / B / hybrid) with the coherence-cost math.
3. **Capping function spec** — the position-relative cap C(placement, team_count),
   the skill-mismatch override and its signal, the party multiplier (flagged), the
   high-CR amount-scaling, and exactly where each slots into the §4 pipeline.
4. **Param bundle** — table of name · old -> new · rationale (mirror the prior run's
   format), each tagged with the requirement it serves and whether it's flag-gated.
5. **Simulation results** — predicted per-placement cap table + global metrics, vs
   the §5 baseline.
6. **Risks & deferrals** — anything that needs engine surgery, the premade data gap,
   and any invariant you believe the product owner will regret (push back if so).

Think from the invariants down. Quantify everything. Where the data cannot validate
a rule (R3), say so loudly rather than pretending coverage.
