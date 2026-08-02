"""``StatsService.champion_build_picks`` / ``top_build_picks`` — the read half of
the native augment/item rollup (``champion_build_stats``, see
``test_champion_build_stats_rollup.py`` for the write/aggregation side).

Inserts directly into ``champion_build_stats`` (+ ``champion_daily_stats`` for
the pick-rate denominator) rather than re-deriving rows through the full
match fixture — these methods only care about already-aggregated counters,
so this is the more direct unit boundary.

Aceites:

* per-champion ``pick_rate`` = share of the CHAMPION's total eligible games
  (from ``champion_daily_stats``, the champion_tierlist source) — NOT the
  floor-filtered pick pool, so excluding the tail can't inflate survivors;
* global (``top_build_picks``) ``pick_rate`` = share of the CATEGORY's own
  floor-qualified pool — mirrors the old external top_build's convention;
* tier is assigned by relative strength WITHIN the queried pool (best
  avg_place first), never against an absolute external scale;
* augment/item kinds never leak into each other's results.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.pool import NullPool

from arena.services.stats_service import StatsService

_db = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="build stats read tests need a migrated Postgres (set DATABASE_URL)",
)

DAY0 = datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)


class _Fixture:
    def __init__(self) -> None:
        self.season_id = uuid.uuid4()

    async def set_champion_total(
        self, session: Any, *, champion_id: int, games: int
    ) -> None:
        """Seeds champion_daily_stats — the pick-rate denominator source."""
        from sqlalchemy import text

        await session.execute(
            text(
                "INSERT INTO champion_daily_stats "
                "(season_id, snapshot_date, champion_id, games, top4, first_place, placement_sum) "
                "VALUES (:s, :d, :c, :g, :g, 0, :ps)"
            ),
            {"s": self.season_id, "d": DAY0.date(), "c": champion_id, "g": games, "ps": games * 3},
        )

    async def add_pick(
        self,
        session: Any,
        *,
        champion_id: int,
        kind: str,
        pick_id: int,
        games: int,
        avg_place: float,
    ) -> None:
        from sqlalchemy import text

        placement_sum = round(games * avg_place)
        await session.execute(
            text(
                "INSERT INTO champion_build_stats "
                "(season_id, kind, champion_id, pick_id, games, top1, top4, placement_sum) "
                "VALUES (:s, :k, :c, :p, :g, 0, :g, :ps)"
            ),
            {
                "s": self.season_id, "k": kind, "c": champion_id, "p": pick_id,
                "g": games, "ps": placement_sum,
            },
        )

    async def cleanup(self, session: Any) -> None:
        from sqlalchemy import text

        await session.execute(
            text("DELETE FROM champion_build_stats WHERE season_id=:s"), {"s": self.season_id}
        )
        await session.execute(
            text("DELETE FROM champion_daily_stats WHERE season_id=:s"), {"s": self.season_id}
        )
        await session.commit()


@asynccontextmanager
async def _fixture() -> AsyncIterator[tuple[Any, _Fixture]]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    fx = _Fixture()
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        try:
            yield session, fx
        finally:
            await session.rollback()
            await fx.cleanup(session)


_CHAMP_A = 8101
_CHAMP_B = 8102


@_db
async def test_champion_pick_rate_is_share_of_the_champion_total_not_the_pool() -> None:
    """25 games on a pick, 100 total games on the champion -> 25.0%, even
    though the floor-filtered pool itself might only sum to less than 100."""
    async with _fixture() as (session, fx):
        await fx.set_champion_total(session, champion_id=_CHAMP_A, games=100)
        await fx.add_pick(
            session, champion_id=_CHAMP_A, kind="augment", pick_id=1, games=25, avg_place=3.0
        )
        await session.commit()

        rows = await StatsService().champion_build_picks(
            session, season_id=str(fx.season_id), champion_id=_CHAMP_A, kind="augment",
            min_games=1,
        )
        assert len(rows) == 1
        assert rows[0].pick_rate == 25.0


@_db
async def test_champion_picks_are_tiered_relative_to_each_other() -> None:
    """10 picks, evenly spread avg_place — the best (lowest) lands in S (top
    10%), the worst in D, order preserved in between."""
    async with _fixture() as (session, fx):
        await fx.set_champion_total(session, champion_id=_CHAMP_A, games=1000)
        for i in range(10):
            await fx.add_pick(
                session, champion_id=_CHAMP_A, kind="augment", pick_id=100 + i,
                games=10, avg_place=2.0 + i * 0.2,  # ranked worst as i grows
            )
        await session.commit()

        rows = await StatsService().champion_build_picks(
            session, season_id=str(fx.season_id), champion_id=_CHAMP_A, kind="augment",
            min_games=1,
        )
        by_pick = {r.pick_id: r for r in rows}
        assert by_pick[100].tier == "S"  # best avg_place, rank 1/10
        assert by_pick[109].tier == "D"  # worst avg_place, rank 10/10
        # Monotonic: better avg_place never gets a numerically "worse" letter
        # than a pick ranked after it.
        order = "SABCD"
        ranks = [order.index(by_pick[100 + i].tier) for i in range(10)]
        assert ranks == sorted(ranks)


@_db
async def test_champion_kind_filter_excludes_the_other_kind() -> None:
    async with _fixture() as (session, fx):
        await fx.set_champion_total(session, champion_id=_CHAMP_A, games=100)
        await fx.add_pick(
            session, champion_id=_CHAMP_A, kind="augment", pick_id=1, games=10, avg_place=3.0
        )
        await fx.add_pick(
            session, champion_id=_CHAMP_A, kind="item", pick_id=1, games=10, avg_place=3.0
        )
        await session.commit()

        augments = await StatsService().champion_build_picks(
            session, season_id=str(fx.season_id), champion_id=_CHAMP_A, kind="augment",
            min_games=1,
        )
        items = await StatsService().champion_build_picks(
            session, season_id=str(fx.season_id), champion_id=_CHAMP_A, kind="item",
            min_games=1,
        )
        assert len(augments) == 1 and len(items) == 1  # same pick_id, both kinds present
        assert augments[0].pick_id == items[0].pick_id  # confirms it's the SAME id, not a fluke


@_db
async def test_champion_picks_below_write_floor_are_absent_not_zero() -> None:
    async with _fixture() as (session, fx):
        await fx.set_champion_total(session, champion_id=_CHAMP_A, games=100)
        await fx.add_pick(
            session, champion_id=_CHAMP_A, kind="augment", pick_id=1, games=5, avg_place=3.0
        )
        await session.commit()
        rows = await StatsService().champion_build_picks(
            session, season_id=str(fx.season_id), champion_id=_CHAMP_A, kind="augment",
            min_games=50,
        )
        assert rows == []


@_db
async def test_top_build_sums_across_champions_pick_rate_is_share_of_category() -> None:
    """Two champions both carry pick 1 (games 30 + 70 = 100 total). A THIRD
    pick (pick 2, 100 games) sits alone — the category total is 200, so pick 1
    is 50% and pick 2 is 50%, even though pick 2 came from a single champion."""
    async with _fixture() as (session, fx):
        await fx.add_pick(
            session, champion_id=_CHAMP_A, kind="augment", pick_id=1, games=30, avg_place=2.5
        )
        await fx.add_pick(
            session, champion_id=_CHAMP_B, kind="augment", pick_id=1, games=70, avg_place=3.5
        )
        await fx.add_pick(
            session, champion_id=_CHAMP_A, kind="augment", pick_id=2, games=100, avg_place=4.0
        )
        await session.commit()

        rows = await StatsService().top_build_picks(
            session, season_id=str(fx.season_id), kind="augment", min_games=1
        )
        by_pick = {r.pick_id: r for r in rows}
        assert by_pick[1].games == 100  # 30 + 70, summed across champions
        assert by_pick[1].pick_rate == 50.0
        assert by_pick[2].pick_rate == 50.0
        # Weighted avg_place for pick 1: (30*2.5 + 70*3.5) / 100 = 3.2
        assert by_pick[1].avg_place == 3.2
        # Only 2 in the pool: rank 1/2 = 50% frac -> "B" bucket (S needs top 10%,
        # unreachable with n=2); rank 2/2 = 100% -> "D". Strength order still holds.
        assert by_pick[1].tier == "B"  # stronger (lower avg_place) of the two
        assert by_pick[2].tier == "D"


@_db
async def test_top_build_below_write_floor_is_absent() -> None:
    async with _fixture() as (session, fx):
        await fx.add_pick(
            session, champion_id=_CHAMP_A, kind="augment", pick_id=1, games=50, avg_place=3.0
        )
        await session.commit()
        rows = await StatsService().top_build_picks(
            session, season_id=str(fx.season_id), kind="augment", min_games=200
        )
        assert rows == []
