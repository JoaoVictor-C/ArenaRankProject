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
from datetime import UTC, datetime, timedelta

from typing import Any

from sqlalchemy import Float, FromClause, Integer, Select, and_, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

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
class RawRecord:
    """One season-highlight record before display hydration (router adds name/avatar)."""

    key: str  # streak | biggest_gain | most_today | first_rate | top4_rate
    label: str  # PT-BR display label
    value: str  # formatted value ("14", "+72", "42%")
    player_id: str  # record holder (hydrated to name/handle/avatar by the router)
    accent: str  # UI accent color hint


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

    async def champion_tierlist(
        self,
        session: AsyncSession,
        *,
        season_id: str,
        min_games: int = 3,
    ) -> list[ChampionTierRow]:
        """Global per-champion aggregate for the season (tierlist source).

        Aggregated from ``match_participants`` (the placement source of truth) so
        ``first_rate`` is a TRUE first-place rate (placement == 1) — ``champion_stats``
        conflates ``wins`` with ``top_half`` (both increment on a top-half finish),
        so it cannot distinguish 1st place. Joins ``matches`` for season scoping
        (participants carry no season_id; the season's declared dates need not match
        played_at, so we scope by ``matches.season_id``, not a date window). Only
        ``eligible`` participants count (AFK/frozen excluded, mirroring the rating
        write). A champion needs ``>= min_games`` to surface. ``pick_rate`` is the
        champion's share of all eligible champion-games. ToS: placement-derived only.
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
        rows = (await session.execute(stmt)).all()
        total_games = sum(int(r.games or 0) for r in rows) or 1
        out: list[ChampionTierRow] = []
        for r in rows:
            g = int(r.games or 0)
            if g <= 0:
                continue
            out.append(
                ChampionTierRow(
                    champion_id=int(r.champion_id),
                    games=g,
                    first_rate=round(100 * int(r.firsts or 0) / g),
                    top4_rate=round(100 * int(r.top4 or 0) / g),
                    avg_place=round(int(r.place_sum or 0) / g, 2),
                    pick_rate=round(100 * g / total_games, 1),
                )
            )
        return out

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

        Reads the pre-aggregated ``champion_stats`` table via the champion-first
        index (``ix_champion_stats_champion_season_games``): rows are ranked within
        each champion by games (tie-break: more top-half finishes) and the top
        ``per_champion`` are kept. When ``champion_ids`` is given the scan is
        narrowed to those champions (RANK is partitioned by champion, so narrowing
        never changes any champion's own ranking). ``winrate`` is the top-half
        ("win") rate. Placement-derived only (ToS): no augment/item winrate.
        """
        cs = m.ChampionStat.__table__
        avg_place = (
            cast(cs.c.total_placement_sum, Float) / func.nullif(cs.c.matches_played, 0)
        ).label("avg_place")
        rn = (
            func.row_number()
            .over(
                partition_by=cs.c.champion_id,
                order_by=(cs.c.matches_played.desc(), cs.c.top_half.desc()),
            )
            .label("rn")
        )
        conds = [cs.c.season_id == season_id, cs.c.matches_played >= min_games]
        champ_set = {int(c) for c in champion_ids} if champion_ids is not None else None
        if champ_set is not None:
            if not champ_set:
                return {}
            conds.append(cs.c.champion_id.in_(champ_set))
        ranked = (
            select(
                cs.c.champion_id.label("champion_id"),
                cs.c.player_id.label("player_id"),
                cs.c.matches_played.label("games"),
                cs.c.top_half.label("top_half"),
                avg_place,
                rn,
            )
            .where(*conds)
            .subquery()
        )
        stmt = select(
            ranked.c.champion_id,
            ranked.c.player_id,
            ranked.c.games,
            ranked.c.top_half,
            ranked.c.avg_place,
        ).where(ranked.c.rn <= per_champion)
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

        Self-joins ``match_participants`` on ``(match_id, team_id)`` with
        ``a.champion_id < b.champion_id`` to form each unordered pair once. Both
        members share the subteam's placement, so ``a.placement`` measures the pair.
        Season-scoped via a ``matches`` join; only ``eligible`` participants count
        (mirrors the rating write). A pair needs ``>= min_games`` to surface; the
        qualified pool is then ranked by the Wilson score lower bound of the
        top-half rate (then games), so a perfect run over a handful of games never
        outranks a solid rate over a real sample. Placement-derived only (ToS).
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
        self, session: AsyncSession, *, season_id: str, min_games: int = 5
    ) -> list[RawRecord]:
        """Season highlight records (rail rotating card), placement-derived + real.

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
