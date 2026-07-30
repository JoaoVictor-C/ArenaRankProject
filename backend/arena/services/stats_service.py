"""StatsService — derived read models for player profiles (proposal §3.3).

Pure-ish aggregation over ``champion_stats`` and ``match_participants``:

* **champion stats**  — per-champion games / first-place rate / top-half rate /
  average placement / net CR impact / recent-form sparkline.
* **head-to-head**    — with/against another player: games together and win rate,
  classifying the relationship as ``duo`` (mostly same team) or ``rival``.
* **streak**          — the player's current win/loss streak for a season.

All queries enforce the Trinity ``played_at`` predicate where a participant scan
is involved (the ``match_participants`` HASH partition + ``(player_id,
played_at DESC)`` index path). ToS: champion winrate is internal — the public
profile surfaces placement-derived metrics (first-rate, top-half, avg place,
CR impact), never augment/item winrate. User-facing strings PT-BR.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from typing import Any

from sqlalchemy import (
    Date,
    Float,
    FromClause,
    Integer,
    Select,
    and_,
    case,
    cast,
    column,
    delete,
    func,
    insert,
    literal,
    select,
    true,
    values,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from arena.core.config import settings
from arena.db import models as m
from arena.schemas import PlayerTag

# A floor predicate for participant scans (Trinity #2/#10 — always bound
# played_at so the planner prunes hash partitions and uses the time index).
# timezone-aware: a naive epoch breaks asyncpg's timestamptz encoder on Windows
# (OSError 22). Aware UTC encodes the instant directly with no local conversion.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Subteam count per Arena mode (Riot facts, mirrored in arena.riot.arena):
#   DUOS  (queue 1700, "2v2") -> 8 teams -> "win" = placement <= 4
#   TRIOS (queue 1750, "3v3") -> 6 teams -> "win" = placement <= 3
# A "win" is a top-half finish (placement <= teamCount // 2). "top4" is the
# fixed placement<=4 podium-ish band the contract surfaces for every mode.
_TEAM_COUNT_BY_MODE: dict[m.RatingMode, int] = {
    m.RatingMode.DUOS: 8,
    m.RatingMode.TRIOS: 6,
}
_TOP4_THRESHOLD = 4

# Synergy showcase floor: pairs with fewer shared subteam-games than this never
# surface (a 100% winrate over a handful of games is noise, not a duo).
# Provisional (the busiest pair currently has ~18 games): 15 for now; raise to
# 30 once the season accumulates volume. Exposed in the API response so the UI
# can state the criterion instead of implying an unfiltered ranking.
SYNERGY_MIN_GAMES = 15
# Floor-qualified pool pulled from SQL before the Wilson re-rank in Python
# (dialect-safe: no sqrt() in SQL). Champion-pair cardinality above the floor is
# small; this cap only guards a pathological season.
_SYNERGY_POOL = 400
# z for the Wilson lower bound. 2.576 (99%) on purpose — this is a showcase
# ranking, not a CI claim, and the stricter z punishes tiny samples harder: with
# 1.96 a 100%-over-15 run still edges out 85%-over-200, which is exactly the
# ordering the showcase must never produce.
_WILSON_Z = 2.576


def _wilson_lower_bound(successes: int, games: int, *, z: float = _WILSON_Z) -> float:
    """Lower bound of the Wilson score interval for a binomial proportion.

    Ranks "62% over 200 games" above "100% over 15 games" — the anti-noise
    ordering for small-sample showcases (legitimacy first).
    """
    if games <= 0:
        return 0.0
    p = successes / games
    z2 = z * z
    denom = 1 + z2 / games
    center = p + z2 / (2 * games)
    margin = z * math.sqrt((p * (1 - p) + z2 / (4 * games)) / games)
    return (center - margin) / denom


def _delta_pp(recent_top4: int, recent_games: int, prior_top4: int, prior_games: int) -> int:
    """Signed percentage-point change of the top-half rate: recent 7d vs prior 7d.

    Returns 0 when either window is empty (no basis for comparison) so a champion
    that only just appeared shows no misleading swing. Both rates are rounded the
    same way the tierlist rounds ``top4_rate`` so the delta reconciles with it.
    """
    if recent_games <= 0 or prior_games <= 0:
        return 0
    return round(100 * recent_top4 / recent_games) - round(100 * prior_top4 / prior_games)


# -- player tags (contract PlayerTag; labels/icons mirror the design mock) -----
# Window over which delta7d is measured and the "Em alta" (hot) tag fires.
_DELTA7D_WINDOW = timedelta(days=7)
# delta7d strictly above this (CR points gained over ~7d) earns the "hot" tag.
_HOT_DELTA_THRESHOLD = 50
# matches_played at/above this earns the "Veterano" tag.
_VETERAN_MATCHES = 100
# A single champion accounting for >= this share of games earns the "OTP" tag.
# Provisional (season has ~2 days of data, max share in top-50 ≈ 26%): 0.30 for
# now; restore to 0.40 once the season accumulates volume.
_OTP_SHARE = 0.30
# Minimum games on a champion to qualify for a "TOP n {champ}" placement rank.
# Provisional (global max games on one champion is currently 12): 2 for now;
# restore to 15 once the season accumulates volume.
_CHAMP_RANK_MIN_GAMES = 2
# Only surface a "TOP n {champ}" tag when the rank is at/below this (a real flex,
# not "TOP 480 Ezreal"). Keeps the leaderboard free of generic filler tags.
_CHAMP_RANK_MAX = 25


@dataclass(slots=True)
class OtpView:
    """One-trick-pony signal: the player's most-played champion and its share."""

    champion_id: int
    games: int
    share: float  # 0..1 — most-played champion games / total games


@dataclass(slots=True)
class ChampRankView:
    """Player's placement rank on one champion (for the "TOP n {champ}" tag).

    ``rank`` is 1-based by **average placement ascending** (a lower mean placement
    is better) among every player with ``>= _CHAMP_RANK_MIN_GAMES`` games on the
    champion in the season. Placement-derived only (ToS): no CR/PDL involved.
    """

    champion_id: int
    rank: int
    avg_place: float
    games: int


@dataclass(slots=True)
class ChampionStatView:
    """One per-champion aggregate row for the profile (UI-safe; no winrate field)."""

    champion_id: int
    games: int
    first_rate: int  # % first place (placement == 1), 0..100
    top_half_rate: int  # % top-half finishes, 0..100
    avg_place: float
    cr_impact: int  # net CR contribution (rounded)
    spark: list[int]  # last-10 placements (most-recent last)


@dataclass(slots=True)
class HeadToHeadView:
    """Aggregate vs. another player across shared matches."""

    other_player_id: str
    games: int
    winrate: int  # 0..100 — share of shared matches the subject won
    synergy: str  # "duo" | "rival"


@dataclass(slots=True)
class StreakView:
    current_streak: int  # + wins / - losses (mirrors player_seasons)
    kind: str  # "vitorias" | "derrotas" | "neutro" (PT-BR)
    length: int  # absolute streak length


@dataclass(slots=True)
class WinLossView:
    """Real W/L aggregate for one player over a season (UI-safe, placement-derived).

    A "win" is a top-half finish for the match's mode (DUOS 8 teams -> placement
    <= 4, TRIOS 6 teams -> placement <= 3). ``top4_count`` is the raw count of the
    placement<=4 band (always <= ``games``); ``top4`` is that count as an integer
    percentage of games (``round(100 * top4_count / games)``, so always <= 100).
    ``winrate`` is the integer percentage of wins over games; ``losses`` is the
    remainder. No augment/item winrate is involved — placement facts only.
    """

    player_id: str
    games: int
    wins: int
    losses: int
    winrate: int  # 0..100 — round(wins / games * 100)
    top4: int  # 0..100 — round(top4_count / games * 100), guaranteed <= 100
    top4_count: int  # raw count of placement <= 4 finishes (always <= games)
    first_rate: int  # 0..100 — round(firsts / games * 100); true 1st-place (placement==1) rate


@dataclass(slots=True)
class ChampionTierRow:
    """One GLOBAL per-champion aggregate for the ``/champions`` tierlist.

    Aggregated from ``match_participants`` (placement source of truth), season-scoped
    via a ``matches`` join. ToS: placement-derived only (first-place rate, top-4
    rate, average placement, pick share) — never augment/item winrate.
    """

    champion_id: int
    games: int
    first_rate: int  # % of games finished 1st (placement == 1), 0..100
    top4_rate: int  # % of games finished in the top-4 band (placement <= 4), 0..100
    avg_place: float
    pick_rate: float  # % of all champion-games this champion accounts for, 0..100


