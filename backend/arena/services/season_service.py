"""SeasonService — season lifecycle, soft-reset, and achievements (§3.6, §13.3).

Implements the season state machine and the two transition pipelines:

State machine (proposal §3.6)::

    ACTIVE ──▶ SOFT_LOCK ──▶ ENDED ──▶ OFF_SEASON
       ▲                                   │
       └───────────── (new season) ────────┘   (a *new* ACTIVE season row)

Only forward transitions along that chain are allowed; ``advance_status`` rejects
anything else (no skipping, no going back on the same row). ``OFF_SEASON`` is
terminal for the row — a new season is a *new* row that starts ``ACTIVE``.

* **close_season** (ENDED): award Top 1/10/50/100/500 achievements from the final
  CR sort, then mark the season ``ENDED`` (§13.3 close pipeline; S3 Parquet
  snapshot is a worker concern handled elsewhere).
* **soft_reset** (new season start): for every player with ``matches_played > 0``
  in the previous season, create a fresh ``player_seasons`` row via the engine's
  pure ``arena.rating.soft_reset`` (``new_CR = 1000 + (prev−1000)·0.5``,
  ``sigma×1.5`` capped 350).

Achievement tiers + PT-BR labels are defined here. mu/sigma never surface; ranks
are by CR. User-facing strings are PT-BR.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from arena.db import models as m
from arena.db.models import SeasonStatus
from arena.rating import DEFAULT_PARAMS, PlayerState, RatingParams, soft_reset

# Allowed forward transitions of the lifecycle state machine.
_ALLOWED_TRANSITIONS: dict[SeasonStatus, SeasonStatus] = {
    SeasonStatus.ACTIVE: SeasonStatus.SOFT_LOCK,
    SeasonStatus.SOFT_LOCK: SeasonStatus.ENDED,
    SeasonStatus.ENDED: SeasonStatus.OFF_SEASON,
}

# Top-tier achievement cutoffs (final CR rank, 1-based) -> (type, PT-BR label).
# Each player gets *only* the best (smallest-cutoff) tier they qualify for.
_ACHIEVEMENT_TIERS: list[tuple[int, str, str]] = [
    (1, "TOP_1", "Campeao da Temporada"),
    (10, "TOP_10", "Top 10 da Temporada"),
    (50, "TOP_50", "Top 50 da Temporada"),
    (100, "TOP_100", "Top 100 da Temporada"),
    (500, "TOP_500", "Top 500 da Temporada"),
]


class SeasonTransitionError(RuntimeError):
    """Raised on an illegal lifecycle transition (PT-BR message)."""


@dataclass(slots=True)
class CloseSeasonResult:
    season_id: str
    achievements_awarded: int = 0
    awarded_by_tier: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class SoftResetResult:
    from_season_id: str
    to_season_id: str
    players_carried: int = 0


class SeasonService:
    """Stateless; methods take an :class:`AsyncSession`."""

    def __init__(self, *, params: RatingParams = DEFAULT_PARAMS) -> None:
        self._params = params

    # -- lifecycle state machine -------------------------------------------

    async def advance_status(
        self, session: AsyncSession, *, season_id: str, to: SeasonStatus
    ) -> SeasonStatus:
        """Advance the season one legal step along the lifecycle chain.

        Raises :class:`SeasonTransitionError` for any non-adjacent transition.
        Commits the new status. Returns the resulting status.
        """
        season = await self._get_season(session, season_id)
        expected = _ALLOWED_TRANSITIONS.get(season.status)
        if expected is None:
            raise SeasonTransitionError(
                f"Temporada em estado terminal '{season.status.value}': "
                "nenhuma transicao permitida."
            )
        if to is not expected:
            raise SeasonTransitionError(
                f"Transicao invalida: de '{season.status.value}' so e permitido "
                f"avancar para '{expected.value}', nao '{to.value}'."
            )
        season.status = to
        await session.commit()
        return to

    # -- close (ENDED): award achievements ---------------------------------

    async def close_season(self, session: AsyncSession, *, season_id: str) -> CloseSeasonResult:
        """Award Top 1/10/50/100/500 badges from final CR sort, then mark ENDED.

        Idempotent on ``player_achievements`` (unique on
        ``player_id, season_id, achievement_type``): re-running skips players who
        already hold the tier. Must be called when transitioning into ENDED.
        """
        season = await self._get_season(session, season_id)

        # Final standings: provisional players excluded from tier rewards.
        max_rank = _ACHIEVEMENT_TIERS[-1][0]
        rows = await session.execute(
            select(m.PlayerSeason.player_id, m.PlayerSeason.cr)
            .where(
                m.PlayerSeason.season_id == season_id,
                m.PlayerSeason.is_provisional.is_(False),
                m.PlayerSeason.matches_played > 0,
            )
            .order_by(m.PlayerSeason.cr.desc())
            .limit(max_rank)
        )
        ranked = list(rows.all())

        # Existing achievements for this season (idempotency).
        existing = await session.execute(
            select(m.PlayerAchievement.player_id, m.PlayerAchievement.achievement_type).where(
                m.PlayerAchievement.season_id == season_id
            )
        )
        held: set[tuple[str, str]] = {(str(pid), atype) for pid, atype in existing.all()}

        awarded_by_tier: dict[str, int] = {}
        total = 0
        for idx, (player_id, _cr) in enumerate(ranked):
            rank = idx + 1
            tier = self._tier_for_rank(rank)
            if tier is None:
                continue
            cutoff, atype, _label = tier
            if (str(player_id), atype) in held:
                continue
            session.add(
                m.PlayerAchievement(
                    player_id=player_id,
                    season_id=season_id,
                    achievement_type=atype,
                    tier=atype,
                    rank_value=rank,
                )
            )
            awarded_by_tier[atype] = awarded_by_tier.get(atype, 0) + 1
            total += 1

        # Forward the lifecycle into ENDED if not already there.
        if season.status is SeasonStatus.SOFT_LOCK:
            season.status = SeasonStatus.ENDED

        await session.commit()
        return CloseSeasonResult(
            season_id=season_id,
            achievements_awarded=total,
            awarded_by_tier=awarded_by_tier,
        )

    @staticmethod
    def _tier_for_rank(rank: int) -> tuple[int, str, str] | None:
        """Best (smallest-cutoff) tier a 1-based rank qualifies for."""
        for cutoff, atype, label in _ACHIEVEMENT_TIERS:
            if rank <= cutoff:
                return cutoff, atype, label
        return None

    # -- new season: soft reset --------------------------------------------

    async def soft_reset(
        self,
        session: AsyncSession,
        *,
        from_season_id: str,
        to_season_id: str,
    ) -> SoftResetResult:
        """Carry every active player from the previous season into the new one.

        For each ``from_season`` player with ``matches_played > 0`` we compute the
        new state via the engine's pure ``soft_reset`` and create a fresh
        ``to_season`` ``player_seasons`` row. Idempotent: players who already have
        a row in the target season are skipped.
        """
        # Players already seeded in the target season (idempotency).
        seeded = await session.execute(
            select(m.PlayerSeason.player_id).where(m.PlayerSeason.season_id == to_season_id)
        )
        already: set[str] = {str(pid) for (pid,) in seeded.all()}

        prev_rows = await session.execute(
            select(m.PlayerSeason).where(
                m.PlayerSeason.season_id == from_season_id,
                m.PlayerSeason.matches_played > 0,
            )
        )

        carried = 0
        for prev in prev_rows.scalars():
            pid = str(prev.player_id)
            if pid in already:
                continue
            state = PlayerState(
                player_id=pid,
                mu=prev.mu,
                sigma=prev.sigma,
                cr=prev.cr,
                current_streak=prev.current_streak,
                matches_played=prev.matches_played,
                placement_matches_remaining=prev.placement_matches_remaining,
                peak_cr=prev.peak_cr,
            )
            reset = soft_reset(state, self._params)
            session.add(
                m.PlayerSeason(
                    player_id=prev.player_id,
                    season_id=to_season_id,
                    cr=reset.cr,
                    mu=reset.mu,
                    sigma=reset.sigma,
                    matches_played=0,
                    placement_matches_remaining=reset.placement_matches_remaining,
                    is_provisional=True,
                    peak_cr=reset.peak_cr,
                    current_streak=0,
                )
            )
            carried += 1

        await session.commit()
        return SoftResetResult(
            from_season_id=from_season_id,
            to_season_id=to_season_id,
            players_carried=carried,
        )

    # -- helpers -----------------------------------------------------------

    async def _get_season(self, session: AsyncSession, season_id: str) -> m.Season:
        season = await session.get(m.Season, season_id)
        if season is None:
            raise SeasonTransitionError(f"Temporada '{season_id}' nao encontrada.")
        return season

    async def active_player_count(self, session: AsyncSession, *, season_id: str) -> int:
        """Players with at least one match this season (business metric)."""
        count = await session.execute(
            select(func.count())
            .select_from(m.PlayerSeason)
            .where(
                m.PlayerSeason.season_id == season_id,
                m.PlayerSeason.matches_played > 0,
            )
        )
        return int(count.scalar_one())


__all__ = [
    "SeasonService",
    "SeasonTransitionError",
    "CloseSeasonResult",
    "SoftResetResult",
]
