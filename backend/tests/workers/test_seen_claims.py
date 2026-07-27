"""Regression tests for the seen-matches CLAIM lifecycle.

``_dedup_new`` marks an id as seen at DISCOVERY time, long before anything
guarantees it will be processed. The old implementation was a plain SET whose
whole-key TTL was refreshed on every productive tick, so:

* an id claimed and then dropped (retries exhausted, failed push) was invisible
  to every future sweep — permanently;
* the documented "re-discovered after 24h" backstop never actually fired.

These tests pin the lease semantics that replaced it.
"""

from __future__ import annotations

import time

from arena.workers import queues as Q
from arena.workers.ingestion import _dedup_new, _release_seen
from arena.workers.sweep import _push_claimed


async def test_claim_is_exclusive_and_order_preserving(fake_redis):
    assert await _dedup_new(fake_redis, ["m1", "m2", "m3"]) == ["m1", "m2", "m3"]
    assert await _dedup_new(fake_redis, ["m2", "m3"]) == []
    assert await _dedup_new(fake_redis, ["m3", "m4"]) == ["m4"]


async def test_release_makes_an_id_discoverable_again(fake_redis):
    await _dedup_new(fake_redis, ["m1"])
    assert await _dedup_new(fake_redis, ["m1"]) == []

    await _release_seen(fake_redis, ["m1"])

    assert await _dedup_new(fake_redis, ["m1"]) == ["m1"]


async def test_claims_age_out_per_member(fake_redis):
    """The TTL backstop the old whole-key EXPIRE silently disabled."""
    await _dedup_new(fake_redis, ["fresh"])
    # Backdate one claim past the TTL; the next claim call prunes it.
    stale_score = time.time() - Q.SEEN_MATCH_TTL_SECONDS - 60
    await fake_redis.zadd(Q.SEEN_MATCHES_ZSET, {"stale": stale_score})

    reclaimed = await _dedup_new(fake_redis, ["stale", "fresh"])

    assert reclaimed == ["stale"]  # aged out and re-claimable; "fresh" is not


async def test_push_failure_releases_the_claim(fake_redis, monkeypatch):
    claimed = await _dedup_new(fake_redis, ["m1", "m2"])
    assert claimed == ["m1", "m2"]

    async def _boom(*args: object, **kw: object) -> int:
        raise RuntimeError("redis down")

    monkeypatch.setattr(fake_redis, "enqueue_job", _boom)
    assert await _push_claimed(fake_redis, Q.STANDARD_QUEUE, claimed) == 0

    # Claimed but queued nowhere -> must be rediscoverable, not lost.
    monkeypatch.undo()
    assert await _dedup_new(fake_redis, ["m1", "m2"]) == ["m1", "m2"]


# Note: the old bulk_processor._process_one had its own claim-release fallback
# for exceptions escaping process_match entirely (outside its own Retry/DLQ
# classification) — that path had no real arq equivalent even before this
# module was retired (an exception escaping process_match's own comprehensive
# try/except would instead hit arq's max_tries and be dropped, not classified).
# What DOES still hold, unchanged, is that process_match itself never touches
# the seen-claim on any outcome (success, filter, dead-letter) — the claim's
# lifecycle is entirely a discovery-time concern now, covered by the
# push-failure test above and the lease tests below.
