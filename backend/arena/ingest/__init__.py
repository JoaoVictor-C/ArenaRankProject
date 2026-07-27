"""Offline backfill toolkit — crawl the co-player graph, register players,
replay matches through rating in true chronological order.

This is the machinery behind ``scripts/backfill.py`` (and anything else that
needs to (re)populate history from scratch), not the online discovery path.
Compare with :mod:`arena.workers.ingestion`, which is the arq-facing producer
for the *live* sweep pipeline: it only asks "what's new since I last checked"
for already-tracked players and enqueues one match id at a time. This package
instead does a bounded breadth-first crawl outward from a set of seed
players — through their co-players, and their co-players' co-players, up to
``CrawlConfig.depth`` — fetching full match payloads as it goes, then
replays everything it found through the rating engine in real
``gameStartTimestamp`` order (required: the premade-detection and
Plackett-Luce updates are order-sensitive). Nothing here touches an arq
queue; a caller drives it directly against a session.

Pipeline shape: :class:`~arena.ingest.crawler.MatchCrawler` (discover +
fetch + parse) -> :class:`~arena.ingest.registry.PlayerRegistry` (bulk
puuid -> player_id upsert) -> :func:`~arena.ingest.replay.replay_chronological`
(rate in order). :func:`~arena.ingest.engine.caching_engine_and_factory`
gives the whole pipeline its own direct-to-Postgres engine, tuned for
offline throughput rather than the app's PgBouncer-safe defaults.
"""

from __future__ import annotations

from arena.ingest.crawler import ARENA_QUEUES, CrawlConfig, MatchCrawler, MatchSource
from arena.ingest.engine import caching_engine_and_factory
from arena.ingest.registry import PlayerRegistry
from arena.ingest.replay import ReplayStats, replay_chronological

__all__ = [
    "ARENA_QUEUES", "CrawlConfig", "MatchCrawler", "MatchSource",
    "PlayerRegistry", "replay_chronological", "ReplayStats",
    "caching_engine_and_factory",
]
