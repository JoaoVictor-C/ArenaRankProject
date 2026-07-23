"""DB-gated end-to-end test of the worker write path.

Skipped unless ``DATABASE_URL`` is set AND the schema is migrated
(``alembic upgrade head``) with at least one season seeded
(``python -m arena.db.seed``). It drives a synthetic Arena payload through
:class:`~arena.services.match_pipeline.WorkerRatingService` -> the real
``RatingService`` -> Postgres, with ``redis=None`` (no-op lock), and asserts the
rating result persisted and is idempotent on re-run.

In CI: stand up a Postgres service, run ``alembic upgrade head`` + seed a
season, then run this. Locally it no-ops unless you opt in by exporting
``DATABASE_URL``.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="integration test needs a migrated Postgres (set DATABASE_URL)",
)


def _payload(riot_id: str) -> dict[str, Any]:
    puuids = [f"{riot_id}-{i}" for i in range(4)]

    def part(puuid: str, sub: int, place: int, champ: int) -> dict[str, Any]:
        return {
            "puuid": puuid,
            "riotIdGameName": puuid,
            "riotIdTagline": "BR1",
            "championId": champ,
            "playerSubteamId": sub,
            "subteamPlacement": place,
            "profileIcon": 1,
            "timePlayed": 600,
            "gameEndedInEarlySurrender": False,
        }

    return {
        "metadata": {"matchId": riot_id},
        "info": {
            "queueId": 1700,
            "gameDuration": 600,
            "gameStartTimestamp": 1_700_000_000_000,
            "participants": [
                part(puuids[0], 1, 1, 11),
                part(puuids[1], 1, 1, 22),
                part(puuids[2], 2, 2, 33),
                part(puuids[3], 2, 2, 44),
            ],
        },
    }


async def test_process_match_persists_and_is_idempotent() -> None:
    from sqlalchemy import text

    from arena.db.session import get_sessionmaker
    from arena.services.match_pipeline import (
        WorkerRatingService,
        deterministic_match_id,
    )

    riot_id = f"BR1_{uuid.uuid4().hex[:12]}"  # unique per run; no cleanup needed
    svc = WorkerRatingService()

    first = await svc.process_match(riot_id, _payload(riot_id), redis=None)
    assert first["status"] == "processed"
    assert first["playersUpdated"] == 4

    internal_id = deterministic_match_id(riot_id)
    factory = get_sessionmaker()
    async with factory() as session:
        count = (
            await session.execute(
                text("select count(*) from match_participants where match_id = :m"),
                {"m": internal_id},
            )
        ).scalar()
    assert count == 4

    # Re-run: the deterministic id -> matches.processed already true -> idempotent.
    second = await svc.process_match(riot_id, _payload(riot_id), redis=None)
    assert second["status"] == "already_processed"
