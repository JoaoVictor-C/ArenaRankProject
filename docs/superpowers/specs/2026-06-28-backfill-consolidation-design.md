# Backfill consolidation & efficiency — design

**Date:** 2026-06-28
**Status:** Approved (design); pending implementation plan
**Author:** pairing session

## Context

The match backfill is implemented twice: `scripts/backfill_real.py` (date-windowed,
chronological, premade-dampener-aware) and `scripts/backfill_matches.py` (snowball BFS).
They are ~90% duplicates — each reimplements the Riot HTTP layer (ad-hoc rate limiter +
`riot_get` retry loop), seed/season resolution, the BFS frontier, player upsert, match
processing through `RatingService`, and summary printing.

Both scripts **bypass the production Riot client** (`arena/riot/client.py` —
`RiotClient` / `build_default_client`), which already provides the full resilience stack
(Redis token-bucket rate limiting, circuit breaker, retry/backoff, request coalescing,
24h match cache, typed errors, regional routing) and exposes exactly the three methods a
crawl needs: `get_account_by_riot_id`, `get_match_ids_by_puuid`, `get_match`. The arq
worker (`workers/ingestion.py`) already uses the client via `workers/deps.get_riot_client`.

**The bug that prompted this:** "isn't getting all matches from all players recursively."
Root cause — with a populated DB (~4000 players), the BFS is seeded with *every* existing
player at depth 0 and the loop hard-stops at `--max-matches` (120 / 400). It exhausts the
budget on seed players and **never reaches depth-1 co-players**, so recursion effectively
never runs for an established ladder. Additionally, `backfill_matches.py` does not paginate
match ids (`start=0,count=100`), capping each player at 100 matches/queue.

**Intended outcome:** one shared, well-bounded crawl library built on `RiotClient`, used by
both a single CLI and the worker; correct chronological replay preserved; the recursion/
completeness bug fixed and covered by tests; and the efficiency levers (cache/coalesce/
cursor + concurrency + DB tuning) applied in one place.

## Goals

- Eliminate both layers of duplication: the two scripts **and** their hand-rolled HTTP stacks.
- One discovery engine (`MatchCrawler`) on top of the existing `RiotClient`.
- Preserve chronological replay correctness for backfill (premade co-occurrence ramp,
  Plackett-Luce ordering, `delta7d`).
- Fix "doesn't recurse / caps out": refresh mode drains the frontier (no hard match cap);
  recursion to depth N is unit-tested.
- Maximum efficiency with balanced defaults and safety bounds.

## Non-goals

- No change to the rating engine, `PremadeIntegrity`, `RatingService`, or the parser
  (`arena/riot/arena.py`).
- No change to `workers/queues.py` constants or the arq queue topology.
- No unrelated refactoring of the worker beyond swapping its discovery step.

## Approach (decisions)

- **B** — shared crawl library on the existing `RiotClient`, used by the CLI and the worker.
- **C (modes)** — one crawler, two modes selectable by flag: `refresh` (all existing
  players) and `bootstrap` (from a `--seed-riot-id`). Shared core; only seed source +
  termination policy differ.
- **A (split)** — discovery is separated from processing. `MatchCrawler` yields parsed
  matches; consumers process them (chronological replay for backfill, streaming for worker).
- **C (efficiency)** — balanced defaults: client 24h cache + coalescing, per-player cursor +
  skip-already-stored, concurrent batches under the token bucket, dedicated caching DB engine,
  `synchronous_commit=off`, bulk upserts. Safety bounds (`max_api_calls`/wall-clock) instead
  of a hard match cap in refresh mode.
- **Redis is now a hard dependency** of the crawl (token bucket + coalescer + match cache).
  Accepted — `arenarank-redis-1` already runs.

## §1 File reorganization

New shared package `arena/ingest/`:

```
arena/ingest/
  __init__.py        # exports MatchCrawler, CrawlConfig, replay_chronological, PlayerRegistry
  crawler.py         # MatchCrawler — BFS discovery over RiotClient; yields parsed matches
  registry.py        # PlayerRegistry — bulk puuid→player_id upsert (on_conflict coalesce)
  replay.py          # replay_chronological — sort by started_at_ms → RatingService
  engine.py          # caching async engine + session factory for scripts (statement_cache-safe)
```

CLI collapses to one thin entry point:

```
scripts/backfill.py          # NEW: ~80-line CLI (argparse → build client → crawl → replay)
scripts/backfill_real.py     # DELETE (logic moves to arena/ingest + replay)
scripts/backfill_matches.py  # DELETE
```

`workers/ingestion.py` is refactored to call `MatchCrawler.discover()` for its discovery
step (streaming consumer). `workers/queues.py`, `arena/riot/arena.py`, `RatingService`,
`PremadeIntegrity` unchanged.

## §2 Components & interfaces

`crawler.py` (discovery only; no rating/DB writes):

