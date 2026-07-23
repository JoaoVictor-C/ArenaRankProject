"""Mirror the active season's ``config`` JSONB onto the current DEFAULT_PARAMS.

The engine reads params from ``arena.rating.params.DEFAULT_PARAMS`` (not from the
DB), so ``seasons.config`` is display/telemetry only — but after a recalibration
it must not show stale values in the admin panel. This rewrites it from the live
dataclass.

Run (cwd backend):
    DATABASE_URL=postgresql+asyncpg://arena:arena@localhost:5433/arena \
      python -m scripts.sync_season_config
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict

from sqlalchemy import select

from arena.db import models as m
from arena.db.session import get_sessionmaker
from arena.rating.params import DEFAULT_PARAMS


async def main() -> None:
    cfg = asdict(DEFAULT_PARAMS)
    # JSONB object keys must be strings; placement_weights is keyed by int.
    cfg["placement_weights"] = {str(k): v for k, v in cfg["placement_weights"].items()}

    factory = get_sessionmaker()
    async with factory() as s:
        seasons = (await s.execute(select(m.Season))).scalars().all()
        for season in seasons:
            season.config = cfg
        await s.commit()
        print(f"updated config on {len(seasons)} season(s):")
        print(
            f"  sigma0={cfg['sigma0']} beta={cfg['beta']} tau={cfg['tau']} "
            f"placement_amp={cfg['placement_amp']} max_delta_mu={cfg['max_delta_mu']} "
            f"dispersion_sigma_ref={cfg['dispersion_sigma_ref']} "
            f"streak_loss_floor={cfg['streak_loss_floor']}"
        )


if __name__ == "__main__":
    asyncio.run(main())
