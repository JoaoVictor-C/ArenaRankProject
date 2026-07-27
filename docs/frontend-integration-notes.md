# Frontend ↔ Backend Integration Notes (for Wire phase + final E2E)

> **Historical, pre-implementation.** Written while the FastAPI backend and the
> tournaments admin surface were still being built — treat "NOT wired" claims
> below as a snapshot of that moment, not current state (the admin-console
> Campeonatos page now exercises the tournament-admin endpoints this doc
> planned for). It also references `tournament_onboarding_scoring_v1.md`,
> which isn't in this repo — `arena/tournaments/scoring.py` is the current
> source of truth for standings computation. Kept for the still-useful
> endpoint/shape mapping below, not as a live status doc.

Audit of the existing `frontend/` (React+Vite) against the API the FastAPI backend is building.
Source of truth for shapes: `frontend/src/lib/types.ts` ↔ `backend/arena/schemas/`.

## Endpoints the frontend ACTUALLY calls (`frontend/src/lib/api.ts`)

E2E-critical — these must return correct shapes for the app to work:

| Method | Endpoint | Frontend route(s) | Notes |
|---|---|---|---|
| GET | `/leaderboard?format&scope&season&limit&offset` | Leaderboard | rows[] with rank/cr/delta7d/tier/tags/champions |
| GET | `/player/{riotId}` | Perfil | full PlayerProfile (matches/champions/h2h/seasons/crHistory) |
| GET | `/match/{matchId}` | Partida | MatchDetail.subteams[] (3v3=6×3 placement 1..6) |
| GET | `/champions?format&metric&patch&region` | Winrate | ChampTierlistResponse (DTO sample OK) |
| GET | `/meta/last-update?rank` | (header/meta) | LastUpdate global+tier cadence |
| GET | `/tournaments` | Campeonatos2, Admin | TournamentListItem[] |
| GET | `/tournament/{id}` | Campeonatos | full TournamentDetail; fallback sample `t001`/`t002` when empty |
| POST | `/admin/tournaments` | Admin → SectionTournaments | body TournamentCreate → 201 TournamentDetail (incl. accessKey) |
| GET | `/admin/overview` | Admin | AdminOverview (metrics/workers/queues/integrity/dlq/season/riotApi) |

## Endpoints in the contract but NOT wired in the frontend (build for completeness, not E2E-critical)

`POST /tournament/{id}/access`, `/team`, `/join`, `POST /admin/tournament/{id}/match/{n}/link`, `/result`.
The Campeonatos lobby ("Entrar no saguão", trickle fill) is **pure client-side simulation** — no API call.
Build them per contract §5 (the backend tournaments agent does), but the demo path does not exercise them.

## Gotchas the build agents must honor

- **camelCase** JSON keys on every response (contract requirement; Pydantic `alias_generator=to_camel` + `populate_by_name`).
- **`/admin/overview`** metric `key` values must match what Admin.tsx maps to icons: `crs_matches_processed_total`, `crs_queue_depth`, `crs_worker_active_count`, `crs_processing_duration_seconds`, `crs_leaderboard_update_latency`, plus a `5xx rate` entry. `season.config` is `Record<string,string>` (Admin renders k/v; empty → frontend shows design fallback). `workers[].status ∈ ok|warn|down`, `riotApi[].status ∈ ok|warn`, `integrity[]`/`flags[].severity ∈ info|warn|critical`, `dlq[].attempts:number`.
- **Tournament provisioning** (`POST /admin/tournaments`): generate full `TournamentDetail` — status `upcoming`, all matches `upcoming` (lobbyCount 0), standings zeroed, registrations with `{empty:true}` player slots, `accessKey` `ARENA-XXXXXX`, scoring default `place→points = numTeams..1` when omitted. `prizeLabel` + `currency` ("BRL"|"RP") drive display.
- **`compute_standings`** (scoring source of truth, `tournament_onboarding_scoring_v1.md`): `perMatch` only for ended matches; `bravura` is the per-match score; total = sum(perMatch)+bonus−penalties; tiebreaks per `rules.tiebreak`.
- **CR**: `cr` field = our gamified `to_cr(mu,sigma)`. Never expose `mu`/`sigma` or augment/item winrate (Riot ToS). Pick rate OK.
- **Errors**: `404 {detail}` for missing player/match/tournament (frontend renders an empty state); `422` validation; `403`/`409` for the onboarding endpoints.
- **CORS**: allow `http://localhost:5173` (Vite dev). Frontend `VITE_API_URL` → `http://localhost:8000`, calls go to `${BASE}/api/v1...`.

## Final E2E smoke (deferred test phase) — minimal happy path

1. `docker compose up` (pg/timescale + redis + api + workers + frontend).
2. seed dev season + a couple tracked players + one processed match fixture.
3. Hit each E2E-critical GET → assert 200 + shape; provision a tournament via POST `/admin/tournaments` → open it on `/campeonatos2/{id}`.
4. Load the frontend, click through Leaderboard → Perfil → Partida → Campeonatos → Admin with no console errors.