```python
@dataclass(frozen=True)
class CrawlConfig:
    region: str = "americas"
    queues: tuple[int, ...] = ARENA_QUEUES        # from arena.riot.arena
    start_epoch: int | None = None                # date window (None = unbounded)
    end_epoch: int | None = None
    depth: int = 3                                 # co-player recursion hops
    max_api_calls: int | None = None              # safety bound (not a match cap)
    max_matches: int | None = None                # optional hard cap (bootstrap)
    batch: int = 40                               # concurrent puuids per round

class MatchCrawler:
    def __init__(self, client: RiotClient, cfg: CrawlConfig, seen_match_ids: set[str]): ...
    async def discover(self, seed_puuids: Iterable[str]) -> AsyncIterator[ParsedArenaMatch]:
        # paginates ids, dedups, fetches+parses concurrently, enqueues co-players ≤ depth;
        # yields each NEW, complete, in-window match exactly once.
```

`registry.py`:

```python
class PlayerRegistry:
    async def bulk_ensure(self, session, matches: Sequence[ParsedArenaMatch]) -> dict[str, str]:
        # one upsert per 1000 (on_conflict do update, COALESCE name/tag/icon), RETURNING id,puuid
```

`replay.py`:

```python
async def replay_chronological(
    session, matches: Sequence[ParsedArenaMatch], *,
    season_id: str, party_store: RedisPartyCooccurrenceStore, id_map: dict[str, str],
) -> ReplayStats:
    # sort by started_at_ms; per-match PremadeIntegrity(ineligible, party_store); RatingService
```

`engine.py`:

```python
def caching_engine_and_factory(database_url: str) -> tuple[AsyncEngine, async_sessionmaker]:
    # statement caching ON (direct PG; ~34× faster than the app's statement_cache_size=0 engine)
```

Seed resolution lives in the CLI: `refresh` → `SELECT puuid FROM players` (optionally only
the new tail via cursor); `bootstrap` → `RiotClient.get_account_by_riot_id(seed)`.

## §3 Data flow & modes

Backfill CLI orchestration:

```
build RiotClient (build_default_client: redis token-bucket + coalesce + 24h cache)
engine, factory = caching_engine_and_factory(DATABASE_URL)   # direct PG, cache on
resolve season_id (ACTIVE, else first)
seen_match_ids ← SELECT riot_match_id FROM matches           # idempotency / resume
seeds ← refresh:  SELECT puuid FROM players (+ optional cursor tail)
        bootstrap: [get_account_by_riot_id(--seed-riot-id)]
matches ← [m async for m in crawler.discover(seeds)]         # DISCOVERY
id_map  ← PlayerRegistry.bulk_ensure(session, matches)
stats   ← replay_chronological(session, matches, season_id, party_store, id_map)
print summary (+ premade-vs-solo effect, top ladder)
```

Worker (`workers/ingestion.py`) consumes the same `crawler.discover()` but **streams**:
each yielded match → cheap filter → enqueue `process_match` to arq (no buffering/replay;
live matches already arrive ~in chronological order).

Termination:
- **refresh** — frontier drains: every existing player's new in-window matches pulled
  (paginated, no hard match cap) + depth-bounded co-players; stops on empty queue or a
  safety bound (`max_api_calls` / wall-clock). This is what makes it exhaustive.
- **bootstrap** — same loop, small seed, `depth` + optional `max_matches` to bound the frontier.

Efficiency in the flow: 18×-shared match payloads collapse via the client coalescer + 24h
cache; `seen_match_ids` + per-player cursor skip stored work; concurrent batches under the
token bucket; replay uses `synchronous_commit=off` + bulk upsert.

## §4 Error handling & testing

Errors: `RiotClient` raises typed errors — `RiotNotFoundError` → skip that puuid/match;
`RiotRateLimitError` / `RiotServerError` → client retries with backoff; `CircuitOpenError`
→ abort cleanly with a clear message. Per-match parse/processing failures are logged and
skipped. Discovery is idempotent (`seen_match_ids` + cursor + `matches` table), so an
aborted run **resumes** on re-run.

Testing (unit, no network):
- `MatchCrawler` against a `FakeRiotClient` (canned id-lists + payloads): asserts dedup,
  pagination past 100, date-window filtering, `is_complete` skipping, and **recursion to
  depth N** — the direct regression test for the original bug.
- `replay_chronological`: synthetic out-of-order matches process in `started_at_ms` order;
  premade ramp fires.
- `PlayerRegistry.bulk_ensure`: re-encounter/upsert idempotency against a test DB.
- Worker streaming: `discover()` yields drive `enqueue_job` calls.

## Risks / notes

- Building on `RiotClient` makes Redis required for backfill (accepted).
- The worker refactor must keep the existing backpressure/pressure-mode and priority
  classification; only the discovery source changes.
- `git` is not initialized in this workspace, so this spec is saved but not committed.