@dataclass(slots=True)
class ChampionBestPlayer:
    """A reference main for one champion — the season's busiest player on it.

    Sourced from the pre-aggregated ``champion_stats`` table (the champion-first
    index ``ix_champion_stats_champion_season_games`` orders this scan). ``winrate``
    is the top-half (Arena "win") rate on the champion; placement-derived only
    (ToS): no augment/item winrate. Display name/icon are hydrated by the router.
    """

    champion_id: int
    player_id: str
    games: int
    winrate: int  # 0..100 — top-half finishes / games on this champion
    avg_place: float


@dataclass(slots=True)
class ChampionSynergyRow:
    """A champion pair that shared a subteam, aggregated over the season.

    Derived from ``match_participants`` self-joined on ``(match_id, team_id)`` — two
    champions on the same Arena subteam. ``win_rate`` is the pair's top-half rate
    (both members share the subteam placement). Placement-derived only (ToS).
    """

    champion_a: int
    champion_b: int
    games: int
    win_rate: int  # 0..100 — top-half (placement <= 4) finishes / games
    first_rate: int  # 0..100 — 1st-place finishes / games
    avg_place: float


@dataclass(slots=True)
class ChampionSynergyGroupRow:
    """A champion subteam (duo/trio) that shared a team, aggregated over the season.

    The N-champion generalization of :class:`ChampionSynergyRow`: ``champions`` is
    the combo ordered by championId asc (2 = duo, 3 = trio). All members share the
    subteam placement, so ``win_rate`` is the combo's top-half rate. ToS: never
    augment/item winrate.
    """

    champions: tuple[int, ...]
    games: int
    win_rate: int  # 0..100 — top-half (placement <= 4) finishes / games
    first_rate: int  # 0..100 — 1st-place finishes / games
    avg_place: float


@dataclass(slots=True)
class ChampionTrendPointView:
    """One day of a champion's trend, from the ``champion_daily_stats`` rollup."""

    date: str  # ISO date "2026-07-20"
    top4: int  # 0..100 — top-half rate that day
    first: int  # 0..100 — 1st-place rate that day
    pick_rate: float  # 0..100 — share of the day's champion-games
    games: int


@dataclass(slots=True)
class RawRecord:
    """One season-highlight record before display hydration (router adds name/avatar)."""

    key: str  # streak | biggest_gain | most_today | first_rate | top4_rate
    label: str  # PT-BR display label
    value: str  # formatted value ("14", "+72", "42%")
    player_id: str  # record holder (hydrated to name/handle/avatar by the router)
    accent: str  # UI accent color hint


#: Display order of the season records. ``_compute_season_records`` emits them in
#: this order; reading them back out of ``season_record_cache`` (an unordered set
#: of rows) re-imposes it so the rail's rotation doesn't shuffle between ticks.
_RECORD_ORDER = ("streak", "biggest_gain", "most_today", "first_rate", "top4_rate")


