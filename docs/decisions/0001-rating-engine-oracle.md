# ADR 0001 — `@crs/rating-engine` is the rating oracle (spec-of-record)

**Status:** Accepted (2026-06-21)

## Context

The CRS rating math exists **twice**: `packages/rating-engine` (TypeScript —
pure, deterministic, 100% test coverage, asserts parity with `openskill` to 1e-9)
and `backend/arena/rating` (Python — the deployed runtime, a hand-port of the TS
engine). The schema and contract types are likewise duplicated (Prisma vs
SQLAlchemy/Alembic; Zod vs Pydantic; and a hand-mirrored `frontend/src/lib/types.ts`).

Nothing in production consumes `packages/`, so the two rating engines could drift
with nothing catching it. We had to decide whether `packages/` is **legacy to be
archived** or the **authoritative reference**.

## Decision

`@crs/rating-engine` (TypeScript) is the **enforced oracle / spec-of-record** for
the rating algorithm. `packages/` is **not** archived.

- Any change to rating math lands in the **TS engine first** (with its
  property / oracle / simulation tests), then is ported to `backend/arena/rating`.
- The **parity gate** (`parity/`, the `parity` job in `.github/workflows/quality.yml`)
  is the enforcement mechanism: it runs identical fixtures through both engines and
  fails CI if the base Weng-Lin Plackett-Luce update + the conservative CR identity
  (`CR = (μ − 3σ)·scale + offset`) diverge beyond tolerance. **Configure it as a
  required status check** on the default branch.
- Deliberate runtime deltas — the 2026-06-15 recalibrated default params and the
  Python-only PDL cap layer — are **configuration / product choices, not engine
  divergence**. The parity gate neutralizes the gamification modifiers so it
  compares the shared core math, which must always match.

## Consequences

- The dual implementation becomes an asset (an executable spec + a verified port)
  instead of a silent-divergence liability.
- `packages/*` runs in CI (the `packages` job); its tests are not optional.
- **Follow-up (types SSOT):** the frontend should consume `@crs/shared-types`
  instead of the hand-mirrored `frontend/src/lib/types.ts`, making the TS package
  the single source of truth for DTOs too. This is gated on reconciling the API
  contract (`api_contract_v1.md`, currently off-repo) into `docs/` — see the
  repo-to-truth task.
