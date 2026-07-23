# Rating-engine parity harness

The rating math lives **twice** — `packages/rating-engine` (TypeScript, the
spec-of-record "oracle" with full coverage) and `backend/arena/rating` (Python,
the deployed runtime, a port of the TS engine). This harness keeps them from
silently diverging.

## What it checks (and what it deliberately doesn't)

`fixtures.json` pins a set of matches **and** a param set that **neutralizes every
gamification modifier**:

- flat placement weights (`[1,1,…]`), `placementAmp = 1.0` + non-provisional players,
- `currentStreak = 0` (streak multiplier = 1.0),
- soft cap unreachable (`crBefore ≪ softCapThreshold`),
- dispersion cap effectively off (`maxDeltaMu = 1e6`),
- the Python-only **PDL cap layer OFF** (`caps = None`).

With modifiers neutralized, both engines reduce to the **same base Weng-Lin
Plackett-Luce update** plus the conservative display `CR = (μ − 3σ)·scale +
offset`. That core is what the gate enforces (per-player `crDelta`, `crAfter`,
`muAfter`, `sigmaAfter` within `tolerance`, default `1e-6`).

> **Not covered:** full-pipeline parity. The two engines ship **different default
> params** (the Python engine was recalibrated 2026-06-15) and the Python side
> adds the PDL caps layer the TS engine lacks. Reconciling those — or formally
> declaring the TS engine "reference only" — is tracked as a separate decision
> (see the repo's P1 "role of `packages/`" task). Extend `fixtures.json` with
> modifier-exercising cases once that reconciliation lands.

## Run it

```bash
# prerequisites
npm install                 # repo root — installs tsx + the workspace packages
pip install ./backend       # makes arena.rating importable

node parity/compare.mjs     # exits non-zero on divergence
# tune the gate:  PARITY_TOL=1e-9 node parity/compare.mjs
```

`compare.mjs` spawns `run_py.py` (Python runtime) and `run_ts.mts` (TS oracle via
`tsx`), captures their JSON, and diffs. In CI this is the `parity` job of
`.github/workflows/quality.yml`.

## Files

| File | Role |
|---|---|
| `fixtures.json` | shared matches + neutralized params + tolerance |
| `run_py.py` | runs `arena.rating.rate`, prints per-player JSON |
| `run_ts.mts` | runs `@crs/rating-engine` `rate`, prints per-player JSON |
| `compare.mjs` | orchestrates both + diffs + sets the exit code |

> **Draft note:** this harness has not yet had its first green run committed —
> the first CI execution may need a tolerance tweak (the Python `openskill` lib
> and the TS hand-port can differ in the last few float ULPs). Treat a small,
> stable `worstΔ` as the real floor and set `tolerance` just above it.
