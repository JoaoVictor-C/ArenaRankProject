# Repository Guidelines

## Project Structure & Module Organization

`backend/arena/` is the deployed Python FastAPI runtime, organized into API routers, services, database models, Riot integration, rating/integrity engines, and workers. Backend tests live in `backend/tests/`; migrations are in `backend/alembic/`. `frontend/` is the React/Vite user interface, while `admin-console/` is the operator UI. `packages/` contains the TypeScript reference rating engine, Prisma database package, and shared Zod types. Infrastructure definitions live under `infrastructure/`, architecture notes under `docs/`, and `parity/` compares the TypeScript rating oracle with Python. Follow the additional rules in `frontend/AGENTS.md` when editing that subtree.

## Build, Test, and Development Commands

- `docker compose up --build`: start Postgres, Redis, API, workers, and frontend locally.
- `cd backend; uv sync --extra dev; uv run uvicorn arena.api.app:app --reload --port 8000`: install backend dependencies and run the API.
- `cd frontend; npm install; npm run dev`: run the public UI at `http://localhost:5173`.
- `cd frontend; npm run lint; npm run typecheck; npm run build`: perform the required frontend checks.
- `npm install; npm test --workspaces --if-present`: install and test root workspace packages.
- `node parity/compare.mjs`: verify rating-engine parity after rating changes.

## Coding Style & Naming Conventions

Use four-space indentation and `snake_case` for Python; Ruff enforces a 100-character line length, and mypy runs in strict mode. TypeScript is strict: use two-space indentation, `camelCase` for values/functions, and `PascalCase` for React components and types. Keep route-specific React CSS beside its component. User-facing UI copy is PT-BR; identifiers and internal technical prose are English.

## Testing Guidelines

Run backend tests with `cd backend; uv run pytest`; name files `test_*.py`. TypeScript uses Vitest with `*.test.ts` or `*.test.tsx`. The reference rating engine requires 100% line, branch, function, and statement coverage (`npm run test:cov -w @crs/rating-engine`). Add regression tests with behavior changes, and run the parity harness whenever rating math or parameters change.

## Commit & Pull Request Guidelines

Recent history follows Conventional Commits with scopes, such as `feat(leaderboard): ...` and `fix(ingest): ...`. Keep each commit focused and use an imperative summary. Pull requests should explain the behavior and risk, link relevant issues/specs, list validation commands, and include screenshots for UI changes. Call out migrations, environment changes, and parity implications explicitly.

## Security & Configuration Tips

Copy values from `backend/.env.example`, `frontend/.env.example`, or package examples; never commit credentials or Riot keys. Admin mutation routes are not fully authenticated, so do not expose them publicly without an explicit security gate.
