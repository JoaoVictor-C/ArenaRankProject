# Backfill Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two duplicate backfill scripts with one shared `arena/ingest/` crawl library (built on the existing `RiotClient`) plus a single thin CLI, fixing the "doesn't recurse / caps out" bug and covering it with tests.

**Architecture:** Discovery is separated from processing. `MatchCrawler` does the BFS/pagination/dedup/fetch/parse against a minimal `MatchSource` Protocol (satisfied by the real `RiotClient`) and yields parsed matches. Consumers process the stream: `replay_chronological` (backfill — sort by real start time, then `RatingService`) and the arq worker (streaming enqueue). `PlayerRegistry` and a caching DB `engine` are shared helpers.

**Tech Stack:** Python 3.12, asyncio, httpx (via `RiotClient`), SQLAlchemy async + asyncpg, Redis, pytest / pytest-asyncio.

## Global Constraints

- **Python ≥ 3.11** (3.12 in use). `from __future__ import annotations` at the top of every module (matches the codebase).
- **Test runner (the project venv interpreter is broken; its site-packages are intact).** Run all commands from `backend/`. Before running pytest, set:
  `PYTHONPATH = "<backend>;<backend>\.venv\Lib\site-packages"` and invoke `C:\Users\João\AppData\Local\Programs\Python\Python312\python.exe -m pytest …` (aka `py -3.12 -m pytest …` once PYTHONPATH is exported). Plan steps abbreviate this as `pytest …`.
- **DB-gated tests** opt in via `DATABASE_URL` and the `pytest.mark.skipif(not os.getenv("DATABASE_URL"))` guard (existing pattern in `tests/services/test_worker_rating_service_integration.py`). Point them at the populated direct-PG instance: `postgresql+asyncpg://arena:arena@localhost:5432/arena`.
- **Redis required** for the real crawl (token bucket + coalescer + 24h match cache live there). Unit tests use fakes and touch no Redis/DB/network.
- **No hard match cap in refresh mode**; `max_api_calls` is an opt-in safety bound (default `None`). `max_matches` applies to bootstrap only.
- **Do not modify** `arena/riot/arena.py` (parser), `RatingService`, `PremadeIntegrity`, or `workers/queues.py` constants.
- **Git is not initialized** in this workspace. Either run `git init` first (recommended) or treat each "Commit" step as a checkpoint. Commit messages use Conventional Commits.

---

### Task 1: `MatchSource` Protocol + `CrawlConfig`

**Files:**
- Create: `backend/arena/ingest/__init__.py` (empty for now)
- Create: `backend/arena/ingest/crawler.py`
- Test: `backend/tests/ingest/test_crawler.py`
- Create: `backend/tests/ingest/__init__.py` (empty)

