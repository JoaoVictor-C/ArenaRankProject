# TRINITY — ADDENDUM: PREMADE INFERENCE UNDER SPARSE DATA (feeds R3)
## Profile: claw_max · model: opus · --data-origin meta_validation
## Companion to: trinity_caps_brief.md (the cap-layer design). Read that context first.

## 1. WHO YOU ARE
Same identity as the cap-layer brief: principal competitive-ranking systems
architect. For THIS task you wear a second hat — a **latent-variable inference
statistician**. You are being asked to recover an unobserved categorical variable
(did these players queue together as a party?) from a sparse, noisy co-occurrence
signal, and to express the answer as a *calibrated probability the rating system
can consume*, not a boolean it can be fooled by.

## 2. THE PROBLEM (why R3 is blocked)
R3 (party-size dampening: duo/trio gains less than solo) requires knowing party
membership. **Riot Match-V5 does NOT expose it.** Confirmed against our parser:
the payload gives `playerSubteamId` (who shared a subteam THIS game),
`subteamPlacement`, `puuid`, `championId` — and nothing about queue grouping.
Same-subteam ≠ same-party: a 3-player subteam may be a premade trio, a premade duo
+ 1 solo fill, or 3 solos auto-matched. There is no authoritative source.

The only recoverable signal is **co-occurrence across matches**: the same puuids
landing on the same subteam repeatedly. The product owner named the two failure
modes precisely:
- **False positive:** two solo players randomly drawn into the same subteam twice
  get mislabeled a duo, and get unfairly dampened.
- **False negative / cold start:** a genuine premade member who has played only one
  game has zero co-occurrence history and looks solo.

The PO's framing: "there is no easy way — design a deep solution."

## 2b. THE LATENCY PROBLEM (central constraint — the PO's sharpest objection)
Co-occurrence detection is **intrinsically lagging**. Any history-based threshold
only fires AFTER N shared games, so the first N games of every premade leak
un-dampened (incorrect) PDL. The max-71 pair is an OUTLIER, not a bar — but it
exposes the structural flaw: a real-time, at-ingest premade label is **impossible**
(the only authoritative source is Riot, who does not expose it). Worse in our
regime: with 70% single-game players, most premades never reach any bar at all →
detection is simultaneously **too late** (leaks early games) AND **mostly blind**
(never fires for short-lived premades), and when it does fire it fires only on the
heavy-repeat pairs — arguably the most legitimate competitive duos, the ones the PO
may least want to punish.

**The escape the PO favors — and you must design around — is RETROACTIVE
CORRECTION.** This platform already has a non-destructive, idempotent re-rate
pipeline (`scripts/rerate_matches.py --apply`): the entire season can be recomputed
from match history at any time. Therefore the architecture is NOT "detect in real
time then dampen" — it is **"rate optimistically now (assume solo), let the
pair-affinity signal mature, then periodically RE-RATE the affected matches with the
now-inferred premade multiplier."** The leak becomes *temporary and self-healing*,
bounded by the re-rate cadence, not permanent. Design the inference module as the
input to a scheduled re-rate sweep, and treat the at-ingest value as a provisional
prior that later correction overwrites.

## 3. GROUND TRUTH FROM REAL DATA (191 matches, Trios = 6 subteams × 3 players)
- Population: 1863 players, **70.0% (1303) played exactly 1 game**, 15.5% played 2,
  steeply decaying. Mean 1.85 games/player. The co-occurrence signal is therefore
  *absent* for the majority by construction.
- Co-occurrence pair counts (same subteam, same match, distinct unordered pairs):

  | shared games | pairs |
  |---|---|
  | ≥1 | 2859 |
  | ≥2 | 195  |
  | ≥3 | 74   |
  | max single pair | **71** |

- **Bimodal interpretation (your hypothesis to test):** a large mass at shared=1
  (consistent with chance), and a long tail up to 71 that is statistically
  impossible under random matchmaking → unambiguous premades exist and ARE
  detectable at the top of the tail.

## 4. THE BASE-RATE MATH YOU MUST USE
A lobby has 18 players in 6 subteams of 3. Conditional on two specific players both
being in the same lobby, the chance they share a subteam is
`2/17 ≈ 0.1176`. So shared=k purely by chance requires co-occurring in k lobbies
AND being co-subteamed each time — but the dominant term is how often two players
re-enter the same lobby at all (a function of the active matchmaking pool and MMR
bucketing, which you must model or bound). `0.1176^71 ≈ 0` → the max-71 pair is a
certainty-premade. Your job is the **middle**: where shared ∈ {2,3,4,5} and the
posterior is genuinely uncertain.

