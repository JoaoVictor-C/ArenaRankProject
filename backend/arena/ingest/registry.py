"""Bulk player registration for the crawl pipeline.

The crawler (`crawler.py`) only knows puuids; the rating engine only knows
``player_id`` (our own UUIDs). This module bridges the two in bulk, once per
crawled batch, instead of the online write path's per-lobby
``INSERT ... ON CONFLICT`` (see ``arena.services.match_pipeline`` /
``arena.ingest.replay``'s ``id_map``, which is built from this module's
output).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from arena.db import models as m
from arena.riot.arena import ParsedArenaMatch


class PlayerRegistry:
    """Bulk puuid->player_id upsert. One INSERT ... ON CONFLICT per `chunk`,
    RETURNING (id, puuid). COALESCE keeps a known name/tag/icon when the new row
    carries null. Idempotent across re-encounters and safe under concurrency."""

    async def bulk_ensure(
        self, session: Any, matches: Sequence[ParsedArenaMatch], *,
        region: str = "br", chunk: int = 1000,
    ) -> dict[str, str]:
        roster: dict[str, dict[str, object]] = {}
        for parsed in matches:
            for st in parsed.subteams:
                for pp in st.participants:
                    if not pp.puuid:
                        continue
                    roster[pp.puuid] = {
                        "puuid": pp.puuid,
                        "summoner_name": pp.riot_id_game_name or None,
                        "tag_line": pp.riot_id_tagline or None,
                        "region": region,
                        "profile_icon_id": pp.profile_icon or None,
                    }
        col = m.Player.__table__.c
        rows = list(roster.values())
        id_map: dict[str, str] = {}
        for i in range(0, len(rows), chunk):
            ins = pg_insert(m.Player).values(rows[i : i + chunk])
            stmt = ins.on_conflict_do_update(
                index_elements=["puuid"],
                set_={
                    "profile_icon_id": func.coalesce(ins.excluded.profile_icon_id, col.profile_icon_id),
                    "summoner_name": func.coalesce(ins.excluded.summoner_name, col.summoner_name),
                    "tag_line": func.coalesce(ins.excluded.tag_line, col.tag_line),
                },
            ).returning(col.id, col.puuid)
            for pid, pu in (await session.execute(stmt)).all():
                id_map[str(pu)] = str(pid)
        return id_map
