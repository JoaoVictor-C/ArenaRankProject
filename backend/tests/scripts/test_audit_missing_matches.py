"""Tests for scripts/audit_missing_matches.py — the one-run coverage audit.

Covers the parts that carry real logic: the Riot/DB diff, the never-ingested vs
participant-gap split, Riot pagination bounds, and the call budget. No DB, no
network — the DB reads are thin SELECTs and the report is formatting.
"""

from __future__ import annotations

import argparse

from arena.core.config import settings
from scripts.audit_missing_matches import (
    PlayerGap,
    _Budget,
    _riot_ids_for,
    _since_epoch,
    diff_page,
    split_missing,
)


def _args(**over: object) -> argparse.Namespace:
    base = {
        "matches_per_page": 5,
        "max_pages_per_player": 3,
    }
    base.update(over)
    return argparse.Namespace(**base)


# ---------------------------------------------------------------------------
# Diff accounting
# ---------------------------------------------------------------------------

_PAGE = [
    ("pid-a", "pu-a", "A#BR1"),
    ("pid-b", "pu-b", "B#BR1"),
]


def test_counts_computed_and_missing_per_player():
    fetched = [
        (["m1", "m2", "m3"], False, False),
        (["m4"], False, False),
    ]
    computed = {"pid-a": {"m1"}, "pid-b": {"m4"}}

    gaps, unknown = diff_page(_PAGE, fetched, computed)

    a, b = gaps
    assert (a.riot_total, a.computed, a.missing) == (3, 1, 2)
    assert (b.riot_total, b.computed, b.missing) == (1, 1, 0)
    assert unknown == ["m2", "m3"]


def test_computed_ignores_db_matches_outside_the_riot_window():
    """A player with old matches in the DB must not show negative/inflated cover."""
    fetched = [(["m1"], False, False), ([], False, False)]
    # pid-a has an extra computed match that Riot did not list in this window.
    computed = {"pid-a": {"m1", "ancient"}, "pid-b": set()}

    gaps, _ = diff_page(_PAGE, fetched, computed)

    assert gaps[0].computed == 1  # only the intersection counts
    assert gaps[0].missing == 0


def test_unknown_ids_are_deduplicated_across_players():
    """A shared lobby missing for both players is classified once, not twice."""
    fetched = [(["shared"], False, False), (["shared"], False, False)]

    _, unknown = diff_page(_PAGE, fetched, {})

    assert unknown == ["shared"]


def test_flags_propagate():
    fetched = [([], True, False), ([], False, True)]

    gaps, _ = diff_page(_PAGE, fetched, {})

    assert gaps[0].truncated and not gaps[0].partial
    assert gaps[1].partial and not gaps[1].truncated


# ---------------------------------------------------------------------------
# never_ingested vs participant_gap
# ---------------------------------------------------------------------------


def test_split_separates_undiscovered_from_lost_participant_rows():
    gap = PlayerGap(puuid="pu-a", player_id="pid-a", name="A", never_ingested=["m1", "m2", "m3"])

    # m2 has a matches row: discovery worked, this player's row is what's missing.
    split_missing([gap], {"m2"})

    assert gap.never_ingested == ["m1", "m3"]
    assert gap.participant_gap == ["m2"]
    assert gap.missing == 3  # the total is unchanged by the split


def test_split_with_nothing_known_leaves_everything_never_ingested():
    gap = PlayerGap(puuid="p", player_id="i", name="n", never_ingested=["m1"])

    split_missing([gap], set())

    assert gap.never_ingested == ["m1"]
    assert gap.participant_gap == []


# ---------------------------------------------------------------------------
# Riot pagination + budget
# ---------------------------------------------------------------------------


class _PagedClient:
    """Returns `pages` full pages then a short one, per queue."""

    def __init__(self, pages: int) -> None:
        self.pages = pages
        self.calls = 0

    async def list_match_ids(
        self, puuid: str, *, start=0, count=5, queue=None, start_time=None
    ) -> list[str]:
        self.calls += 1
        page = start // count
        if page >= self.pages:
            return []
        return [f"m-{queue}-{start + i}" for i in range(count)]


async def test_pagination_cap_is_reported_not_silently_dropped():
    client = _PagedClient(pages=99)
    budget = _Budget(0)

    ids, truncated, partial = await _riot_ids_for(client, "pu", 0, _args(), budget)

    assert truncated is True
    assert partial is False
    # 3 pages x 5 ids x each live queue.
    assert len(ids) == 3 * 5 * len(settings.live_queue_ids)


async def test_ids_are_deduplicated_across_queues():
    class _SameIdClient:
        async def list_match_ids(self, puuid, *, start=0, count=5, queue=None, start_time=None):
            return ["dupe"] if start == 0 else []

    ids, _, _ = await _riot_ids_for(_SameIdClient(), "pu", 0, _args(), _Budget(0))

    assert ids == ["dupe"]


async def test_riot_error_marks_partial_without_aborting():
    class _BrokenClient:
        async def list_match_ids(self, *a: object, **kw: object) -> list[str]:
            raise RuntimeError("503")

    ids, _, partial = await _riot_ids_for(_BrokenClient(), "pu", 0, _args(), _Budget(0))

    assert partial is True
    assert ids == []


async def test_budget_stops_the_walk_and_marks_truncated():
    client = _PagedClient(pages=99)
    budget = _Budget(2)

    _, truncated, _ = await _riot_ids_for(client, "pu", 0, _args(), budget)

    assert budget.exhausted
    assert truncated is True
    assert client.calls == 2  # never overspends the ceiling


def test_unbounded_budget_never_exhausts():
    budget = _Budget(0)
    for _ in range(1000):
        assert budget.take()
    assert not budget.exhausted


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------


def test_since_days_wins_when_given():
    import time

    since = _since_epoch(argparse.Namespace(since_days=7))

    assert abs(since - (int(time.time()) - 7 * 24 * 3600)) < 5


def test_since_defaults_to_the_launch_cutoff(monkeypatch):
    monkeypatch.setattr(settings, "match_min_started_at_ms", 1_700_000_000_000)

    assert _since_epoch(argparse.Namespace(since_days=0)) == 1_700_000_000
