# Rating recalibration — 2026-06-15

Fixes the production pathologies reported on the gamified CRS ladder: **negative
PDL** (15.8% of players had CR < 0, min −360) and **exorbitant per-match swings**
(cr_delta down to −572, stddev 119.6, 43% of matches moving |Δ| > 100).

## Root cause

CR is a conservative display: `CR = (μ − 3σ)·scale + base_offset`. With
`σ0 = 350` the new-player display is `(1000 − 1050) + 250 = 200`, and the −3σ
term equals ≈ −1050. In this Arena regime (6 teams, **1.85 games per player on
average, 70% with exactly one game**) σ barely converges (≈ 1.6/game), so the
−3σ penalty never unwinds and any player whose μ dipped below ~788 displayed
negative. The volatility had two compounding sources, both confirmed in the data:

1. **High σ ⇒ huge raw PL μ-steps** (worst single-game `plBaseDeltaMu` = −270).
2. **`placement_amp = 2.0`** doubled the μ-delta during the provisional window —
   amplifying noise into the display for exactly the least-converged players.
3. **The C1 σ-scaled dispersion cap** `E = 150·max(1, σ/85)` evaluated to ≈ 617
   at σ ≈ 350, so it never bound on the −582 it was meant to catch.

Identity that ties it together: `cr_delta = Δμ_final − 3·Δσ`.

## Escalation

The engine math + production evidence were sent to the **Trinity** reasoning
runtime (`F:\wn-lab\trinity\core`, profile `claw_max`, model opus,
`--data-origin meta_validation`; brief in `backend/trinity_rating_brief.md`).
Trinity returned a 6-change feature-flagged bundle optimized for a **live hot-fix
with no reseed**. Because our situation is a full **re-rate of a dev season** (no
live standings to preserve), we adopted Trinity's own *preferred, Bayesian-
coherent* path (σ0 reduction — its "Phase-2") plus its R2 (revert C1) and R5
(streak symmetry), and **dropped the no-reseed-only machinery** (the `cr_raw`
column + display floor + R3/R4 σ-shrink surgery — the latter is moot for the 70%
single-game cohort, by Trinity's own admission).

Every candidate was quantified offline on the real match history with a
non-destructive what-if simulator (`scripts/sim_params.py`) before applying.

## Applied changes (all in `arena/rating/params.py`, pure params, reversible)

| param | old | new | why |
|---|---|---|---|
| `sigma0` | 350.0 | **200.0** | new-player display → +650; smaller PL steps; fixes negatives at the source |
| `beta` | 175.0 | **100.0** | keep β = σ0/2 |
| `tau` | 3.5 | **1.5** | less σ re-inflation (Trinity R4) |
| `placement_amp` | 2.0 | **1.0** | stop doubling the μ-delta (noise → display) |
| `max_delta_mu` | 150.0 | **80.0** | flat cap that actually binds |
| `dispersion_sigma_ref` | 85.0 | **200.0** | revert C1 σ-scaling → E ≈ 80 flat (Trinity R2) |
| `streak_loss_floor` | 0.25 | **0.5** | win/loss symmetry (Trinity R5) |
| `sigma_reset_cap` | 350.0 | **200.0** | coherence with new σ0 |

Display transform unchanged (still μ − 3σ + 250) — honest once σ0 is small.
`seasons.config` JSONB mirrored via `scripts/sync_season_config.py`.

## Result (re-rated 191 matches / 3438 participations on real data)

| metric | before | after |
|---|---|---|
| % CR < 0 | 15.8% (295) | **0%** |
| CR min / median / max | −360 / 233 / 1731 | **530 / 660 / 1518** |
| cr_delta min / max | −572 / +204 | **−77 / +59** |
| cr_delta stddev | 119.6 | **34.1** |
| matches with \|Δ\| > 100 | 1494 (43%) | **0** |

Simulation predicted these within rounding; API leaderboard verified 0 negative CR.

## Reverting

- **Code:** `git revert` this commit, or restore `backend/_rating_backups/2026-06-15_pre-trinity/{params,modifiers,engine,types}.py`.
- **Data:** restore `backend/_rating_backups/2026-06-15_pre-rerate_db.sql` (full
  pre-re-rate `pg_dump`), or just re-run `python -m scripts.rerate_matches --apply`
  after reverting params.

## Deferred (Phase-2, not blocking — see Trinity brief)

- σ still converges slowly (~190 after many games). Irrelevant to the reported
  bugs (0 negatives at every game count) but means the −3σ term is ~constant, so
  CR ≈ μ − const. Real σ-convergence would need lower β or Trinity's R3
  (amplify σ-shrink in the provisional window) — engine surgery, deferred.
- **`delta7d` reads large** (e.g. +827) because the previous backfill stamped
  `played_at = now()`, collapsing every match onto the ingestion window so the
  7-day window covers the whole history. Fixed forward in `arena/riot/arena.py`
  (parse `gameStartTimestamp`) + `scripts/backfill.py` (via `arena/ingest`); existing rows
  keep their compressed timestamps until a fresh backfill.
