"""Unified Arena backfill CLI.

  refresh   — pull every existing player's new in-window matches + depth-bounded
              co-players (no hard match cap; frontier drains).
  bootstrap — grow a ladder from a single --seed-riot-id (depth + --max-matches).

Run (cwd backend, RIOT_API_KEY + DATABASE_URL set; Redis up):
  python -m scripts.backfill --mode refresh --start-date 2026-04-01 --end-date 2026-05-01
  python -m scripts.backfill --mode bootstrap --seed-riot-id "Presente#1001" --depth 3 --max-matches 400
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select

from arena.core.config import settings
from arena.db import models as m
from arena.ingest import (
    CrawlConfig, MatchCrawler, PlayerRegistry, caching_engine_and_factory, replay_chronological,
)
from arena.integrity.fingerprint import RedisPartyCooccurrenceStore
from arena.riot.client import build_default_client
from arena.riot.routing import Region
from arena.services.match_pipeline import PremadeIntegrity
from arena.services.rating_service import RatingService


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="backfill")
    ap.add_argument("--mode", choices=("refresh", "bootstrap"), default="refresh")
    ap.add_argument("--seed-riot-id", default="", help='bootstrap account "Name#Tag"')
    ap.add_argument("--region", default="americas")
    ap.add_argument("--start-date", default="")
    ap.add_argument("--end-date", default="")
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--max-matches", type=int, default=None)   # bootstrap cap; None in refresh
    ap.add_argument("--max-api-calls", type=int, default=None)  # opt-in safety bound
    return ap.parse_args(argv)


def _epoch(date_str: str) -> int | None:
    if not date_str:
        return None
    return int(datetime.fromisoformat(date_str).replace(tzinfo=UTC).timestamp())


async def resolve_seeds(session, source, *, mode: str, seed_riot_id: str, region: str) -> list[str]:
    if mode == "bootstrap":
        name, _, tag = seed_riot_id.partition("#")
        acct = await source.get_account_by_riot_id(name, tag, region=Region(region))
        return [acct["puuid"]] if acct and acct.get("puuid") else []
    rows = (await session.execute(select(m.Player.puuid))).scalars().all()
    return list(rows)


async def run(args: argparse.Namespace) -> None:
    key = settings.riot_api_key
    if not key:
        print("RIOT_API_KEY empty")
        return
    redis = Redis.from_url(settings.redis_url)
    engine, factory = caching_engine_and_factory(settings.database_url)
    party_store = RedisPartyCooccurrenceStore(redis)
    client = build_default_client(key, redis=redis, default_region=Region(args.region))
    try:
        async with factory() as s0:
            season = (await s0.execute(
                select(m.Season).where(m.Season.status == m.SeasonStatus.ACTIVE).limit(1)
            )).scalar_one_or_none() or (await s0.execute(select(m.Season).limit(1))).scalar_one()
            season_id = str(season.id)
            seen = set((await s0.execute(select(m.Match.riot_match_id))).scalars().all())
            async with client:
                seeds = await resolve_seeds(
                    s0, client, mode=args.mode, seed_riot_id=args.seed_riot_id, region=args.region,
                )
                if not seeds:
                    print("no seeds resolved")
                    return
                cfg = CrawlConfig(
                    region=args.region, start_epoch=_epoch(args.start_date),
                    end_epoch=_epoch(args.end_date), depth=args.depth,
                    max_matches=args.max_matches, max_api_calls=args.max_api_calls,
                )
                crawler = MatchCrawler(client, cfg, seen_match_ids=seen)
                print(f"mode={args.mode} seeds={len(seeds)} depth={args.depth} season={season_id}")
                matches = [parsed async for parsed in crawler.discover(seeds)]
                print(f"discovered {len(matches)} matches ({crawler.calls} api calls)")
        async with factory() as s:
            # Re-dedup against the DB *after* discovery: rows may have appeared
            # during the (long) crawl — concurrent workers or a manual restore —
            # and the pre-crawl ``seen`` snapshot would let replay INSERTs collide.
            seen_now = set((await s.execute(select(m.Match.riot_match_id))).scalars().all())
            skipped = len(matches)
            matches = [pm for pm in matches if pm.match_id not in seen_now]
            skipped -= len(matches)
            print(f"dedup vs DB: {skipped} already present, {len(matches)} to replay")
            id_map = await PlayerRegistry().bulk_ensure(s, matches)
            await s.commit()
            svc = RatingService(PremadeIntegrity(set(), party_store))
            stats = await replay_chronological(
                s, matches, season_id=season_id, party_store=party_store,
                id_map=id_map, rating_service=svc,
            )
            print(f"DONE processed={stats.processed} players={len(id_map)}")
    finally:
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
