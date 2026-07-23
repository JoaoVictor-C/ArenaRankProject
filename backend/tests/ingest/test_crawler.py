from __future__ import annotations

import pytest

from arena.ingest.crawler import ARENA_QUEUES, CrawlConfig, MatchCrawler, MatchSource
from tests.ingest.conftest import FakeSource, arena_payload


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


@pytest.mark.asyncio
async def test_discover_continues_after_ids_error():
    """A puuid whose get_match_ids_by_puuid raises must not abort the crawl;
    the other seeds' matches are still yielded (FIX 1 regression)."""

    class _ErrorOnBadSource(FakeSource):
        async def get_match_ids_by_puuid(
            self, puuid, *, start, count, queue, start_time, end_time
        ):
            if puuid == "bad-puuid":
                raise RuntimeError("404 simulated")
            return await super().get_match_ids_by_puuid(
                puuid, start=start, count=count, queue=queue,
                start_time=start_time, end_time=end_time,
            )

    good_pus = _16("G")
    src = _ErrorOnBadSource(
        {"bad-puuid": [], good_pus[0]: ["m-good"]},
        {"m-good": arena_payload("m-good", good_pus, start_ms=1_700_000_000_000)},
    )
    cfg = CrawlConfig(depth=0, start_epoch=1_600_000_000, end_epoch=1_800_000_000)
    out = [m async for m in MatchCrawler(src, cfg, set()).discover(["bad-puuid", good_pus[0]])]
    assert [m.match_id for m in out] == ["m-good"]
