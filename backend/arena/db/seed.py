"""Idempotent development seed — one ACTIVE season + a static champions const.

Run locally (or via ``docker compose run --rm api python -m arena.db.seed``) to
bring a fresh database to a usable state for the read-API and the frontend:

* a single **ACTIVE** dev season on queue ``1750`` (LoL Arena), with the launch
  ``RatingParams`` serialized into ``seasons.config`` — this is what the
  rating/season services read for placement curves, soft-reset factors, etc.;
* the canonical **champions static const** (:data:`CHAMPIONS`) — the same
  deterministic champion roster the ``GET /api/v1/champions`` tierlist sample is
  built from, exported here so other dev tooling / fixtures share one source.

Idempotency: every write is guarded by an existence check (season is matched by
``queue_id`` + ``status=ACTIVE``), so re-running is a no-op — safe to wire into a
container start command or a Make target. Nothing here runs in production.

This module never surfaces ``mu``/``sigma`` or augment/item winrate; it only
seeds internal rows. User-facing strings are PT-BR per contract.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arena.core.logging import configure_logging, get_logger
from arena.db import models as m
from arena.db.session import dispose_engine, get_sessionmaker
from arena.rating import DEFAULT_PARAMS

_log = get_logger("arena.db.seed")

# Dev season runs on the LoL Arena queue.
DEV_QUEUE_ID: Final[int] = 1750
DEV_SEASON_NAME: Final[str] = "Temporada de Desenvolvimento"


# ---------------------------------------------------------------------------
# Champions static const
#
# The canonical champion roster for dev/fixtures. Deterministic and ordered so
# the tierlist sample and any future fixture share one source of truth. Names
# only — champion art is a placeholder gradient (Riot ToS), and no augment/item
# winrate is implied here.
# ---------------------------------------------------------------------------
CHAMPIONS: Final[tuple[str, ...]] = (
    "Jinx",
    "Lux",
    "Yasuo",
    "Zed",
    "Ahri",
    "Vi",
    "Garen",
    "Thresh",
    "Caitlyn",
    "Vex",
    "Yone",
    "Katarina",
    "Akali",
    "Darius",
    "Sett",
    "Nilah",
    "Samira",
    "Seraphine",
    "Ekko",
    "Briar",
)


def _season_config() -> dict[str, Any]:
    """Serialize the launch ``RatingParams`` into a JSONB-friendly dict.

    ``placement_weights`` has int keys (team count); JSON object keys must be
    strings, so we stringify them. The season/rating services read this back and
    reconstruct a :class:`~arena.rating.RatingParams` when present.
    """
    cfg = asdict(DEFAULT_PARAMS)
    cfg["placement_weights"] = {
        str(team_count): list(curve)
        for team_count, curve in DEFAULT_PARAMS.placement_weights.items()
    }
    return cfg


async def seed_dev_season(session: AsyncSession) -> m.Season:
    """Create (or return) the single ACTIVE dev season on queue 1750.

    Idempotent: if an ACTIVE season already exists on the dev queue it is
    returned untouched. The season window is a generous one-year span anchored
    at the current UTC day so dev matches (``played_at = now``) always fall
    inside it.
    """
    existing = await session.scalar(
        select(m.Season).where(
            m.Season.queue_id == DEV_QUEUE_ID,
            m.Season.status == m.SeasonStatus.ACTIVE,
        )
    )
    if existing is not None:
        _log.info("seed.season.exists", seasonId=str(existing.id), name=existing.name)
        return existing

    now = datetime.now(UTC)
    season = m.Season(
        name=DEV_SEASON_NAME,
        queue_id=DEV_QUEUE_ID,
        starts_at=now - timedelta(days=1),
        ends_at=now + timedelta(days=365),
        status=m.SeasonStatus.ACTIVE,
        config=_season_config(),
    )
    session.add(season)
    await session.flush()
    _log.info("seed.season.created", seasonId=str(season.id), queueId=DEV_QUEUE_ID)
    return season


async def seed(session: AsyncSession) -> dict[str, Any]:
    """Run all idempotent dev seeders inside the caller's transaction.

    Returns a small JSON-serializable summary (``camelCase`` keys to match the
    API contract style) describing what now exists.
    """
    season = await seed_dev_season(session)
    return {
        "seasonId": str(season.id),
        "seasonName": season.name,
        "queueId": season.queue_id,
        "championsCount": len(CHAMPIONS),
    }


async def _run() -> dict[str, Any]:
    configure_logging()
    factory = get_sessionmaker()
    try:
        async with factory() as session:
            summary = await seed(session)
            await session.commit()
    finally:
        await dispose_engine()
    _log.info("seed.done", **summary)
    return summary


def main() -> None:
    """CLI entrypoint: ``python -m arena.db.seed``."""
    asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover - manual dev invocation
    main()


__all__ = [
    "CHAMPIONS",
    "DEV_QUEUE_ID",
    "DEV_SEASON_NAME",
    "seed",
    "seed_dev_season",
    "main",
]
