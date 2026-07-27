"""Breadth-first co-player crawl over the Riot API.

``MatchCrawler.discover()`` starts from a set of seed puuids, fetches each
player's recent Arena match ids, fetches+parses the full payload for any id
not already seen, yields the match, and — this is what makes it a *crawl*
rather than a per-player poll — adds every teammate found in that match to
the work queue at ``depth + 1``, up to ``CrawlConfig.depth``. That's how a
handful of seed players (e.g. the site's currently-tracked roster) can
backfill a much larger slice of real history: teammates you've never seen
before still show up because someone you already track played with them.

Safety bounds exist because a wide-enough crawl on a large enough seed set
can otherwise burn an unbounded number of Riot API calls: ``max_api_calls``
trips the internal ``_Budget`` signal (caught in ``discover()``, ends the
crawl cleanly instead of raising out to the caller), and ``max_matches``
caps how many matches are actually yielded regardless of how much further
the frontier could still expand.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from arena.core.logging import get_logger
from arena.riot.arena import ARENA_QUEUE_IDS, NotAnArenaMatch, ParsedArenaMatch, parse_arena_match

#: Every Arena queue id, sorted desc — sourced from the parser so discovery can
#: never drift behind a new queue id.
ARENA_QUEUES: tuple[int, ...] = tuple(sorted(ARENA_QUEUE_IDS, reverse=True))


@runtime_checkable
class MatchSource(Protocol):
    """The minimal Riot surface the crawler needs (real RiotClient satisfies it)."""

    async def get_match_ids_by_puuid(
        self, puuid: str, *, start: int, count: int,
        queue: int | None, start_time: int | None, end_time: int | None,
    ) -> list[str]: ...

    async def get_match(self, match_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CrawlConfig:
    """Tuning knobs for one :meth:`MatchCrawler.discover` run.

    ``depth`` bounds how many co-player hops the crawl follows outward from
    the seed set (0 = only the seeds themselves, no expansion). ``start_epoch``/
    ``end_epoch`` (unix seconds) filter which matches are yielded, not which
    are fetched — a match outside the window is still parsed (needed to find
    its participants) but dropped by ``_in_window``. ``batch`` is how many
    puuids are worked concurrently per BFS layer; ``ids_page``/``ids_max_pages``
    bound the match-id-list pagination per player per queue.
    """

    region: str = "americas"
    queues: tuple[int, ...] = field(default_factory=lambda: ARENA_QUEUES)
    start_epoch: int | None = None
    end_epoch: int | None = None
    depth: int = 3
    max_api_calls: int | None = None
    max_matches: int | None = None
    batch: int = 40
    ids_page: int = 100
    ids_max_pages: int = 20


_log = get_logger("arena.ingest.crawler")


class _Budget(Exception):
    """Internal signal that a safety bound was hit; stops discovery cleanly."""


class MatchCrawler:
    """Drives one breadth-first crawl (see module docstring for the shape).

    ``seen_match_ids`` is an externally-owned set the caller can seed with
    ids already in the DB, so a crawl re-run doesn't re-fetch/re-yield
    history it already has — the crawler only ever adds to it, never reads
    from a fresh empty set on its own.
    """

    def __init__(self, source: MatchSource, cfg: CrawlConfig, seen_match_ids: set[str]) -> None:
        self._src = source
        self._cfg = cfg
        self._seen_matches = seen_match_ids
        self.calls = 0

    async def _ids_for(self, puuid: str) -> list[str]:
        cfg, out = self._cfg, []
        for q in cfg.queues:
            for page in range(cfg.ids_max_pages):
                self._tick()
                got = await self._src.get_match_ids_by_puuid(
                    puuid, start=page * cfg.ids_page, count=cfg.ids_page, queue=q,
                    start_time=cfg.start_epoch, end_time=cfg.end_epoch,
                )
                if not got:
                    break
                out.extend(got)
                if len(got) < cfg.ids_page:
                    break
        return out

    def _tick(self) -> None:
        self.calls += 1
        if self._cfg.max_api_calls is not None and self.calls > self._cfg.max_api_calls:
            raise _Budget

    def _in_window(self, parsed: ParsedArenaMatch) -> bool:
        cfg = self._cfg
        if not parsed.started_at_ms or (cfg.start_epoch is None and cfg.end_epoch is None):
            return True
        ts = parsed.started_at_ms / 1000
        if cfg.start_epoch is not None and ts < cfg.start_epoch:
            return False
        if cfg.end_epoch is not None and ts >= cfg.end_epoch:
            return False
        return True

    async def discover(self, seed_puuids: Iterable[str]) -> AsyncIterator[ParsedArenaMatch]:
        """Yield every new, in-window, complete Arena match reachable from
        ``seed_puuids`` within ``CrawlConfig.depth`` co-player hops.

        ``work`` is a FIFO of ``(puuid, depth)`` pairs — FIFO (not a stack)
        so the crawl processes strictly by depth layer (all of depth 0, then
        all of depth 1, ...) rather than diving arbitrarily deep down one
        branch first. Each layer: page every queued puuid's match-id lists
        concurrently, drop ids already seen (globally, via ``_seen_matches``,
        or within this same layer, via ``local``), fetch+parse only the
        genuinely new ones, yield the eligible ones, and — the actual "crawl"
        step — enqueue each teammate found at ``depth + 1`` if not already
        queued and depth allows it. A hit against ``max_api_calls`` raises
        ``_Budget`` from inside the gathered coroutines; it's re-raised
        first (before any per-item error handling) so the crawl stops
        immediately rather than finishing out a partially-budgeted layer.
        """
        cfg = self._cfg
        work: deque[tuple[str, int]] = deque((pu, 0) for pu in seed_puuids)
        seen_puuids: set[str] = {pu for pu, _ in work}
        produced = 0
        try:
            while work:
                batch = [work.popleft() for _ in range(min(cfg.batch, len(work)))]
                batch = [(pu, d) for pu, d in batch if d <= cfg.depth]
                if not batch:
                    continue
                id_lists_raw = await asyncio.gather(
                    *(self._ids_for(pu) for pu, _ in batch), return_exceptions=True
                )
                # Re-raise _Budget first so the outer except still stops cleanly.
                for res in id_lists_raw:
                    if isinstance(res, _Budget):
                        raise res
                id_lists: list[list[str]] = []
                for (pu, _d), res in zip(batch, id_lists_raw):
                    if isinstance(res, BaseException):
                        _log.warning("ingest.ids_failed", puuid=pu[:8], error=str(res))
                        id_lists.append([])
                    else:
                        id_lists.append(res)
                # Dedup against ids already known (self._seen_matches, shared
                # across the whole crawl) and ids just discovered elsewhere in
                # THIS layer (local) — the same match can surface from more
                # than one participant's id list in a single batch.
                cand: list[tuple[str, int]] = []
                local: set[str] = set()
                for (_pu, d), lst in zip(batch, id_lists):
                    for rid in lst:
                        if rid in self._seen_matches or rid in local:
                            continue
                        local.add(rid)
                        cand.append((rid, d))
                for rid, _ in cand:
                    self._tick()
                payloads = await asyncio.gather(
                    *(self._src.get_match(rid) for rid, _ in cand), return_exceptions=True
                )
                for (rid, d), payload in zip(cand, payloads):
                    if isinstance(payload, BaseException):
                        continue
                    try:
                        parsed = parse_arena_match(payload)
                    except NotAnArenaMatch:
                        continue
                    except Exception as exc:  # noqa: BLE001
                        _log.warning("ingest.parse_failed", match_id=rid, error=str(exc))
                        continue
                    # Mark seen even if it gets filtered below — a match
                    # rejected by is_complete/_in_window is still resolved,
                    # so re-crawling must not re-fetch it every time.
                    self._seen_matches.add(rid)
                    if not parsed.is_complete or not self._in_window(parsed):
                        continue
                    yield parsed
                    produced += 1
                    if cfg.max_matches is not None and produced >= cfg.max_matches:
                        return
                    if d + 1 <= cfg.depth:
                        for st in parsed.subteams:
                            for pp in st.participants:
                                if pp.puuid and pp.puuid not in seen_puuids:
                                    seen_puuids.add(pp.puuid)
                                    work.append((pp.puuid, d + 1))
        except _Budget:
            _log.info("ingest.budget_reached", calls=self.calls, produced=produced)
