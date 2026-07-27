# `@crs/database`

The Prisma schema + client for the Casual Ranked System (CRS) — the
**reference** persistence model, mirrored (not shared at runtime) by the
deployed backend's SQLAlchemy/Alembic schema in `backend/arena/db/` +
`backend/alembic/`. Like `@crs/rating-engine`, this package is **not
deployed** — Production runs the Python/SQLAlchemy side — but it is the
schema-of-record: a schema change should be designed here first, then ported
to the Alembic migrations, the same way rating-math changes land in
`@crs/rating-engine` before the Python port.

## Models (`prisma/schema.prisma`)

`Player` · `Season` · `PlayerSeason` (season-scoped rating state) · `Match` ·
`MatchParticipant` · `ChampionStat` · `IntegrityEvent` · `PlayerAchievement` ·
`CrSnapshot`. Enums: `SeasonStatus`, `RatingMode`, `Severity`,
`RegistrationSource`.

`prisma/sql/001_timescale_views.sql` — raw SQL for the TimescaleDB-specific
pieces (hypertable policies on `cr_snapshots`) that Prisma's schema language
can't express; the Python side applies the equivalent via a plain Alembic
migration (see `backend/alembic/versions/` for the hypertable + continuous
partition setup).

## Client (`src/client.ts`)

A `PrismaClient` singleton cached on `globalThis` in dev (prevents hot-reload
from exhausting the connection pool). `disconnect()` for graceful shutdown.
Re-exports everything from `@prisma/client`.

## Commands

```bash
npm run prisma:generate  -w @crs/database   # regenerate the Prisma client
npm run prisma:validate  -w @crs/database   # validate schema.prisma
npm run typecheck        -w @crs/database
npm test                 -w @crs/database
```

## Keeping the two schemas honest

There is no automated parity gate between this Prisma schema and the
SQLAlchemy models (unlike the rating engine's `parity/` harness) — when you
add/change a model here, make the matching change in `backend/arena/db/models.py`
+ a new Alembic migration by hand, and check `backend/CLAUDE.md` for the
current partitioning/Timescale conventions before writing raw DDL.
