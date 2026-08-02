"""One-time historical backfill: augments/items + combat telemetry for
already-ingested matches.

Every match ingested before native participant capture existed (augments/items:
``arena/riot/arena.py``, migration ``0018_participant_picks``; combat telemetry:
same file, migration ``0021_participant_combat_stats``) has NULL on the relevant
``match_participants`` columns — the fields were simply never parsed out of the
raw payload, and we don't keep raw payloads long-term (the whole point of the
parse is a closed, fixed field set, not a 75KB blob per match). This script
re-fetches each such match from Riot (read-only; no rating/persistence side
effects beyond these columns) and fills them all in — one re-fetch per match
covers both categories, since they come from the same payload.

Idempotent/resumable: each pass selects matches still missing capture (using
``kills IS NULL`` as the marker — the newest column, so it also covers rows
that already have augments/items from an earlier run of this script), so a
killed run picks up where it left off. Safe to run alongside live ingestion
(shares the same Riot rate-limit budget via the same Redis token bucket) —
though it'll go faster with live ingestion paused, since it no longer has to
share.

Matches are fetched CONCURRENTLY (bounded by ``--concurrency``), not one at a
time: the rate limiter (a Redis token bucket, the same one live ingestion
uses — see ``arena/riot/rate_limit.py``) already serializes the actual Riot
calls to the real limit regardless of how many callers ask at once, same as
StandardWorker/PriorityWorker processing "10-20 in parallel" during normal
ingestion (root CLAUDE.md). Running one match at a time left almost all of
that budget unused — latency-bound, not rate-bound.

A permanent Riot failure (404 — the match is genuinely gone upstream) writes
zeroed-out fields rather than leaving NULL, so the run converges instead of
retrying it forever; a transient failure (rate limit, 5xx, circuit open, DB
blip) is skipped for the REST of this run (still NULL — the next run retries
it fresh) rather than spinning on the same stuck match.

After this completes, either wait for the hourly ``champion_build_stats_maintenance``
cron or trigger ``StatsService.rebuild_champion_build_stats`` manually to fold
any newly captured augment/item history into the rollup (combat telemetry has
no rollup — per-match display only).

Run (cwd backend, RIOT_API_KEY + DATABASE_URL set; Redis up):
    python -m scripts.backfill_participant_telemetry
    python -m scripts.backfill_participant_telemetry --batch-size 500 --concurrency 30
    python -m scripts.backfill_participant_telemetry --max-matches 1000   # a bounded test run
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from arena.core.config import settings
from arena.db import models as m
from arena.ingest.engine import caching_engine_and_factory
from arena.riot.arena import ParsedParticipant, parse_arena_match
from arena.riot.client import RiotClient, build_default_client
from arena.riot.errors import RiotNotFoundError
from arena.riot.routing import Region
from arena.workers.bootstrap import seed_region

#: Riot match-v5 is REGIONAL routing (americas/europe/asia), not platform
#: (br1/na1/...) — every BR match resolves through the same regional cluster
#: regardless of which specific match it is, so one default for the whole
#: backfill is correct (matches the rest of this BR-only product).
_DEFAULT_BATCH_SIZE = 200

#: In-flight matches at once. The rate limiter is the real gate (a shared
#: Redis token bucket — see module docstring); this just has to be high enough
#: to keep it fed. Slightly above the default SQLAlchemy pool (pool_size=5 +
#: max_overflow=10 = 15) is fine — a few tasks briefly queue for a DB
#: connection during their short write; the Riot round-trip dominates, not
#: the write, so that queueing is not the bottleneck.
_DEFAULT_CONCURRENCY = 20

#: match_participants columns this script fills in, in the exact order the
#: UPDATE below binds them — augments/items plus every combat-telemetry column
#: from migration 0021.
_COMBAT_COLUMNS = (
    "kills",
    "deaths",
    "assists",
    "damage_to_champions",
    "gold_earned",
    "champion_level",
    "damage_taken",
    "total_heal",
    "damage_self_mitigated",
    "largest_multi_kill",
    "killing_sprees",
    "time_spent_dead",
)


async def _pending_matches(
    factory: async_sessionmaker[AsyncSession], *, batch_size: int, exclude: set[uuid.UUID]
) -> list[tuple[uuid.UUID, str]]:
    """Up to ``batch_size`` (matches.id, riot_match_id) still missing capture."""
    async with factory() as session:
        stmt = (
            select(m.Match.id, m.Match.riot_match_id)
            .join(m.MatchParticipant, m.MatchParticipant.match_id == m.Match.id)
            .where(m.MatchParticipant.kills.is_(None))
            .distinct()
            .limit(batch_size)
        )
        if exclude:
            stmt = stmt.where(m.Match.id.notin_(exclude))
        rows = (await session.execute(stmt)).all()
        return [(row.id, row.riot_match_id) for row in rows]


async def _apply(
    factory: async_sessionmaker[AsyncSession],
    *,
    match_id: uuid.UUID,
    by_puuid: dict[str, ParsedParticipant],
) -> int:
    """UPDATE every participant of one match with its parsed picks + combat
    telemetry (empty/zeroed for a puuid the payload didn't carry — malformed/
    partial data)."""
    async with factory() as session:
        rows = (
            await session.execute(
                select(m.MatchParticipant.id, m.Player.puuid)
                .join(m.Player, m.Player.id == m.MatchParticipant.player_id)
                .where(m.MatchParticipant.match_id == match_id)
            )
        ).all()
        for row in rows:
            pp = by_puuid.get(row.puuid)
            params: dict[str, object] = {
                "a": pp.augments if pp is not None else [],
                "i": pp.items if pp is not None else [],
                "pid": row.id,
                "mid": match_id,
            }
            for col in _COMBAT_COLUMNS:
                params[col] = getattr(pp, col) if pp is not None else 0
            set_clause = ", ".join(f"{col} = :{col}" for col in _COMBAT_COLUMNS)
            await session.execute(
                text(
                    f"UPDATE match_participants SET augments = :a, items = :i, {set_clause} "
                    "WHERE id = :pid AND match_id = :mid"
                ),
                params,
            )
        await session.commit()
        return len(rows)


async def _backfill_one(
    factory: async_sessionmaker[AsyncSession],
    client: RiotClient,
    *,
    match_id: uuid.UUID,
    riot_match_id: str,
    region: Region,
) -> str:
    """Returns ``"ok"``, ``"empty"`` (permanent 404, marked done) or ``"skip"``
    (transient failure — left NULL for the next run)."""
    try:
        payload = await client.get_match(riot_match_id, region=region)
        parsed = parse_arena_match(payload)
    except RiotNotFoundError:
        try:
            await _apply(factory, match_id=match_id, by_puuid={})
        except Exception as exc:  # noqa: BLE001 — a DB blip must not crash the run either
            print(f"  {riot_match_id}: 404 upstream, but DB write failed — skipped this run ({exc})")
            return "skip"
        print(f"  {riot_match_id}: 404 upstream — marked empty (won't retry)")
        return "empty"
    except Exception as exc:  # noqa: BLE001 — any failure here must not crash the run
        print(f"  {riot_match_id}: skipped this run ({exc})")
        return "skip"

    by_puuid = {p.puuid: p for t in parsed.subteams for p in t.participants}
    try:
        n = await _apply(factory, match_id=match_id, by_puuid=by_puuid)
    except Exception as exc:  # noqa: BLE001 — a DB blip must not crash the run either
        print(f"  {riot_match_id}: fetched OK, but DB write failed — skipped this run ({exc})")
        return "skip"
    return "ok" if n > 0 else "empty"


async def _run_batch(
    factory: async_sessionmaker[AsyncSession],
    client: RiotClient,
    batch: list[tuple[uuid.UUID, str]],
    *,
    region: Region,
    semaphore: asyncio.Semaphore,
    counts: dict[str, int],
    skip_ids: set[uuid.UUID],
) -> None:
    """Process one batch with up to ``semaphore``'s value in flight at once.

    The Riot call inside :func:`_backfill_one` is the slow, shared-budget part
    (gated by the rate limiter regardless of how many callers ask); the
    semaphore just caps how many of THIS script's tasks may be mid-flight,
    so a batch of 200 doesn't fire 200 requests simultaneously.
    """

    async def _one(match_id: uuid.UUID, riot_match_id: str) -> None:
        async with semaphore:
            outcome = await _backfill_one(
                factory, client, match_id=match_id, riot_match_id=riot_match_id, region=region
            )
        counts[outcome] += 1
        if outcome == "skip":
            skip_ids.add(match_id)
        total = sum(counts.values())
        if total % 50 == 0:
            print(f"  {total} processed: {counts}")

    await asyncio.gather(*(_one(mid, rid) for mid, rid in batch))


async def main() -> None:
    ap = argparse.ArgumentParser(
        description="Backfill augments/items + combat telemetry for already-ingested matches."
    )
    ap.add_argument("--batch-size", type=int, default=_DEFAULT_BATCH_SIZE)
    ap.add_argument("--concurrency", type=int, default=_DEFAULT_CONCURRENCY)
    ap.add_argument(
        "--max-matches", type=int, default=None, help="stop after this many (default: all)"
    )
    args = ap.parse_args()

    key = settings.riot_api_key
    if not key:
        print("RIOT_API_KEY empty")
        return

    redis = Redis.from_url(settings.redis_url)
    engine, factory = caching_engine_and_factory(settings.database_url)
    region = seed_region()
    client = build_default_client(key, redis=redis, default_region=region)
    semaphore = asyncio.Semaphore(args.concurrency)

    counts = {"ok": 0, "empty": 0, "skip": 0}
    skip_ids: set[uuid.UUID] = set()
    try:
        async with client:
            while args.max_matches is None or sum(counts.values()) < args.max_matches:
                batch = await _pending_matches(
                    factory, batch_size=args.batch_size, exclude=skip_ids
                )
                if not batch:
                    print("no more matches pending — done")
                    break
                if args.max_matches is not None:
                    remaining = args.max_matches - sum(counts.values())
                    batch = batch[:remaining]
                await _run_batch(
                    factory, client, batch, region=region, semaphore=semaphore,
                    counts=counts, skip_ids=skip_ids,
                )
    finally:
        await redis.aclose()
        await engine.dispose()
    print(f"DONE {counts}")


if __name__ == "__main__":
    asyncio.run(main())