## 5. MISSION
Design a **premade-inference module** that, for any subteam in a match, outputs for
each member a **calibrated probability of being in a party** (and party size),
which the R3 cap multiplier then consumes *as a probability, not a threshold*.

Specify, concretely:

P1. **The inference model.** A per-pair (and pair→group) latent-variable estimator.
    Candidates you must weigh: likelihood-ratio test `P(shared=k | premade) /
    P(shared=k | chance)`; a Beta-Binomial / Bayesian posterior over "party
    affinity" per pair; a decaying co-occurrence score. State priors explicitly
    (premade base rate in the population — you may infer it from the §3 tail shape).
    Pairs → groups: how a high-affinity {A,B} and {B,C} compose into a trio {A,B,C}.

P2. **Time dynamics.** Premades dissolve and re-form. Specify a decay (half-life on
    co-occurrence weight) so a duo that stopped playing together 60 days ago is no
    longer flagged. The PO intuition "1 trio game → treat as solo by default" is a
    cold-start prior, not a rule — encode it as such.

P3. **Asymmetric error cost.** Punishing a true solo (false positive) is a worse
    product outcome than missing a true premade (false negative): it breaks the
    fairness contract for an innocent player. Bake this asymmetry into the decision
    (e.g., require a high posterior before any dampening; bias the prior toward
    solo). Quantify the FP/FN trade-off curve.

P4. **How the cap consumes a probability.** Replace the boolean `party_mult` with an
    expectation: `effective_mult = 1 − P(premade)·(1 − mults[inferred_size])`, or
    your better proposal. Show that at P=0 it is a no-op (solos untouched) and
    degrades gracefully when history is absent (P defaults low).

P5. **Cold-start & sparse-data degradation.** With 70% single-game players, most
    rows have no signal. Define behavior: default to solo/no-dampening, accumulate
    silently, only act once the posterior clears the P3 bar. Shadow-only until then.

P6. **Retroactive correction loop (the answer to §2b latency).** Specify the
    detect-late / correct-retroactively design: (a) at ingest, rate with a
    provisional party prior (default solo) so PDL is shown instantly; (b) a
    pair-affinity store matures as history accumulates; (c) a scheduled re-rate
    sweep (`scripts/rerate_matches.py`) recomputes affected matches once a pair
    crosses the posterior bar, overwriting the provisional gains with corrected
    ones. Define: the re-rate trigger/cadence (per-match-batch? nightly? on
    bar-crossing?); the **bounded leak** between provisional and correction
    (quantify worst-case PDL over-credit per premade before the sweep catches it);
    how a player experiences the correction (silent adjustment vs visible "rank
    settling"); and convergence — prove the sweep is idempotent and does not
    oscillate as affinity estimates wobble near the bar (hysteresis?). This loop is
    the core deliverable, not an afterthought.

## 6. CONSTRAINTS
- Quantifiable on THIS 191-match dataset. Report: how many of the 195 (≥2) and 74
  (≥3) pairs your model would classify premade at your chosen posterior bar, your
  estimated FP rate against the 2/17 chance model, and the implied % of
  participations that would receive any dampening.
- Pure, season-tunable params (decay half-life, posterior bar, priors) in
  `arena/rating/params.py` / `seasons.config`. Shadow-only flag until validated.
- A new derived store (pair-affinity table, rebuilt from match history) is allowed;
  specify its shape and refresh cadence. No live Riot dependency beyond match-v5.
- Must compose cleanly with the cap layer in trinity_caps_brief.md (it replaces the
  flagged-off `caps.party.*` block).

## 7. DELIVERABLE
1. The inference model (P1) with priors and the likelihood-ratio / posterior math.
2. Time-decay + cold-start spec (P2, P5).
3. The asymmetric-cost decision rule and FP/FN trade-off (P3).
4. The probability→multiplier integration (P4), proven no-op at P=0.
5. **The retroactive-correction loop (P6)** — provisional-at-ingest → mature →
   re-rate sweep — with trigger/cadence, bounded-leak quantification, convergence/
   hysteresis proof, and player-facing correction UX. This is the central artifact.
6. Param bundle (name · value · rationale · flag), mirroring the cap brief's format,
   including the re-rate cadence and provisional-prior params.
7. Classification results on the real data (§6) + honest statement of what cannot be
   validated with 1.85 games/player and what minimum data volume would change that.
8. Pushback: if probabilistic premade dampening — even with retroactive correction —
   is not worth the false-positive risk at this data scale, say so and recommend
   deferring R3 entirely with the threshold of evidence that would reopen it.

Think from the inference problem down. A boolean threshold is the naive answer the
PO already rejected — give the calibrated-probability solution. Quantify FP/FN on
the real pairs. Where the data is too sparse to validate, say so loudly.