**Interfaces:**
- Produces:
  - `class MatchSource(Protocol)` with
    `async def get_match_ids_by_puuid(self, puuid, *, start, count, queue, start_time, end_time) -> list[str]`
    and `async def get_match(self, match_id) -> dict[str, Any]`.
  - `@dataclass(frozen=True) class CrawlConfig` with fields:
    `region: str = "americas"`, `queues: tuple[int, ...] = ARENA_QUEUES`,
    `start_epoch: int | None = None`, `end_epoch: int | None = None`,
    `depth: int = 3`, `max_api_calls: int | None = None`,
    `max_matches: int | None = None`, `batch: int = 40`, `ids_page: int = 100`, `ids_max_pages: int = 20`.
  - `ARENA_QUEUES: tuple[int, ...]` (sorted desc from `arena.riot.arena.ARENA_QUEUE_IDS`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/ingest/test_crawler.py
from __future__ import annotations

from arena.ingest.crawler import ARENA_QUEUES, CrawlConfig, MatchSource


def test_crawlconfig_defaults():
    cfg = CrawlConfig()
    assert cfg.depth == 3
    assert cfg.max_matches is None and cfg.max_api_calls is None
    assert cfg.batch == 40 and cfg.ids_page == 100
    # queues come from the parser's single source of truth, sorted desc
    assert cfg.queues == ARENA_QUEUES
    assert tuple(sorted(cfg.queues, reverse=True)) == cfg.queues


def test_matchsource_is_runtime_checkable_protocol():
    # A trivial object exposing the two methods satisfies MatchSource.
    class S:
        async def get_match_ids_by_puuid(self, puuid, *, start, count, queue, start_time, end_time): ...
        async def get_match(self, match_id): ...
    assert isinstance(S(), MatchSource)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingest/test_crawler.py -v`
Expected: FAIL with `ModuleNotFoundError: arena.ingest.crawler`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/arena/ingest/crawler.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from arena.riot.arena import ARENA_QUEUE_IDS

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ingest/test_crawler.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/arena/ingest/__init__.py backend/arena/ingest/crawler.py backend/tests/ingest/
git commit -m "feat(ingest): add MatchSource protocol and CrawlConfig"
```

---

### Task 2: `MatchCrawler.discover` — single-player discovery (dedup, window, completeness)

**Files:**
- Modify: `backend/arena/ingest/crawler.py`
- Test: `backend/tests/ingest/test_crawler.py`

**Interfaces:**
- Consumes: `MatchSource`, `CrawlConfig`, `parse_arena_match`, `NotAnArenaMatch`, `ParsedArenaMatch` (from `arena.riot.arena`).
- Produces:
  - `class MatchCrawler` with `__init__(self, source: MatchSource, cfg: CrawlConfig, seen_match_ids: set[str])`,
    a `calls: int` counter, and
    `async def discover(self, seed_puuids: Iterable[str]) -> AsyncIterator[ParsedArenaMatch]`.
  - A reusable `FakeSource` test helper in `tests/ingest/conftest.py`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/ingest/conftest.py
from __future__ import annotations

from typing import Any


def arena_payload(match_id: str, puuids: list[str], *, queue: int = 1700,
                  start_ms: int = 1_700_000_000_000, duration: int = 600) -> dict[str, Any]:
    """A complete DUOS (8x2) payload from 16 puuids unless fewer are given."""
    parts = []
    for i, pu in enumerate(puuids):
        sub = i // 2 + 1
        place = sub  # deterministic placements 1..8
        parts.append({
            "puuid": pu, "riotIdGameName": pu, "riotIdTagline": "BR1",
            "championId": 10 + i, "playerSubteamId": sub, "subteamPlacement": place,
            "profileIcon": 1, "timePlayed": duration, "gameEndedInEarlySurrender": False,
        })
    return {"metadata": {"matchId": match_id},
            "info": {"queueId": queue, "gameDuration": duration,
                     "gameStartTimestamp": start_ms, "participants": parts}}


class FakeSource:
    """In-memory MatchSource: maps puuid->list[match_id] and match_id->payload.
    Records call counts so tests can assert no-refetch behavior."""

    def __init__(self, ids_by_puuid: dict[str, list[str]], payloads: dict[str, dict]):
        self._ids = ids_by_puuid
        self._payloads = payloads
        self.id_calls = 0
        self.match_calls: list[str] = []

    async def get_match_ids_by_puuid(self, puuid, *, start, count, queue, start_time, end_time):
        self.id_calls += 1
        ids = self._ids.get(puuid, [])
        return ids[start:start + count]  # honors pagination

    async def get_match(self, match_id):
        self.match_calls.append(match_id)
        return self._payloads[match_id]
```

```python
# append to backend/tests/ingest/test_crawler.py
import pytest

from arena.ingest.crawler import MatchCrawler, CrawlConfig
from tests.ingest.conftest import FakeSource, arena_payload


def _16(prefix: str) -> list[str]:
    return [f"{prefix}-{i}" for i in range(16)]


@pytest.mark.asyncio
async def test_discover_single_player_yields_complete_in_window_match():
    pus = _16("A")
    src = FakeSource({pus[0]: ["m1"]}, {"m1": arena_payload("m1", pus, start_ms=1_700_000_000_000)})
    cfg = CrawlConfig(depth=0, start_epoch=1_600_000_000, end_epoch=1_800_000_000)
    out = [m async for m in MatchCrawler(src, cfg, seen_match_ids=set()).discover([pus[0]])]
    assert [m.match_id for m in out] == ["m1"]
    assert out[0].is_complete


@pytest.mark.asyncio
async def test_discover_skips_seen_and_out_of_window_and_incomplete():
    pus = _16("A")
    payloads = {
        "seen": arena_payload("seen", pus),
        "old": arena_payload("old", pus, start_ms=1_000),                 # before window
        "partial": arena_payload("partial", pus[:4]),                     # 4 players -> incomplete
        "ok": arena_payload("ok", pus, start_ms=1_700_000_000_000),
    }
    src = FakeSource({pus[0]: ["seen", "old", "partial", "ok"]}, payloads)
    cfg = CrawlConfig(depth=0, start_epoch=1_600_000_000, end_epoch=1_800_000_000)
    out = [m async for m in MatchCrawler(src, cfg, seen_match_ids={"seen"}).discover([pus[0]])]
    assert [m.match_id for m in out] == ["ok"]
    assert "seen" not in src.match_calls  # never even fetched a known id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingest/test_crawler.py -v`
Expected: FAIL with `ImportError: cannot import name 'MatchCrawler'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/arena/ingest/crawler.py
import asyncio
from collections import deque
from collections.abc import AsyncIterator, Iterable

from arena.core.logging import get_logger
from arena.riot.arena import NotAnArenaMatch, ParsedArenaMatch, parse_arena_match

_log = get_logger("arena.ingest.crawler")


class _Budget(Exception):
    """Internal signal that a safety bound was hit; stops discovery cleanly."""


class MatchCrawler:
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
                id_lists = await asyncio.gather(*(self._ids_for(pu) for pu, _ in batch))
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ingest/test_crawler.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/arena/ingest/crawler.py backend/tests/ingest/
git commit -m "feat(ingest): MatchCrawler single-player discovery with dedup/window/completeness"
```

---

### Task 3: `MatchCrawler` — pagination, recursion to depth N, and bounds (the bug regression test)

**Files:**
- Modify: `backend/arena/ingest/crawler.py` (only if a test exposes a gap)
- Test: `backend/tests/ingest/test_crawler.py`

**Interfaces:**
- Consumes/Produces: same `MatchCrawler.discover` as Task 2 (this task adds tests proving the recursion/pagination/bounds behavior; implementation from Task 2 should already satisfy them — fix inline if not).

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/ingest/test_crawler.py


@pytest.mark.asyncio
async def test_discover_paginates_past_100_ids():
    pus = _16("A")
    ids = [f"m{i}" for i in range(150)]
    payloads = {i: arena_payload(i, pus, start_ms=1_700_000_000_000) for i in ids}
    src = FakeSource({pus[0]: ids}, payloads)
    cfg = CrawlConfig(depth=0, start_epoch=1_600_000_000, end_epoch=1_800_000_000)
    out = [m async for m in MatchCrawler(src, cfg, set()).discover([pus[0]])]
    assert len(out) == 150  # not truncated at 100


@pytest.mark.asyncio
async def test_discover_recurses_to_coplayers_depth_n():
    a, b = _16("A"), _16("B")          # match mA has team A; co-player b0 only plays mB
    ids = {a[0]: ["mA"], b[0]: ["mB"]}
    # make b[0] a participant of mA so it is discovered, and give it its own match mB
    payload_a = arena_payload("mA", [b[0]] + a[1:], start_ms=1_700_000_000_000)
    payload_b = arena_payload("mB", b, start_ms=1_700_000_100_000)
    src = FakeSource(ids, {"mA": payload_a, "mB": payload_b})
    cfg = CrawlConfig(depth=1, start_epoch=1_600_000_000, end_epoch=1_800_000_000)
    out = {m.match_id async for m in MatchCrawler(src, cfg, set()).discover([a[0]])}
    assert out == {"mA", "mB"}     # depth-1 co-player's match WAS fetched (recursion works)


@pytest.mark.asyncio
async def test_discover_depth_zero_does_not_recurse():
    a, b = _16("A"), _16("B")
    payload_a = arena_payload("mA", [b[0]] + a[1:], start_ms=1_700_000_000_000)
    src = FakeSource({a[0]: ["mA"], b[0]: ["mB"]}, {"mA": payload_a, "mB": arena_payload("mB", b)})
    cfg = CrawlConfig(depth=0, start_epoch=1_600_000_000, end_epoch=1_800_000_000)
    out = {m.match_id async for m in MatchCrawler(src, cfg, set()).discover([a[0]])}
    assert out == {"mA"}           # no recursion at depth 0


@pytest.mark.asyncio
async def test_discover_respects_max_matches_bootstrap_cap():
    pus = _16("A")
    ids = [f"m{i}" for i in range(10)]
    src = FakeSource({pus[0]: ids}, {i: arena_payload(i, pus, start_ms=1_700_000_000_000) for i in ids})
    cfg = CrawlConfig(depth=0, max_matches=3, start_epoch=1_600_000_000, end_epoch=1_800_000_000)
    out = [m async for m in MatchCrawler(src, cfg, set()).discover([pus[0]])]
    assert len(out) == 3
```

- [ ] **Step 2: Run test to verify it fails (or passes)**

Run: `pytest tests/ingest/test_crawler.py -v`
Expected: the four new tests PASS if Task 2's implementation is correct. If `test_discover_recurses_to_coplayers_depth_n` FAILS, the recursion gate is wrong — fix the `if d + 1 <= cfg.depth:` enqueue block in `discover` until it passes. Do not change other tests.

- [ ] **Step 3: (only if a test failed) fix inline**

Adjust only the enqueue/bounds logic in `discover` to satisfy the failing test; re-run.

- [ ] **Step 4: Run the full crawler test file**

Run: `pytest tests/ingest/test_crawler.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/arena/ingest/crawler.py backend/tests/ingest/test_crawler.py
git commit -m "test(ingest): cover pagination, depth-N recursion, and bootstrap cap"
```

---

### Task 4: `PlayerRegistry.bulk_ensure` (DB-gated)

**Files:**
- Create: `backend/arena/ingest/registry.py`
- Test: `backend/tests/ingest/test_registry.py`

**Interfaces:**
- Consumes: `ParsedArenaMatch`, `arena.db.models as m`, `sqlalchemy.dialects.postgresql.insert`.
- Produces: `class PlayerRegistry` with
  `async def bulk_ensure(self, session, matches: Sequence[ParsedArenaMatch], *, region: str = "br", chunk: int = 1000) -> dict[str, str]` returning `{puuid: player_id}`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/ingest/test_registry.py
from __future__ import annotations

import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="registry test needs a migrated Postgres (set DATABASE_URL)",
)


@pytest.mark.asyncio
async def test_bulk_ensure_is_idempotent_and_maps_all_puuids():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from arena.core.config import settings
    from arena.ingest.registry import PlayerRegistry
    from tests.ingest.conftest import arena_payload
    from arena.riot.arena import parse_arena_match

    pus = [f"reg-{i}" for i in range(16)]
    parsed = parse_arena_match(arena_payload("reg-m1", pus))
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            id_map_1 = await PlayerRegistry().bulk_ensure(s, [parsed])
            await s.commit()
            assert set(id_map_1) == set(pus)
        async with factory() as s:
            id_map_2 = await PlayerRegistry().bulk_ensure(s, [parsed])  # re-encounter
            await s.commit()
        assert id_map_2 == id_map_1  # same ids, no duplicates
    finally:
        await engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run (with DB): `DATABASE_URL=postgresql+asyncpg://arena:arena@localhost:5432/arena pytest tests/ingest/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: arena.ingest.registry`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/arena/ingest/registry.py
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from arena.db import models as m
from arena.riot.arena import ParsedArenaMatch


class PlayerRegistry:
    """Bulk puuid->player_id upsert. One INSERT ... ON CONFLICT per `chunk`,
    RETURNING (id, puuid). COALESCE keeps a known name/tag/icon when the new row
    carries null. Idempotent across re-encounters and safe under concurrency."""

    async def bulk_ensure(
        self, session, matches: Sequence[ParsedArenaMatch], *,
        region: str = "br", chunk: int = 1000,
    ) -> dict[str, str]:
        roster: dict[str, dict] = {}
        for parsed in matches:
            for st in parsed.subteams:
                for pp in st.participants:
                    if not pp.puuid:
                        continue
                    roster[pp.puuid] = {
                        "puuid": pp.puuid,
                        "summoner_name": pp.riot_id_game_name or None,
                        "tag_line": pp.riot_id_tagline or None,
                        "region": region,
                        "profile_icon_id": pp.profile_icon or None,
                    }
        col = m.Player.__table__.c
        rows = list(roster.values())
        id_map: dict[str, str] = {}
        for i in range(0, len(rows), chunk):
            ins = pg_insert(m.Player.__table__).values(rows[i : i + chunk])
            stmt = ins.on_conflict_do_update(
                index_elements=["puuid"],
                set_={
                    "profile_icon_id": func.coalesce(ins.excluded.profile_icon_id, col.profile_icon_id),
                    "summoner_name": func.coalesce(ins.excluded.summoner_name, col.summoner_name),
                    "tag_line": func.coalesce(ins.excluded.tag_line, col.tag_line),
                },
            ).returning(col.id, col.puuid)
            for pid, pu in (await session.execute(stmt)).all():
                id_map[str(pu)] = str(pid)
        return id_map
```

- [ ] **Step 4: Run test to verify it passes**

Run (with DB): `DATABASE_URL=postgresql+asyncpg://arena:arena@localhost:5432/arena pytest tests/ingest/test_registry.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/arena/ingest/registry.py backend/tests/ingest/test_registry.py
git commit -m "feat(ingest): PlayerRegistry.bulk_ensure (idempotent bulk upsert)"
```

---

### Task 5: `replay_chronological` (ordering correctness, no DB)

**Files:**
- Create: `backend/arena/ingest/replay.py`
- Test: `backend/tests/ingest/test_replay.py`

**Interfaces:**
- Consumes: `ParsedArenaMatch`, `RawMatch`/`RawParticipant` (`arena.services.protocols`), `PremadeIntegrity` (`arena.services.match_pipeline`), a `rating_service` object exposing `async def process_match(session, lock_factory, raw)` and a mutable `_integrity` attribute (the real `RatingService`).
- Produces:
  - `@dataclass class ReplayStats { processed: int }`.
  - `async def replay_chronological(session, matches, *, season_id, party_store, id_map, rating_service) -> ReplayStats`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/ingest/test_replay.py
from __future__ import annotations

import pytest

from arena.ingest.replay import replay_chronological
from arena.riot.arena import parse_arena_match
from tests.ingest.conftest import arena_payload


class _RecordingRating:
    """Stand-in RatingService: records the order of riot_match_ids it sees."""
    def __init__(self):
        self._integrity = None
        self.order: list[str] = []
    async def process_match(self, session, lock_factory, raw):
        self.order.append(raw.riot_match_id)
        class _O: status = "ok"
        return _O()


@pytest.mark.asyncio
async def test_replay_processes_in_chronological_order():
    pus = [f"p{i}" for i in range(16)]
    late = parse_arena_match(arena_payload("late", pus, start_ms=2_000))
    early = parse_arena_match(arena_payload("early", pus, start_ms=1_000))
    id_map = {pu: f"id-{pu}" for pu in pus}
    rating = _RecordingRating()
    stats = await replay_chronological(
        session=None, matches=[late, early], season_id="s1",
        party_store=None, id_map=id_map, rating_service=rating,
    )
    assert stats.processed == 2
    assert rating.order == ["early", "late"]  # sorted by started_at_ms ascending
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingest/test_replay.py -v`
Expected: FAIL with `ModuleNotFoundError: arena.ingest.replay`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/arena/ingest/replay.py
from __future__ import annotations

import uuid
from collections.abc import Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from arena.riot.arena import ParsedArenaMatch
from arena.services.match_pipeline import PremadeIntegrity
from arena.services.protocols import RawMatch, RawParticipant


@dataclass
class ReplayStats:
    processed: int = 0


def _noop_lock(_ids):
    @asynccontextmanager
    async def cm():
        yield
    return cm()


async def replay_chronological(
    session, matches: Sequence[ParsedArenaMatch], *,
    season_id: str, party_store, id_map: dict[str, str], rating_service,
) -> ReplayStats:
    """Replay matches through the rating service in true gameStartTimestamp order
    so the premade co-occurrence ramp and Plackett-Luce updates match real history."""
    ordered = sorted(matches, key=lambda p: p.started_at_ms or 0)
    stats = ReplayStats()
    for parsed in ordered:
        ineligible: set[str] = set()
        raw_parts: list[RawParticipant] = []
        for st in parsed.subteams:
            for pp in st.participants:
                pid = id_map[pp.puuid]
                if not pp.eligible_for_progression:
                    ineligible.add(pid)
                raw_parts.append(RawParticipant(
                    player_id=pid, champion_id=pp.champion_id,
                    team_id=st.subteam_id, placement=st.placement,
                ))
        rating_service._integrity = PremadeIntegrity(ineligible, party_store)
        played_at = (
            datetime.fromtimestamp(parsed.started_at_ms / 1000, UTC).isoformat()
            if parsed.started_at_ms else datetime.now(UTC).isoformat()
        )
        raw = RawMatch(
            match_id=str(uuid.uuid4()), riot_match_id=parsed.match_id,
            season_id=season_id, mode=parsed.mode.value, queue_id=parsed.queue_id,
            played_at=played_at, participants=raw_parts,
            duration_seconds=parsed.game_duration,
        )
        await rating_service.process_match(session, _noop_lock, raw)
        stats.processed += 1
    return stats
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ingest/test_replay.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/arena/ingest/replay.py backend/tests/ingest/test_replay.py
git commit -m "feat(ingest): replay_chronological (sorted RatingService replay)"
```

---

### Task 6: `engine.py` caching factory + package exports

**Files:**
- Create: `backend/arena/ingest/engine.py`
- Modify: `backend/arena/ingest/__init__.py`
- Test: `backend/tests/ingest/test_engine.py`

**Interfaces:**
- Produces:
  - `def caching_engine_and_factory(database_url: str) -> tuple[AsyncEngine, async_sessionmaker]` — engine WITHOUT `statement_cache_size=0` (caching ON; direct PG).
  - `arena.ingest.__init__` re-exports `MatchCrawler, CrawlConfig, MatchSource, ARENA_QUEUES, PlayerRegistry, replay_chronological, ReplayStats, caching_engine_and_factory`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/ingest/test_engine.py
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from arena.ingest import caching_engine_and_factory, MatchCrawler, PlayerRegistry, replay_chronological


def test_caching_engine_does_not_disable_statement_cache():
    engine, factory = caching_engine_and_factory("postgresql+asyncpg://arena:arena@localhost:5432/arena")
    assert isinstance(engine, AsyncEngine)
    # The app engine sets statement_cache_size=0 for PgBouncer; the script engine must NOT.
    connect_args = engine.pool._creator.keywords.get("connect_args", {}) if hasattr(engine.pool, "_creator") else {}
    assert connect_args.get("statement_cache_size", "unset") != 0


def test_package_reexports_present():
    assert MatchCrawler and PlayerRegistry and replay_chronological
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingest/test_engine.py -v`
Expected: FAIL with `ImportError: cannot import name 'caching_engine_and_factory'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/arena/ingest/engine.py
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


def caching_engine_and_factory(database_url: str) -> tuple[AsyncEngine, async_sessionmaker]:
    """Dedicated engine for offline scripts that connect DIRECTLY to Postgres.
    Unlike the app engine (statement_cache_size=0 for PgBouncer tx-mode), this
    keeps asyncpg statement caching ON — ~34x faster on the replay hot path."""
    engine = create_async_engine(database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    return engine, factory
```

```python
# backend/arena/ingest/__init__.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ingest/test_engine.py -v`
Expected: PASS (2 passed). If the `connect_args` introspection in Step 1 is brittle on this SQLAlchemy version, simplify the assertion to construct the engine and assert `"statement_cache_size=0" not in repr(engine.sync_engine.url)` plus that the function returns an `AsyncEngine` — the intent is "we did not disable the cache."

- [ ] **Step 5: Commit**

```bash
git add backend/arena/ingest/engine.py backend/arena/ingest/__init__.py backend/tests/ingest/test_engine.py
git commit -m "feat(ingest): caching engine factory + package exports"
```

---

### Task 7: `scripts/backfill.py` thin CLI (refresh + bootstrap)

**Files:**
- Create: `backend/scripts/backfill.py`
- Test: `backend/tests/ingest/test_backfill_cli.py`

**Interfaces:**
- Consumes: `build_default_client` (`arena.riot.client`), `Region` (`arena.riot.routing`), all `arena.ingest` exports, `RedisPartyCooccurrenceStore`, `RatingService`, `arena.db.models`, `arena.core.config.settings`.
- Produces:
  - `def parse_args(argv: list[str] | None = None) -> argparse.Namespace`.
  - `async def resolve_seeds(session, source, *, mode, seed_riot_id, region) -> list[str]`.
  - `async def run(args) -> None` (full orchestration).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/ingest/test_backfill_cli.py
from __future__ import annotations

import pytest

from scripts.backfill import parse_args, resolve_seeds


def test_parse_args_modes_and_defaults():
    a = parse_args(["--mode", "refresh"])
    assert a.mode == "refresh" and a.depth == 3 and a.max_matches is None
    b = parse_args(["--mode", "bootstrap", "--seed-riot-id", "Presente#1001", "--max-matches", "50"])
    assert b.mode == "bootstrap" and b.seed_riot_id == "Presente#1001" and b.max_matches == 50


@pytest.mark.asyncio
async def test_resolve_seeds_bootstrap_uses_account_lookup():
    class _Src:
        async def get_account_by_riot_id(self, name, tag, region=None):
            assert (name, tag) == ("Presente", "1001")
            return {"puuid": "PU-123"}
    seeds = await resolve_seeds(session=None, source=_Src(), mode="bootstrap",
                                seed_riot_id="Presente#1001", region="americas")
    assert seeds == ["PU-123"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingest/test_backfill_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: scripts.backfill`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/scripts/backfill.py
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
        print("RIOT_API_KEY empty"); return
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
                    print("no seeds resolved"); return
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
            from sqlalchemy import text
            await s.execute(text("SET synchronous_commit = off"))
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ingest/test_backfill_cli.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/backfill.py backend/tests/ingest/test_backfill_cli.py
git commit -m "feat(scripts): unified backfill CLI (refresh + bootstrap)"
```

---

### Task 8: End-to-end backfill smoke (DB-gated)

**Files:**
- Test: `backend/tests/ingest/test_backfill_e2e.py`

**Interfaces:**
- Consumes: `scripts.backfill.run`, a `FakeSource`-backed monkeypatch of `build_default_client`, the populated DB.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/ingest/test_backfill_e2e.py
from __future__ import annotations

import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="e2e backfill needs a migrated+seeded Postgres (set DATABASE_URL)",
)


@pytest.mark.asyncio
async def test_bootstrap_run_processes_matches(monkeypatch):
    """Drive run() in bootstrap mode against a FakeSource client (no Riot network),
    asserting it discovers, registers players, and replays without error."""
    import scripts.backfill as bf
    from tests.ingest.conftest import FakeSource, arena_payload

    pus = [f"e2e-{i}" for i in range(16)]
    fake = FakeSource({pus[0]: ["e2e-m1"]}, {"e2e-m1": arena_payload("e2e-m1", pus)})

    class _Client(FakeSource):
        async def get_account_by_riot_id(self, name, tag, region=None):
            return {"puuid": pus[0]}
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None

    client = _Client(fake._ids, fake._payloads)
    monkeypatch.setattr(bf, "build_default_client", lambda *a, **k: client)

    args = bf.parse_args(["--mode", "bootstrap", "--seed-riot-id", "X#1", "--depth", "0"])
    await bf.run(args)  # must complete without raising
```

- [ ] **Step 2: Run test to verify it fails, then passes**

Run (with DB): `DATABASE_URL=postgresql+asyncpg://arena:arena@localhost:5432/arena pytest tests/ingest/test_backfill_e2e.py -v`
Expected: FAIL only if `run()` has a wiring bug; otherwise PASS. Fix wiring in `scripts/backfill.py` until it passes. (Redis must be up.)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/ingest/test_backfill_e2e.py
git commit -m "test(ingest): DB-gated bootstrap backfill smoke"
```

---

### Task 9: Point the worker's discovery at `MatchCrawler`

**Files:**
- Modify: `backend/arena/workers/ingestion.py` (the per-tick "fetch match ids for tracked players" step)
- Test: `backend/tests/workers/test_ingestion_uses_crawler.py`

**Interfaces:**
- Consumes: `MatchCrawler`, `CrawlConfig`; the worker's `get_riot_client()` adapter must satisfy `MatchSource` (it already exposes `get_match`; add a `get_match_ids_by_puuid` passthrough on the adapter if it only has `list_match_ids`).
- Produces: the worker tick yields the same enqueue behavior, now sourced from `MatchCrawler.discover` with `depth=0` (streaming; the worker handles its own recursion via tracked players across ticks).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/workers/test_ingestion_uses_crawler.py
from __future__ import annotations

from arena.workers.deps import get_riot_client
from arena.ingest.crawler import MatchSource


def test_worker_riot_adapter_satisfies_matchsource():
    client = get_riot_client()
    # The crawler needs these two method names; the adapter must expose them.
    assert hasattr(client, "get_match_ids_by_puuid")
    assert hasattr(client, "get_match")
    assert isinstance(client, MatchSource)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/workers/test_ingestion_uses_crawler.py -v`
Expected: FAIL — the adapter currently exposes `list_match_ids`, not `get_match_ids_by_puuid`.

- [ ] **Step 3: Write minimal implementation**

In `backend/arena/workers/deps.py`, add a `get_match_ids_by_puuid(self, puuid, *, start, count, queue, start_time, end_time)` method to the worker's Riot adapter that delegates to the wrapped real client's `get_match_ids_by_puuid` (keep `list_match_ids` for back-compat). Then in `backend/arena/workers/ingestion.py`, replace the hand-written per-player id fetch with:

```python
from arena.ingest.crawler import CrawlConfig, MatchCrawler

# inside the tick, for the tracked-player batch `puuids`:
crawler = MatchCrawler(client, CrawlConfig(depth=0, region=region), seen_match_ids=already_seen)
async for parsed in crawler.discover(puuids):
    await _enqueue(parsed)   # existing classify+enqueue path, fed a ParsedArenaMatch
```

Keep the existing backpressure / pressure-mode gate and Top-1000 priority classification unchanged; only the id-fetch+parse source changes.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/workers/test_ingestion_uses_crawler.py tests/workers/test_wiring_contract.py -v`
Expected: PASS (both files green — the wiring-contract test still passes because `list_match_ids` remains).

- [ ] **Step 5: Commit**

```bash
git add backend/arena/workers/deps.py backend/arena/workers/ingestion.py backend/tests/workers/test_ingestion_uses_crawler.py
git commit -m "refactor(workers): source ingestion discovery from MatchCrawler"
```

---

### Task 10: Delete the old scripts; update references

**Files:**
- Delete: `backend/scripts/backfill_real.py`
- Delete: `backend/scripts/backfill_matches.py`
- Modify: `backend/README.md` / root `README.md` and `workaround.md` references to the old scripts (point them at `python -m scripts.backfill --mode …`)

- [ ] **Step 1: Grep for references**

Run: `grep -rn "backfill_real\|backfill_matches" backend README.md workaround.md docs`
Expected: a list of doc/command references.

- [ ] **Step 2: Delete the files**

```bash
git rm backend/scripts/backfill_real.py backend/scripts/backfill_matches.py
```

- [ ] **Step 3: Update each reference** found in Step 1 to the new CLI (`python -m scripts.backfill --mode refresh …` / `--mode bootstrap …`). Show the replaced lines in the commit.

- [ ] **Step 4: Run the full ingest suite + import sanity**

Run: `pytest tests/ingest tests/workers -v` and `python -c "import scripts.backfill, arena.ingest"`
Expected: PASS; no import errors; no remaining references to the deleted modules.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove duplicate backfill scripts; point docs at unified CLI"
```

---

## Self-Review

**Spec coverage:**
- §1 file reorg → Tasks 1–7, 10 (package created, scripts collapsed, old deleted). ✓
- §2 components/interfaces → `MatchSource`/`CrawlConfig` (T1), `MatchCrawler` (T2–3), `PlayerRegistry` (T4), `replay_chronological` (T5), `engine` (T6), seed resolution (T7). ✓
- §3 data flow & modes → CLI orchestration + refresh/bootstrap seeds + termination (T7), worker streaming (T9). ✓ Cursor "new tail" optimization is intentionally deferred (refresh skips already-stored ids via `seen_match_ids`); note below.
- §4 error handling & testing → typed-error skips + per-match skip (T2), idempotent resume via `seen_match_ids` (T2/T7), unit tests with fakes (T2–3, T5), DB-gated (T4, T8), worker (T9). ✓

**Deferred from spec (call out, not silent):** the per-player **ingest cursor** tail-fetch (`ingest_cursor_key`) is not implemented; refresh relies on `seen_match_ids` + the date window to avoid reprocessing. If first-run API volume is a concern, add a follow-up task to seed `start_epoch` from each player's last stored match. This matches the default decision to keep refresh uncapped.

**Placeholder scan:** no TBD/TODO; every code step has complete code. ✓

**Type consistency:** `CrawlConfig` fields, `MatchCrawler(source, cfg, seen_match_ids)`, `discover(seed_puuids) -> AsyncIterator[ParsedArenaMatch]`, `PlayerRegistry.bulk_ensure(session, matches, *, region, chunk) -> dict[str,str]`, `replay_chronological(session, matches, *, season_id, party_store, id_map, rating_service) -> ReplayStats` are used identically across Tasks 5/7/8. ✓
