# `@crs/shared-types`

Enums, Zod schemas and DTOs shared across CRS reference-implementation
services. Runtime dependency: `zod` only. Per decision D2.4 this package does
**not** import `@crs/rating-engine` — `SeasonConfigSchema` is a parallel Zod
mirror of the engine's `RatingParams`, kept in sync by hand, not by a shared
type import (the two packages are deliberately decoupled).

Like the rest of `packages/`, this is the **reference contract** — the
deployed backend's actual wire contract is the FastAPI/Pydantic schemas in
`backend/arena/schemas/`, which should stay conceptually in sync with the DTOs
here but are not generated from them.

## Layout

- `src/enums.ts` — string-literal enums, each declared once as a `readonly`
  const tuple (the runtime source of truth) and once as a derived union type.
  A compile-time `Equals`/`AssertTrue` guard makes `tsc --noEmit` fail if the
  tuple and the union ever drift apart in either direction — if you add a
  member to one and forget the other, this package won't build.
- `src/schemas.ts` — Zod schemas for shared config shapes (e.g.
  `SeasonConfigSchema`).
- `src/dtos.ts` — Zod schemas (+ inferred TS types) for the core API response
  DTOs, e.g. `PlayerProfileDTOSchema`. Same schema validates at an API boundary
  and types the client — core set only, not a 1:1 mirror of every backend
  route (YAGNI per the original design spec).
- `src/index.ts` — barrel: `export * from './enums.js' | './schemas.js' | './dtos.js'`.

## Commands

```bash
npm run typecheck  -w @crs/shared-types
npm test           -w @crs/shared-types
```

## Adding a new shared enum or DTO

Follow the existing pattern in `enums.ts` (const tuple + derived union +
`AssertTrue<Equals<...>>` guard) rather than a plain TS `enum` — it's what
keeps the runtime array and the compile-time union from silently drifting.