class StatsService:
    """Stateless; every method takes an :class:`AsyncSession`."""

    # -- champion stats ----------------------------------------------------

    async def champion_stats(
        self,
        session: AsyncSession,
        *,
        player_id: str,
        season_id: str,
        limit: int = 50,
    ) -> list[ChampionStatView]:
        """Per-champion profile rows, busiest champion first.

        Derived from the pre-aggregated ``champion_stats`` table (maintained by
        the rating service), so this is index-only and cheap.
        """
        rows = await session.execute(
            select(m.ChampionStat)
            .where(
                m.ChampionStat.player_id == player_id,
                m.ChampionStat.season_id == season_id,
            )
            .order_by(m.ChampionStat.matches_played.desc())
            .limit(limit)
        )
        out: list[ChampionStatView] = []
        for cs in rows.scalars():
            games = cs.matches_played or 0
            if games == 0:
                continue
            top_half_rate = round(100 * (cs.top_half or 0) / games)
            out.append(
                ChampionStatView(
                    champion_id=cs.champion_id,
                    games=games,
                    first_rate=self._first_rate(cs),
                    top_half_rate=top_half_rate,
                    avg_place=round((cs.total_placement_sum or 0) / games, 2),
                    cr_impact=round(cs.cr_delta_sum or 0.0),
                    spark=list(cs.last10_placements or []),
                )
            )
        return out

    @staticmethod
    def _tier_rows(
        rows: Iterable[Any], *, first_col: str = "firsts", place_col: str = "place_sum"
    ) -> list[ChampionTierRow]:
        """Shared projection for both tierlist sources — identical arithmetic.

        ``champion_tierlist`` (rollup) and ``_champion_tierlist_live`` (raw scan)
        must produce byte-identical rows; keeping the rounding in ONE place is what
        makes that guarantee mechanical rather than a promise. ``pick_rate`` is each
        champion's share of the floor-qualified champion-games.
        """
        materialized = list(rows)
        total_games = sum(int(r.games or 0) for r in materialized) or 1
        out: list[ChampionTierRow] = []
        for r in materialized:
            g = int(r.games or 0)
            if g <= 0:
                continue
            out.append(
                ChampionTierRow(
                    champion_id=int(r.champion_id),
                    games=g,
                    first_rate=round(100 * int(getattr(r, first_col) or 0) / g),
                    top4_rate=round(100 * int(r.top4 or 0) / g),
                    avg_place=round(int(getattr(r, place_col) or 0) / g, 2),
                    pick_rate=round(100 * g / total_games, 1),
                )
            )
        return out

    async def champion_tierlist(
        self,
        session: AsyncSession,
        *,
        season_id: str,
        min_games: int = 3,
    ) -> list[ChampionTierRow]:
        """Global per-champion aggregate for the season (tierlist source).

        Reads the ``champion_daily_stats`` rollup: one indexed scan of a small flat
        table, summed per champion. This USED to scan ``match_participants``
        directly (see :meth:`_champion_tierlist_live`) — that query is what stacked
        per-request aggregation memory until the OOM killer took the API container
        on the t3.micro replica and forced the Caddy 503 on ``/champions``. The
        rollup carries ``first_place``, which is why it can replace the raw scan
        where ``champion_stats`` cannot (that table has no first-place counter — see
        :meth:`_first_rate`).

        There is deliberately NO fallback to the live scan when the rollup is empty:
        that fallback would fire exactly on a cold replica and reintroduce the
        outage. An empty rollup yields an empty tierlist (an honest empty state the
        router already renders) until ``champion_daily_maintenance`` first runs.

        A champion needs ``>= min_games`` season-wide to surface. ToS:
        placement-derived only.
        """
        cds = m.ChampionDailyStat.__table__
        games = func.sum(cds.c.games)
        stmt = (
            select(
                cds.c.champion_id.label("champion_id"),
                games.label("games"),
                func.sum(cds.c.first_place).label("firsts"),
                func.sum(cds.c.top4).label("top4"),
                func.sum(cds.c.placement_sum).label("place_sum"),
            )
            .where(cds.c.season_id == season_id)
            .group_by(cds.c.champion_id)
            .having(games >= min_games)
        )
        return self._tier_rows((await session.execute(stmt)).all())

    async def _champion_tierlist_live(
        self,
        session: AsyncSession,
        *,
        season_id: str,
        min_games: int = 3,
    ) -> list[ChampionTierRow]:
        """The pre-rollup tierlist scan — the ground truth the rollup must reproduce.

        **Never call this from a request handler.** It is the query that OOM-killed
        the API container on the replica (see :meth:`champion_tierlist`). It stays
        here as the parity oracle: the test suite asserts it agrees with the
        rollup-backed method row for row, which is the only real proof the
        materialization is correct.

        Aggregated from ``match_participants`` (the placement source of truth).
        Joins ``matches`` for season scoping (participants carry no season_id; the
        season's declared dates need not match played_at, so we scope by
        ``matches.season_id``, not a date window). Only ``eligible`` participants
        count (AFK/frozen excluded, mirroring the rating write) — the same predicate
        ``rebuild_champion_daily`` applies.
        """
        mp = m.MatchParticipant
        games = func.count()
        stmt = (
            select(
                mp.champion_id,
                games.label("games"),
                func.sum(case((mp.placement == 1, 1), else_=0)).label("firsts"),
                func.sum(case((mp.placement <= _TOP4_THRESHOLD, 1), else_=0)).label("top4"),
                func.sum(mp.placement).label("place_sum"),
            )
            .join(m.Match, m.Match.id == mp.match_id)
            .where(
                m.Match.season_id == season_id,
                mp.eligible.is_(True),
                mp.played_at >= _EPOCH,
            )
            .group_by(mp.champion_id)
            .having(games >= min_games)
        )
        return self._tier_rows((await session.execute(stmt)).all())

    async def champion_best_players(
        self,
        session: AsyncSession,
        *,
        season_id: str,
        champion_ids: Iterable[int] | None = None,
        per_champion: int = 1,
        min_games: int = 1,
    ) -> dict[int, list[ChampionBestPlayer]]:
        """The busiest ``per_champion`` reference mains per champion, in ONE query.

        Reads the pre-aggregated ``champion_stats`` table through the champion-first
        index (``ix_champion_stats_champion_season_games``) as a LATERAL top-N per
        champion: for each requested champion the index is walked and stopped after
        ``per_champion`` rows. ``winrate`` is the top-half ("win") rate.
        Placement-derived only (ToS): no augment/item winrate.

        The obvious formulation — ``row_number() OVER (PARTITION BY champion_id)``
        filtered to ``rn <= per_champion`` — is a trap at this table's size. The
        window has to materialize EVERY (player, champion) row for the season before
        the rank filter applies: measured on the live season that is 988k rows and
        946k shared buffers (~7.4 GB of buffer traffic) to return 173 rows, 851 ms
        with everything already cached. Peak sort memory stays small, so it is not
        an OOM the way the old participants scan was — but on the read replica
        (128 MB shared_buffers) those buffers are disk reads, not hits. The LATERAL
        form asks the index for exactly what it needs: ~1.4k buffers, ~5 ms.

        ``champion_ids`` is therefore effectively required for the cheap path; when
        it is omitted the champion list is taken from the ``champion_daily_stats``
        rollup (the same set the tierlist surfaces) rather than by scanning
        ``champion_stats`` for distinct ids.
        """
        cs = m.ChampionStat.__table__
        cds = m.ChampionDailyStat.__table__

        champs_sq: FromClause
        if champion_ids is not None:
            champ_set = {int(c) for c in champion_ids}
            if not champ_set:
                return {}
            # VALUES rather than unnest(): an untyped array bind makes PG raise
            # "function unnest(unknown) is not unique", and VALUES needs no cast.
            champs_sq = values(
                column("champion_id", Integer), name="c"
            ).data([(c,) for c in sorted(champ_set)])
        else:
            champs_sq = (
                select(cds.c.champion_id.label("champion_id"))
                .where(cds.c.season_id == season_id)
                .distinct()
                .subquery("c")
            )

        top = (
            select(
                cs.c.player_id.label("player_id"),
                cs.c.matches_played.label("games"),
                cs.c.top_half.label("top_half"),
                (
                    cast(cs.c.total_placement_sum, Float)
                    / func.nullif(cs.c.matches_played, 0)
                ).label("avg_place"),
            )
            .where(
                cs.c.season_id == season_id,
                cs.c.champion_id == champs_sq.c.champion_id,
                cs.c.matches_played >= min_games,
            )
            # player_id closes the tie: without it two mains with identical
            # (games, top_half) order arbitrarily and the champion's displayed
            # reference main can flip between requests.
            .order_by(
                cs.c.matches_played.desc(), cs.c.top_half.desc(), cs.c.player_id.asc()
            )
            .limit(per_champion)
            .lateral("top")
        )
        stmt = select(
            champs_sq.c.champion_id,
            top.c.player_id,
            top.c.games,
            top.c.top_half,
            top.c.avg_place,
        ).select_from(champs_sq.join(top, true()))
        rows = await session.execute(stmt)
        out: dict[int, list[ChampionBestPlayer]] = {}
        for champion_id, pid, games, top_half, avg_p in rows.all():
            g = int(games or 0)
            if g <= 0:
                continue
            out.setdefault(int(champion_id), []).append(
                ChampionBestPlayer(
                    champion_id=int(champion_id),
                    player_id=str(pid),
                    games=g,
                    winrate=round(100 * int(top_half or 0) / g),
                    avg_place=round(float(avg_p or 0.0), 2),
                )
            )
        return out

    async def champion_synergies(
        self,
        session: AsyncSession,
        *,
        season_id: str,
        min_games: int = SYNERGY_MIN_GAMES,
        limit: int = 40,
    ) -> list[ChampionSynergyRow]:
        """Top champion pairs that shared an Arena subteam, by Wilson lower bound.

        Thin pair-shaped view over :meth:`champion_synergies_n` (``size=2``), which
        reads the ``champion_combo_stats`` rollup. Kept as its own method because
        ``/champions/synergy`` is an older route with a pair-specific DTO
        (``champion_a``/``champion_b``) that predates the N-ary generalization.
        """
        groups = await self.champion_synergies_n(
            session, season_id=season_id, size=2, min_games=min_games, limit=limit
        )
        return [
            ChampionSynergyRow(
                champion_a=g.champions[0],
                champion_b=g.champions[1],
                games=g.games,
                win_rate=g.win_rate,
                first_rate=g.first_rate,
                avg_place=g.avg_place,
            )
            for g in groups
        ]

    async def _champion_synergies_live(
        self,
        session: AsyncSession,
        *,
        season_id: str,
        min_games: int = SYNERGY_MIN_GAMES,
        limit: int = 40,
    ) -> list[ChampionSynergyRow]:
        """The pre-rollup pair scan — parity oracle only, never a request path.

        Self-joins ``match_participants`` on ``(match_id, team_id)`` with
        ``a.champion_id < b.champion_id`` to form each unordered pair once. Both
        members share the subteam's placement, so ``a.placement`` measures the pair.
        Season-scoped via a ``matches`` join; only ``eligible`` participants count
        (mirrors the rating write) — the same predicate
        :meth:`rebuild_champion_combos` applies.

        **Never call this from a handler.** Measured on the live season: 8.0 s,
        63.5M shared buffers, ~285 MB spilled to temp. See
        :meth:`champion_synergies_n` for why that mattered.
        """
        a = aliased(m.MatchParticipant)
        b = aliased(m.MatchParticipant)
        games = func.count()
        top4 = func.sum(case((a.placement <= _TOP4_THRESHOLD, 1), else_=0))
        stmt = (
            select(
                a.champion_id.label("champion_a"),
                b.champion_id.label("champion_b"),
                games.label("games"),
                top4.label("top4"),
                func.sum(case((a.placement == 1, 1), else_=0)).label("firsts"),
                func.sum(a.placement).label("place_sum"),
            )
            .select_from(a)
            .join(
                b,
                and_(
                    a.match_id == b.match_id,
                    a.team_id == b.team_id,
                    a.champion_id < b.champion_id,
                ),
            )
            .join(m.Match, m.Match.id == a.match_id)
            .where(
                m.Match.season_id == season_id,
                a.eligible.is_(True),
                b.eligible.is_(True),
                a.played_at >= _EPOCH,
                b.played_at >= _EPOCH,
            )
            .group_by(a.champion_id, b.champion_id)
            .having(games >= min_games)
            .order_by(games.desc())
            .limit(_SYNERGY_POOL)
        )
        rows = (await session.execute(stmt)).all()
        ranked = sorted(
            (r for r in rows if int(r.games or 0) > 0),
            key=lambda r: (
                -_wilson_lower_bound(int(r.top4 or 0), int(r.games or 0)),
                -int(r.games or 0),
            ),
        )
        out: list[ChampionSynergyRow] = []
        for r in ranked[:limit]:
            g = int(r.games or 0)
            out.append(
                ChampionSynergyRow(
                    champion_a=int(r.champion_a),
                    champion_b=int(r.champion_b),
                    games=g,
                    win_rate=round(100 * int(r.top4 or 0) / g),
                    first_rate=round(100 * int(r.firsts or 0) / g),
                    avg_place=round(int(r.place_sum or 0) / g, 2),
                )
            )
        return out

    async def champion_synergies_n(
        self,
        session: AsyncSession,
        *,
        season_id: str,
        size: int = 2,
        min_games: int = SYNERGY_MIN_GAMES,
        limit: int = 40,
    ) -> list[ChampionSynergyGroupRow]:
        """Top champion subteams of ``size`` members, by Wilson lower bound.

        Reads the ``champion_combo_stats`` rollup through
        ``ix_champion_combo_stats_season_size_games``. This USED to self-join
        ``match_participants`` ``size`` times per request (see
        :meth:`_champion_synergies_n_live`) — measured on the live season that was
        8.0 s / 63.5M buffers / ~285 MB of temp spill for pairs and 19.1 s /
        ~530 MB for trios, i.e. WORSE than the participants scan that got the API
        container OOM-killed, and it sat outside the Caddy breaker that was
        protecting the other two routes.

        A combo needs ``>= min_games`` to surface; the floor-qualified pool is then
        ranked by the Wilson lower bound of the top-half rate (then games), so a
        perfect run over a handful of games never outranks a solid rate over a real
        sample. ``size`` is clamped to 2..3 (Arena teams are 2 or 3).

        The rollup carries its own WRITE floor (``settings.synergy_combo_min_games``)
        which drops the long tail no read can reach. Asking for ``min_games`` BELOW
        that floor cannot be satisfied from the rollup — the rows simply are not
        there — so it is clamped up, and the caller gets a consistent (if stricter)
        answer rather than a silently truncated one. Empty until
        ``champion_combo_maintenance`` first runs; as with the tierlist there is
        deliberately no fallback to the live self-join. Placement-derived (ToS).
        """
        size = max(2, min(size, 3))
        floor = max(int(min_games), settings.synergy_combo_min_games)
        ccs = m.ChampionComboStat.__table__
        stmt = (
            select(
                ccs.c.c0, ccs.c.c1, ccs.c.c2, ccs.c.games, ccs.c.top4,
                ccs.c.first_place, ccs.c.placement_sum,
            )
            .where(
                ccs.c.season_id == season_id,
                ccs.c.size == size,
                ccs.c.games >= floor,
            )
            .order_by(ccs.c.games.desc())
            .limit(_SYNERGY_POOL)
        )
        rows = (await session.execute(stmt)).all()
        ranked = sorted(
            (r for r in rows if int(r.games or 0) > 0),
            key=lambda r: (
                -_wilson_lower_bound(int(r.top4 or 0), int(r.games or 0)),
                -int(r.games or 0),
            ),
        )
        out: list[ChampionSynergyGroupRow] = []
        for r in ranked[:limit]:
            g = int(r.games or 0)
            champs = (int(r.c0), int(r.c1)) if size == 2 else (int(r.c0), int(r.c1), int(r.c2))
            out.append(
                ChampionSynergyGroupRow(
                    champions=champs,
                    games=g,
                    win_rate=round(100 * int(r.top4 or 0) / g),
                    first_rate=round(100 * int(r.first_place or 0) / g),
                    avg_place=round(int(r.placement_sum or 0) / g, 2),
                )
            )
        return out

    async def rebuild_champion_combos(
        self, session: AsyncSession, *, season_id: str, min_games: int | None = None
    ) -> int:
        """Recompute the whole season's synergy rollup (both sizes). Cron-only.

        Delete-then-insert for the season, so re-running converges and a combo that
        stops qualifying disappears. Unlike :meth:`rebuild_champion_daily` this
        CANNOT be windowed: the rollup is cumulative per season, so a partial
        recompute would produce wrong totals. That makes it the expensive tick —
        hourly, not every 15 minutes.

        ``min_games`` is the WRITE floor (default ``settings.synergy_combo_min_games``):
        the long tail is dropped because no read can reach it (the read floor,
        ``SYNERGY_MIN_GAMES``, is far higher). On the live season it takes trios
        from ~309k rows to ~21k. Returns rows written. The caller commits.
        """
        floor = settings.synergy_combo_min_games if min_games is None else min_games
        ccs = m.ChampionComboStat
        await session.execute(delete(ccs).where(ccs.season_id == season_id))

        written = 0
        for size in (2, 3):
            parts = [aliased(m.MatchParticipant) for _ in range(size)]
            anchor = parts[0]
            games = func.count()
            # c2 sentinel for pairs: 0 = absent (champion ids are positive), which
            # keeps the PK NOT NULL — a nullable column cannot sit in a PK.
            cols: list[Any] = [p.champion_id for p in parts]
            if size == 2:
                cols.append(literal(0))
            src = select(
                m.Match.season_id.label("season_id"),
                literal(size).label("size"),
                cols[0].label("c0"),
                cols[1].label("c1"),
                cols[2].label("c2"),
                games.label("games"),
                func.sum(case((anchor.placement <= _TOP4_THRESHOLD, 1), else_=0)).label("top4"),
                func.sum(case((anchor.placement == 1, 1), else_=0)).label("first_place"),
                func.sum(anchor.placement).label("placement_sum"),
            ).select_from(anchor)
            for i in range(1, size):
                prev, cur = parts[i - 1], parts[i]
                src = src.join(
                    cur,
                    and_(
                        cur.match_id == anchor.match_id,
                        cur.team_id == anchor.team_id,
                        prev.champion_id < cur.champion_id,
                    ),
                )
            src = (
                src.join(m.Match, m.Match.id == anchor.match_id)
                .where(
                    m.Match.season_id == season_id,
                    *[p.eligible.is_(True) for p in parts],
                    *[p.played_at >= _EPOCH for p in parts],
                )
                .group_by(m.Match.season_id, *[p.champion_id for p in parts])
                .having(games >= floor)
            )
            result = await session.execute(
                insert(ccs).from_select(
                    [
                        "season_id", "size", "c0", "c1", "c2",
                        "games", "top4", "first_place", "placement_sum",
                    ],
                    src,
                )
            )
            written += int(getattr(result, "rowcount", 0) or 0)
        return written

    async def _champion_synergies_n_live(
        self,
        session: AsyncSession,
        *,
        season_id: str,
        size: int = 2,
        min_games: int = SYNERGY_MIN_GAMES,
        limit: int = 40,
    ) -> list[ChampionSynergyGroupRow]:
        """The pre-rollup self-join — parity oracle only, never a request path.

        Self-joins ``match_participants`` ``size`` times on ``(match_id, team_id)``
        with a strictly increasing ``champion_id`` chain (``c0 < c1 < ... <
        c{size-1}``), so each unordered combo forms exactly once. All members share
        the subteam's placement, so the anchor participant measures the combo.

        **Never call this from a handler** — this is the 8–19 s, hundreds-of-MB-of-
        temp-spill query :meth:`champion_synergies_n` was materialized to avoid. It
        stays as the oracle the test suite diffs the rollup against.
        """
        size = max(2, min(size, 3))
        parts = [aliased(m.MatchParticipant) for _ in range(size)]
        anchor = parts[0]
        games = func.count()
        top4 = func.sum(case((anchor.placement <= _TOP4_THRESHOLD, 1), else_=0))
        stmt = select(
            *[p.champion_id.label(f"c{i}") for i, p in enumerate(parts)],
            games.label("games"),
            top4.label("top4"),
            func.sum(case((anchor.placement == 1, 1), else_=0)).label("firsts"),
            func.sum(anchor.placement).label("place_sum"),
        ).select_from(anchor)
        # Chain the remaining members: same subteam, strictly increasing champ id.
        for i in range(1, size):
            prev, cur = parts[i - 1], parts[i]
            stmt = stmt.join(
                cur,
                and_(
                    cur.match_id == anchor.match_id,
                    cur.team_id == anchor.team_id,
                    prev.champion_id < cur.champion_id,
                ),
            )
        stmt = (
            stmt.join(m.Match, m.Match.id == anchor.match_id)
            .where(
                m.Match.season_id == season_id,
                *[p.eligible.is_(True) for p in parts],
                *[p.played_at >= _EPOCH for p in parts],
            )
            .group_by(*[p.champion_id for p in parts])
            .having(games >= min_games)
            .order_by(games.desc())
            .limit(_SYNERGY_POOL)
        )
        rows = (await session.execute(stmt)).all()
        ranked = sorted(
            (r for r in rows if int(r.games or 0) > 0),
            key=lambda r: (
                -_wilson_lower_bound(int(r.top4 or 0), int(r.games or 0)),
                -int(r.games or 0),
            ),
        )
        out: list[ChampionSynergyGroupRow] = []
        for r in ranked[:limit]:
            g = int(r.games or 0)
            champs = tuple(int(getattr(r, f"c{i}")) for i in range(size))
            out.append(
                ChampionSynergyGroupRow(
                    champions=champs,
                    games=g,
                    win_rate=round(100 * int(r.top4 or 0) / g),
                    first_rate=round(100 * int(r.firsts or 0) / g),
                    avg_place=round(int(r.place_sum or 0) / g, 2),
                )
            )
        return out

    # -- champion daily rollup (B1/B2: tierlist + trend charts + 7d delta) -----

    async def rebuild_champion_daily(
        self, session: AsyncSession, *, season_id: str, since: date
    ) -> int:
        """Recompute + replace the per-champion daily rollup for days ``>= since``.

        Aggregates eligible ``match_participants`` by ``(played_at::date,
        champion)`` for the season and writes ``champion_daily_stats``. Delete-then-
        insert over the recent window makes it idempotent: re-running as late
        matches land keeps a day accurate (a day's aggregate grows as matches
        arrive). The caller commits. Returns rows inserted. Placement-derived (ToS).

        The ``eligible`` predicate here MUST match
        :meth:`_champion_tierlist_live`'s — that equality is what makes the
        rollup-backed tierlist exact rather than approximate.
        """
        mp = m.MatchParticipant
        since_dt = datetime(since.year, since.month, since.day, tzinfo=UTC)
        # UTC-explicit day so the cron and the migration backfill bucket a match
        # to the SAME date regardless of the DB session timezone.
        day = cast(func.timezone("UTC", mp.played_at), Date)
        src = (
            select(
                day.label("snapshot_date"),
                m.Match.season_id.label("season_id"),
                mp.champion_id.label("champion_id"),
                func.count().label("games"),
                func.sum(case((mp.placement <= _TOP4_THRESHOLD, 1), else_=0)).label("top4"),
                func.sum(case((mp.placement == 1, 1), else_=0)).label("first_place"),
                func.sum(mp.placement).label("placement_sum"),
            )
            .join(m.Match, m.Match.id == mp.match_id)
            .where(
                m.Match.season_id == season_id,
                mp.eligible.is_(True),
                mp.played_at >= since_dt,
            )
            .group_by(day, m.Match.season_id, mp.champion_id)
        )
        cds = m.ChampionDailyStat
        await session.execute(
            delete(cds).where(cds.season_id == season_id, cds.snapshot_date >= since)
        )
        result = await session.execute(
            insert(cds).from_select(
                [
                    "snapshot_date",
                    "season_id",
                    "champion_id",
                    "games",
                    "top4",
                    "first_place",
                    "placement_sum",
                ],
                src,
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def champion_trend(
        self, session: AsyncSession, *, season_id: str, champion_id: int, days: int = 30
    ) -> list[ChampionTrendPointView]:
        """A champion's daily top-half / 1st / pick rate over the last ``days``.

        Reads the ``champion_daily_stats`` rollup (cheap indexed scan) instead of
        re-aggregating raw participants. Pick-rate = the champion's daily games
        over the day's total champion-games (a second grouped read). Empty before
        the rollup has history for this champion. Placement-derived (ToS).
        """
        cds = m.ChampionDailyStat.__table__
        cutoff = (datetime.now(UTC) - timedelta(days=days)).date()
        champ_rows = (
            await session.execute(
                select(
                    cds.c.snapshot_date,
                    cds.c.games,
                    cds.c.top4,
                    cds.c.first_place,
                )
                .where(
                    cds.c.season_id == season_id,
                    cds.c.champion_id == champion_id,
                    cds.c.snapshot_date >= cutoff,
                )
                .order_by(cds.c.snapshot_date.asc())
            )
        ).all()
        if not champ_rows:
            return []
        totals = {
            r.snapshot_date: int(r.total or 0)
            for r in (
                await session.execute(
                    select(cds.c.snapshot_date, func.sum(cds.c.games).label("total"))
                    .where(cds.c.season_id == season_id, cds.c.snapshot_date >= cutoff)
                    .group_by(cds.c.snapshot_date)
                )
            ).all()
        }
        out: list[ChampionTrendPointView] = []
        for r in champ_rows:
            g = int(r.games or 0)
            if g <= 0:
                continue
            total = totals.get(r.snapshot_date, 0)
            out.append(
                ChampionTrendPointView(
                    date=r.snapshot_date.isoformat(),
                    top4=round(100 * int(r.top4 or 0) / g),
                    first=round(100 * int(r.first_place or 0) / g),
                    pick_rate=round(100 * g / total, 1) if total > 0 else 0.0,
                    games=g,
                )
            )
        return out

    async def champion_winrate_delta7d(
        self,
        session: AsyncSession,
        *,
        season_id: str,
        champion_ids: Iterable[int] | None = None,
    ) -> dict[int, int]:
        """Per-champion top-half delta (pp): last 7d vs the prior 7d, batched.

        One grouped scan over the 14-day window of ``champion_daily_stats`` keyed
        by champion (no N+1). Absent champions (or ones missing either window)
        default to 0 via :func:`_delta_pp`. Feeds ``ChampRow.winrateDelta`` on the
        ``/champions`` tierlist. Placement-derived (ToS).
        """
        cds = m.ChampionDailyStat.__table__
        today = datetime.now(UTC).date()
        d7 = today - timedelta(days=7)
        d14 = today - timedelta(days=14)
        in_recent = cds.c.snapshot_date >= d7
        in_prior = and_(cds.c.snapshot_date >= d14, cds.c.snapshot_date < d7)
        conds = [cds.c.season_id == season_id, cds.c.snapshot_date >= d14]
        if champion_ids is not None:
            ids = {int(x) for x in champion_ids}
            if not ids:
                return {}
            conds.append(cds.c.champion_id.in_(ids))
        stmt = (
            select(
                cds.c.champion_id.label("champion_id"),
                func.sum(case((in_recent, cds.c.top4), else_=0)).label("rt"),
                func.sum(case((in_recent, cds.c.games), else_=0)).label("rg"),
                func.sum(case((in_prior, cds.c.top4), else_=0)).label("pt"),
                func.sum(case((in_prior, cds.c.games), else_=0)).label("pg"),
            )
            .where(*conds)
            .group_by(cds.c.champion_id)
        )
        out: dict[int, int] = {}
        for r in (await session.execute(stmt)).all():
            out[int(r.champion_id)] = _delta_pp(
                int(r.rt or 0), int(r.rg or 0), int(r.pt or 0), int(r.pg or 0)
            )
        return out

    async def season_activity(
        self, session: AsyncSession, *, season_id: str, days: int = 10
    ) -> list[tuple[str, int]]:
        """Ranked matches processed per day for the season (rail activity chart).

        Returns ``[(day_of_month_label, count)]`` in chronological order for the most
        recent ``days`` days that have matches. Sparse by design — only days with
        real matches appear (no fabricated bars).
        """
        day = func.date(m.Match.played_at)
        stmt = (
            select(day.label("d"), func.count().label("c"))
            .where(m.Match.season_id == season_id)
            .group_by(day)
            .order_by(day.desc())
            .limit(days)
        )
        rows = (await session.execute(stmt)).all()
        out: list[tuple[str, int]] = []
        for r in reversed(rows):  # chronological (oldest first)
            d = r.d
            label = d.strftime("%d") if hasattr(d, "strftime") else str(d)[-2:]
            out.append((label, int(r.c or 0)))
        return out

    async def season_records(
        self, session: AsyncSession, *, season_id: str
    ) -> list[RawRecord]:
        """Season highlight records, read from the ``season_record_cache`` table.

        A plain indexed read of at most 5 rows. This USED to compute the records
        inline (see :meth:`_compute_season_records`) — a GROUP BY over every
        eligible participant in the season, materializing ~127k players, plus an
        unindexed sort on ``cr_delta``. That was the second route the OOM killer
        took down on the t3.micro replica, and the reason ``/meta/records`` sits
        behind a Caddy 503 today.

        Empty until ``season_records_maintenance`` first runs — an honest empty
        state the router already renders. As with the champion tierlist, there is
        deliberately no fallback to the live computation.
        """
        src = m.SeasonRecordCache.__table__
        rows = (
            await session.execute(
                select(
                    src.c.key, src.c.label, src.c.value, src.c.player_id, src.c.accent
                ).where(src.c.season_id == season_id)
            )
        ).all()
        by_key = {
            r.key: RawRecord(r.key, r.label, r.value, str(r.player_id), r.accent) for r in rows
        }
        # Stable display order, independent of however the rows came back.
        return [by_key[k] for k in _RECORD_ORDER if k in by_key]

    async def _compute_season_records(
        self, session: AsyncSession, *, season_id: str, min_games: int = 5
    ) -> list[RawRecord]:
        """Compute the season highlight records from scratch — cron-only.

        **Never call this from a request handler.** It is the expensive
        computation :meth:`season_records` was materialized to avoid; the
        ``season_records_maintenance`` cron runs it on the primary and writes the
        result to ``season_record_cache``.

        Each record names the record-holder's ``player_id`` (the router hydrates the
        display name/avatar). Records with no qualifying data are omitted. ToS: only
        placement / CR-delta facts — no augment/item winrate.
        """
        mp = m.MatchParticipant
        out: list[RawRecord] = []

        # 1) Biggest current win streak (player_seasons.current_streak).
        streak = (
            await session.execute(
                select(m.PlayerSeason.player_id, m.PlayerSeason.current_streak)
                .where(m.PlayerSeason.season_id == season_id, m.PlayerSeason.current_streak > 0)
                .order_by(m.PlayerSeason.current_streak.desc())
                .limit(1)
            )
        ).first()
        if streak is not None:
            out.append(
                RawRecord("streak", "Maior sequência de vitórias",
                          str(int(streak.current_streak)), str(streak.player_id), "#ff8a3b")
            )

        # 2) Biggest single-match CR gain (match_participants.cr_delta).
        gain = (
            await session.execute(
                select(mp.player_id, mp.cr_delta)
                .join(m.Match, m.Match.id == mp.match_id)
                .where(m.Match.season_id == season_id, mp.eligible.is_(True))
                .order_by(mp.cr_delta.desc())
                .limit(1)
            )
        ).first()
        if gain is not None and (gain.cr_delta or 0) > 0:
            out.append(
                RawRecord("biggest_gain", "Maior ganho numa partida",
                          f"+{round(gain.cr_delta)}", str(gain.player_id), "var(--green)")
            )

        # 3) Most ranked matches today.
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        most_today = (
            await session.execute(
                select(mp.player_id, func.count().label("c"))
                .join(m.Match, m.Match.id == mp.match_id)
                .where(m.Match.season_id == season_id, mp.eligible.is_(True), mp.played_at >= today)
                .group_by(mp.player_id)
                .order_by(func.count().desc())
                .limit(1)
            )
        ).first()
        if most_today is not None and int(most_today.c or 0) > 0:
            out.append(
                RawRecord("most_today", "Mais partidas hoje",
                          str(int(most_today.c)), str(most_today.player_id), "var(--primary-bright)")
            )

        # 4+5) Highest first-place / top-4 rate (per-player placement agg, min games).
        agg = (
            await session.execute(
                select(
                    mp.player_id,
                    func.count().label("games"),
                    func.sum(case((mp.placement == 1, 1), else_=0)).label("firsts"),
                    func.sum(case((mp.placement <= _TOP4_THRESHOLD, 1), else_=0)).label("top4"),
                )
                .join(m.Match, m.Match.id == mp.match_id)
                .where(m.Match.season_id == season_id, mp.eligible.is_(True), mp.played_at >= _EPOCH)
                .group_by(mp.player_id)
                .having(func.count() >= min_games)
            )
        ).all()
        if agg:
            best_first = max(agg, key=lambda r: (r.firsts or 0) / (r.games or 1))
            out.append(
                RawRecord("first_rate", "Maior taxa de 1º lugar",
                          f"{round(100 * (best_first.firsts or 0) / int(best_first.games))}%",
                          str(best_first.player_id), "var(--gold-bright)")
            )
            best_top4 = max(agg, key=lambda r: (r.top4 or 0) / (r.games or 1))
            out.append(
                RawRecord("top4_rate", "Maior taxa de Top 4",
                          f"{round(100 * (best_top4.top4 or 0) / int(best_top4.games))}%",
                          str(best_top4.player_id), "var(--primary-bright)")
            )
        return out

    async def rebuild_season_records(
        self, session: AsyncSession, *, season_id: str
    ) -> int:
        """Recompute the season records and replace the cached rows. Cron-only.

        Delete-then-insert over the season's (at most 5) rows, mirroring
        :meth:`rebuild_champion_daily`'s idempotency: re-running always converges
        on the current truth, and a record that stops qualifying disappears rather
        than lingering. The caller commits. Returns rows written.
        """
        records = await self._compute_season_records(session, season_id=season_id)
        src = m.SeasonRecordCache
        await session.execute(delete(src).where(src.season_id == season_id))
        if not records:
            return 0
        await session.execute(
            insert(src),
            [
                {
                    "season_id": season_id,
                    "key": r.key,
                    "label": r.label,
                    "value": r.value,
                    "player_id": r.player_id,
                    "accent": r.accent,
                }
                for r in records
            ],
        )
        return len(records)

    @staticmethod
    def _first_rate(cs: m.ChampionStat) -> int:
        """% of finishes in first place.

        ``champion_stats`` keeps no dedicated first-place counter, so we
        approximate from the trailing placement window when present (recent
        form) and fall back to wins/games otherwise. A precise lifetime figure
        is available via ``match_participants`` if ever required.
        """
        window = list(cs.last10_placements or [])
        if window:
            return round(100 * sum(1 for p in window if p == 1) / len(window))
        games = cs.matches_played or 0
        return round(100 * (cs.wins or 0) / games) if games else 0

    # -- head-to-head ------------------------------------------------------

    async def head_to_head(
        self,
        session: AsyncSession,
        *,
        player_id: str,
        other_player_id: str,
        since: datetime | None = None,
    ) -> HeadToHeadView:
        """Win rate and relationship vs. ``other_player_id`` over shared matches.

        Self-joins ``match_participants`` on ``match_id`` (the
        ``(player_id, match_id)`` index supports the A∩B path, §8.2). The subject
        "won" a shared match when their placement was better-or-equal. ``synergy``
        is ``duo`` when they were mostly on the same team, else ``rival``.
        """
        floor = since or _EPOCH
        a = m.MatchParticipant.__table__.alias("a")
        b = m.MatchParticipant.__table__.alias("b")

        subject_win = a.c.placement <= b.c.placement
        same_team = a.c.team_id == b.c.team_id

        stmt = (
            select(
                func.count().label("games"),
                func.coalesce(func.sum(func.cast(subject_win, Integer)), 0).label("wins"),
                func.coalesce(func.sum(func.cast(same_team, Integer)), 0).label("together"),
            )
            .select_from(a.join(b, a.c.match_id == b.c.match_id))
            .where(
                a.c.player_id == player_id,
                b.c.player_id == other_player_id,
                a.c.played_at >= floor,
                b.c.played_at >= floor,
            )
        )
        row = (await session.execute(stmt)).one()
        games = int(row.games or 0)
        if games == 0:
            return HeadToHeadView(
                other_player_id=other_player_id, games=0, winrate=0, synergy="rival"
            )
        wins = int(row.wins or 0)
        together = int(row.together or 0)
        return HeadToHeadView(
            other_player_id=other_player_id,
            games=games,
            winrate=round(100 * wins / games),
            synergy="duo" if together * 2 >= games else "rival",
        )

    # -- streak ------------------------------------------------------------

    async def streak(self, session: AsyncSession, *, player_id: str, season_id: str) -> StreakView:
        """Current streak straight from ``player_seasons`` (maintained on write).

        Positive = consecutive wins, negative = consecutive losses, 0 = neutral.
        ``kind`` is PT-BR for direct UI use.
        """
        cur = await session.execute(
            select(m.PlayerSeason.current_streak).where(
                m.PlayerSeason.player_id == player_id,
                m.PlayerSeason.season_id == season_id,
            )
        )
        value = cur.scalar_one_or_none() or 0
        if value > 0:
            kind = "vitorias"
        elif value < 0:
            kind = "derrotas"
        else:
            kind = "neutro"
        return StreakView(current_streak=value, kind=kind, length=abs(value))

    # -- real win/loss (placement-derived, mode-aware) ---------------------

    async def win_loss_by_player(
        self,
        session: AsyncSession,
        *,
        season_id: str,
        player_ids: Iterable[str],
        since: datetime | None = None,
    ) -> dict[str, WinLossView]:
        """Real per-player {wins, losses, winrate, top4} for a season, in ONE query.

        This is the leaderboard's batch helper: pass the page's ``player_ids`` and
        get a ``{player_id: WinLossView}`` map back from a single grouped SQL
        aggregate (no N+1). A "win" is a top-half finish for that match's mode
        (``placement <= teamCount // 2`` — DUOS/8 -> <=4, TRIOS/6 -> <=3); ``top4``
        is the fixed ``placement <= 4`` band; ``winrate = round(wins/games*100)``;
        ``losses = games - wins``.

        ``teamCount`` is derived per match from ``matches.mode`` (the authoritative
        per-match shape) via a join on ``match_id`` + the season partition key, so
        a mixed DUOS/TRIOS history is scored correctly. The ``played_at >= floor``
        predicate keeps the ``match_participants`` HASH-partition + ``(player_id,
        played_at DESC)`` index path (Trinity #2/#10) and prunes the matches
        season partition.

        Returns an empty map for an empty ``player_ids`` (no query is issued).
        Players with no eligible games simply do not appear in the map; callers
        degrade those to zeroed counters.
        """
        ids = [str(pid) for pid in player_ids]
        if not ids:
            return {}

        floor = since or _EPOCH
        mp = m.MatchParticipant.__table__
        mt = m.Match.__table__

        # Per-mode "win" threshold = teamCount // 2 (top-half finish), derived
        # from the match's own mode so a mixed DUOS/TRIOS history scores right:
        #   DUOS  (8 teams) -> placement <= 4
        #   TRIOS (6 teams) -> placement <= 3
        # Precomputed as integer literals (no SQL division) to avoid numeric /
        # integer coercion ambiguity. Default to TRIOS for any unknown mode.
        win_threshold = case(
            (mt.c.mode == m.RatingMode.DUOS, _TEAM_COUNT_BY_MODE[m.RatingMode.DUOS] // 2),
            (mt.c.mode == m.RatingMode.TRIOS, _TEAM_COUNT_BY_MODE[m.RatingMode.TRIOS] // 2),
            else_=_TEAM_COUNT_BY_MODE[m.RatingMode.TRIOS] // 2,
        )
        is_win = mp.c.placement <= win_threshold
        is_top4 = mp.c.placement <= _TOP4_THRESHOLD
        is_first = mp.c.placement == 1

        stmt = (
            select(
                mp.c.player_id.label("player_id"),
                func.count().label("games"),
                func.coalesce(func.sum(func.cast(is_win, Integer)), 0).label("wins"),
                func.coalesce(func.sum(func.cast(is_top4, Integer)), 0).label("top4"),
                func.coalesce(func.sum(func.cast(is_first, Integer)), 0).label("firsts"),
            )
            .select_from(
                mp.join(
                    mt,
                    (mp.c.match_id == mt.c.id) & (mt.c.season_id == season_id),
                )
            )
            .where(
                mp.c.player_id.in_(ids),
                mp.c.played_at >= floor,
                mt.c.played_at >= floor,
            )
            .group_by(mp.c.player_id)
        )

        out: dict[str, WinLossView] = {}
        for row in (await session.execute(stmt)).all():
            games = int(row.games or 0)
            if games == 0:
                continue
            wins = int(row.wins or 0)
            top4_count = int(row.top4 or 0)
            firsts = int(row.firsts or 0)
            out[str(row.player_id)] = WinLossView(
                player_id=str(row.player_id),
                games=games,
                wins=wins,
                losses=games - wins,
                winrate=round(100 * wins / games),
                top4=round(100 * top4_count / games),
                top4_count=top4_count,
                first_rate=round(100 * firsts / games),
            )
        return out

    # -- current top-1 streak (consecutive placement==1, "on fire" table row) ---

    async def top1_streak_by_player(
        self,
        session: AsyncSession,
        *,
        season_id: str,
        player_ids: Iterable[str],
    ) -> dict[str, int]:
        """Per-player count of consecutive 1st-place finishes from the latest match.

        The leaderboard's "on fire" signal: a player whose most recent matches are
        an unbroken run of first places (``placement == 1``) earns the animated
        table row once the run reaches 3+. The streak is measured from each
        player's latest match going back, breaking at the first non-first finish.

        One windowed query: ``ROW_NUMBER() OVER (PARTITION BY player ORDER BY
        played_at DESC)`` numbers each player's matches newest-first; the streak is
        ``MIN(rn WHERE placement != 1) - 1`` (position of the first break minus
        one), or the player's total game count when every finish is first place (no
        break → ``MIN`` is NULL → coalesce to ``COUNT(*)``). Players with no
        eligible games are absent from the map (callers treat a missing key as 0).
        The ``played_at >= _EPOCH`` floor keeps the Trinity hash-partition prune +
        ``(player_id, played_at DESC)`` index path (#2/#10).
        """
        ids = [str(pid) for pid in player_ids]
        if not ids:
            return {}

        mp = m.MatchParticipant.__table__
        mt = m.Match.__table__
        ranked = (
            select(
                mp.c.player_id.label("player_id"),
                mp.c.placement.label("placement"),
                func.row_number()
                .over(
                    partition_by=mp.c.player_id,
                    order_by=mp.c.played_at.desc(),
                )
                .label("rn"),
            )
            .select_from(
                mp.join(
                    mt,
                    (mp.c.match_id == mt.c.id) & (mt.c.season_id == season_id),
                )
            )
            .where(
                mp.c.player_id.in_(ids),
                mp.c.played_at >= _EPOCH,
                mt.c.played_at >= _EPOCH,
            )
        ).subquery()

        stmt = select(
            ranked.c.player_id.label("player_id"),
            func.coalesce(
                func.min(case((ranked.c.placement != 1, ranked.c.rn))) - 1,
                func.count(),
            ).label("streak"),
        ).group_by(ranked.c.player_id)

        return {str(pid): int(streak or 0) for pid, streak in (await session.execute(stmt)).all()}

    # -- delta7d (CR change over ~7 days, from the cr_snapshots hypertable) -----

    async def delta7d_by_player(
        self,
        session: AsyncSession,
        *,
        season_id: str,
        player_ids: Iterable[str],
        now: datetime | None = None,
    ) -> dict[str, int]:
        """Per-player signed CR change over the last ~7 days, in ONE query.

        ``delta7d = round(current_cr - cr_at_~7d_ago)`` read from
        ``cr_snapshots_recent`` — o espelho PLANO da janela da temporada
        corrente (T2.3): é a tabela que existe na réplica de leitura (a
        hypertable Timescale não replica logicamente). "Current" is each
        player's most recent snapshot; the "~7d ago" baseline is that player's
        *latest* snapshot at or before ``now - 7d`` (so a snapshot exactly on
        the boundary counts). When a player has no snapshot that old, the
        baseline degrades to their *earliest* snapshot (best available
        history); a player with a single snapshot (or none) yields 0 — stable.

        Batched for a leaderboard page: one grouped scan keyed by ``player_id``
        within the season partition (no N+1). Returns ``{player_id: delta}``;
        players absent from the snapshot mirror simply do not appear (callers
        treat a missing key as 0).
        """
        ids = [str(pid) for pid in player_ids]
        if not ids:
            return {}

        cutoff = (now or datetime.now(UTC)) - _DELTA7D_WINDOW
        stmt = self._delta7d_stmt(
            m.CrSnapshotRecent.__table__, season_id=season_id, ids=ids, cutoff=cutoff
        )

        out: dict[str, int] = {}
        for row in (await session.execute(stmt)).all():
            if row.current_cr is None or row.baseline_cr is None:
                continue
            out[str(row.player_id)] = round(float(row.current_cr) - float(row.baseline_cr))
        return out

    @staticmethod
    def _delta7d_stmt(
        snap: FromClause, *, season_id: str, ids: list[str], cutoff: datetime
    ) -> Select[Any]:
        """Build the one-pass delta7d statement over a snapshot-shaped table.

        Table-parametrized so tests can run the EXACT same query shape against
        a fixture table (parity antiga ``cr_snapshots`` × nova
        ``cr_snapshots_recent`` — mesmas colunas, mesmo resultado).
        """
        # current_cr: cr at the player's MAX(snapshot_at).
        # baseline_at: latest snapshot_at <= cutoff (the ~7d-ago point), or NULL.
        # earliest_at: the player's MIN(snapshot_at) — fallback baseline.
        # All three resolved in a single grouped pass over the season's chunks.
        agg = (
            select(
                snap.c.player_id.label("player_id"),
                func.max(snap.c.snapshot_at).label("current_at"),
                func.min(snap.c.snapshot_at).label("earliest_at"),
                func.max(case((snap.c.snapshot_at <= cutoff, snap.c.snapshot_at))).label(
                    "baseline_at"
                ),
            )
            .where(
                snap.c.season_id == season_id,
                snap.c.player_id.in_(ids),
            )
            .group_by(snap.c.player_id)
            .subquery()
        )

        cur = snap.alias("cur")
        base = snap.alias("base")
        # Coalesce the ~7d baseline to the earliest snapshot when no old-enough
        # snapshot exists, so a short history still produces a real delta.
        base_at = func.coalesce(agg.c.baseline_at, agg.c.earliest_at)
        return select(
            agg.c.player_id.label("player_id"),
            cur.c.cr.label("current_cr"),
            base.c.cr.label("baseline_cr"),
        ).select_from(
            agg.join(
                cur,
                (cur.c.player_id == agg.c.player_id)
                & (cur.c.season_id == season_id)
                & (cur.c.snapshot_at == agg.c.current_at),
            ).join(
                base,
                (base.c.player_id == agg.c.player_id)
                & (base.c.season_id == season_id)
                & (base.c.snapshot_at == base_at),
            )
        )

    # -- regional rank (rank within the player's own region, e.g. BR) ----------

    async def regional_rank_by_player(
        self,
        session: AsyncSession,
        *,
        season_id: str,
        player_ids: Iterable[str],
    ) -> dict[str, int]:
        """1-based rank of each player *within their own region*, in ONE query.

        Region comes from ``players.region`` (e.g. ``"BR"``); the rank is by CR
        descending among players sharing that region in the season. Computed with
        a single windowed scan (``RANK() OVER (PARTITION BY region ORDER BY cr
        DESC)``) and filtered to the requested ids, so a whole leaderboard page is
        one round-trip (no N+1). Players with no region are skipped (no regional
        tag). Returns ``{player_id: regional_rank}``.
        """
        ids = [str(pid) for pid in player_ids]
        if not ids:
            return {}

        ps = m.PlayerSeason.__table__
        pl = m.Player.__table__
        ranked = (
            select(
                ps.c.player_id.label("player_id"),
                func.rank()
                .over(
                    partition_by=pl.c.region,
                    order_by=ps.c.cr.desc(),
                )
                .label("regional_rank"),
            )
            .select_from(ps.join(pl, pl.c.id == ps.c.player_id))
            .where(
                ps.c.season_id == season_id,
                pl.c.region.isnot(None),
            )
            .subquery()
        )
        stmt = select(ranked.c.player_id, ranked.c.regional_rank).where(ranked.c.player_id.in_(ids))
        out: dict[str, int] = {}
        for row in (await session.execute(stmt)).all():
            out[str(row.player_id)] = int(row.regional_rank)
        return out

    # -- region label per player (for the "TOP n {REGION}" tag) ----------------

    async def regions_by_player(
        self,
        session: AsyncSession,
        *,
        player_ids: Iterable[str],
    ) -> dict[str, str]:
        """Map ``player_id -> region`` (e.g. ``"BR"``) for the page, one query."""
        ids = [str(pid) for pid in player_ids]
        if not ids:
            return {}
        pl = m.Player.__table__
        rows = await session.execute(
            select(pl.c.id, pl.c.region).where(pl.c.id.in_(ids), pl.c.region.isnot(None))
        )
        return {str(pid): region for pid, region in rows.all() if region}

    # -- one-trick-pony detection (most-played champion >= ~40% of games) ------

    async def otp_by_player(
        self,
        session: AsyncSession,
        *,
        season_id: str,
        player_ids: Iterable[str],
    ) -> dict[str, OtpView]:
        """Per-player OTP signal from ``champion_stats``, in ONE query.

        Scans the pre-aggregated ``champion_stats`` for the page and, per player,
        keeps the busiest champion and its share of total games
        (``most_played_games / total_games``). Callers tag a player ``otp`` when
        ``share >= _OTP_SHARE``. Players with no champion rows are absent from the
        map. No N+1 — one grouped scan over the season's champion_stats.
        """
        ids = [str(pid) for pid in player_ids]
        if not ids:
            return {}
        cs = m.ChampionStat.__table__
        rows = await session.execute(
            select(cs.c.player_id, cs.c.champion_id, cs.c.matches_played).where(
                cs.c.season_id == season_id, cs.c.player_id.in_(ids)
            )
        )
        totals: dict[str, int] = {}
        best: dict[str, tuple[int, int]] = {}  # player_id -> (champion_id, games)
        for pid, champion_id, games in rows.all():
            key = str(pid)
            g = int(games or 0)
            totals[key] = totals.get(key, 0) + g
            cur = best.get(key)
            if cur is None or g > cur[1]:
                best[key] = (int(champion_id), g)
        out: dict[str, OtpView] = {}
        for key, total in totals.items():
            if total <= 0:
                continue
            champ_id, champ_games = best[key]
            out[key] = OtpView(
                champion_id=champ_id,
                games=champ_games,
                share=champ_games / total,
            )
        return out

    async def champion_placement_rank_by_player(
        self,
        session: AsyncSession,
        *,
        season_id: str,
        mains: dict[str, int],
        min_games: int = _CHAMP_RANK_MIN_GAMES,
    ) -> dict[str, ChampRankView]:
        """For each ``player_id -> main champion_id`` in ``mains``, the player's rank
        by **average placement** among that champion's players, in ONE query.

        Ranks every ``champion_stats`` row with ``matches_played >= min_games`` by
        average placement ascending (``total_placement_sum / matches_played``; a
        lower mean placement is better, ties broken by more games) within each
        champion, then keeps only each requested player's *main* champion. Players
        whose main has fewer than ``min_games`` games (or aren't ranked) are absent
        from the map. Placement-derived only (ToS): no CR/PDL. One windowed scan.
        """
        if not mains:
            return {}
        cs = m.ChampionStat.__table__
        # Float division — Postgres integer/integer truncates, which would collapse
        # every player to a handful of average-placement ties and wreck the rank.
        avg_place = (
            cast(cs.c.total_placement_sum, Float) / func.nullif(cs.c.matches_played, 0)
        ).label("avg_place")
        ranked = (
            select(
                cs.c.player_id.label("player_id"),
                cs.c.champion_id.label("champion_id"),
                avg_place,
                cs.c.matches_played.label("games"),
                func.rank()
                .over(
                    partition_by=cs.c.champion_id,
                    order_by=(avg_place.asc(), cs.c.matches_played.desc()),
                )
                .label("champ_rank"),
            )
            # Restrict to the champions that are actually a page player's main.
            # RANK is partitioned by champion, so narrowing the champion set never
            # changes any single champion's ranking — it just skips scanning the
            # ~160 champions nobody on this page mains.
            .where(
                cs.c.season_id == season_id,
                cs.c.matches_played >= min_games,
                cs.c.champion_id.in_(set(mains.values())),
            )
            .subquery()
        )
        stmt = select(
            ranked.c.player_id,
            ranked.c.champion_id,
            ranked.c.champ_rank,
            ranked.c.avg_place,
            ranked.c.games,
        ).where(ranked.c.player_id.in_(list(mains.keys())))
        rows = await session.execute(stmt)
        out: dict[str, ChampRankView] = {}
        for pid, champion_id, champ_rank, avg_p, games in rows.all():
            key = str(pid)
            # Only the player's own main champion earns their identity tag.
            if mains.get(key) != int(champion_id):
                continue
            out[key] = ChampRankView(
                champion_id=int(champion_id),
                rank=int(champ_rank),
                avg_place=float(avg_p),
                games=int(games or 0),
            )
        return out

    # -- pure tag assembly (no I/O) --------------------------------------------

    @staticmethod
    def build_player_tags(
        *,
        delta7d: int = 0,
        otp: OtpView | None = None,
        otp_champion_name: str | None = None,
        otp_icon_url: str | None = None,
        champ_rank: ChampRankView | None = None,
        champ_rank_name: str | None = None,
        champ_rank_icon_url: str | None = None,
        limit: int = 2,
    ) -> list[PlayerTag]:
        """Build the champion-first ``PlayerTag`` list for a player (pure).

        Order, capped at ``limit`` (default 2):

        1. **Champion identity** (one tag). A placement flex — "TOP n {Champ}"
           (``champrank`` kind, only when ``champ_rank.rank <= _CHAMP_RANK_MAX``)
           — outranks a plain "OTP {Champ}" (``otp`` kind, when its share
           ``>= 40%``). Both carry the champion's ddragon icon so the client can
           tint the chip with the champion's dominant color.
        2. **Momentum** — "Em alta" (``hot``) when ``delta7d > 50``.

        Global/regional rank tags are deliberately gone: the rank already leads
        every row and repeating it as a badge was pure redundancy.
        """
        tags: list[PlayerTag] = []

        if champ_rank is not None and champ_rank.rank <= _CHAMP_RANK_MAX:
            champ = _short_champ_name(champ_rank_name, champ_rank.champion_id)
            tags.append(
                PlayerTag(
                    kind="champrank",
                    label=f"TOP {champ_rank.rank} {champ}",
                    icon="",
                    champ_icon_url=champ_rank_icon_url,
                )
            )
        elif otp is not None and otp.share >= _OTP_SHARE:
            champ = _short_champ_name(otp_champion_name, otp.champion_id)
            tags.append(
                PlayerTag(kind="otp", label=f"OTP {champ}", icon="", champ_icon_url=otp_icon_url)
            )

        if delta7d > _HOT_DELTA_THRESHOLD:
            tags.append(PlayerTag(kind="hot", label="Em alta", icon="trending_up"))

        return tags[:limit]


def _short_champ_name(name: str | None, champion_id: int) -> str:
    """Compact tag label for a champion: first word, uppercased.

    "Ezreal" → "EZREAL", "Nunu e Willump" → "NUNU", "Miss Fortune" → "MISS".
    Falls back to the numeric id when the champion name isn't resolved.
    """
    if not name:
        return str(champion_id)
    return name.split()[0].upper()


__all__ = [
    "StatsService",
    "ChampionStatView",
    "HeadToHeadView",
    "StreakView",
    "WinLossView",
    "OtpView",
    "ChampRankView",
]
