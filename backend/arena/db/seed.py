"""Idempotent development seed — one ACTIVE season + a static champions const.

Run locally (or via ``docker compose run --rm api python -m arena.db.seed``) to
bring a fresh database to a usable state for the read-API and the frontend:

* a single **ACTIVE** dev season on queue ``1750`` (LoL Arena), with the launch
  ``RatingParams`` serialized into ``seasons.config`` — this is what the
  rating/season services read for placement curves, soft-reset factors, etc.;
* the canonical **champions static const** (:data:`CHAMPIONS`) — the same
  deterministic champion roster the ``GET /api/v1/champions`` tierlist sample is
  built from. NOTE: this is an in-memory constant only; there is no champions
  table in the schema, so nothing here writes champion rows;
* the **tracked players** named by ``settings.seed_players`` (default
  ``Presente#1001,CrazzyBoy#Br2``), each with an empty ``player_seasons`` row in
  the dev season. Their Riot IDs are resolved to REAL PUUIDs via account-v1 —
  the sweep workers poll Riot by PUUID, so a placeholder id would 404 on every
  tick. Needs ``RIOT_API_KEY``; without it the players are skipped (warning) and
  the season seed still succeeds.

Idempotency: every write is guarded (season matched by ``queue_id`` +
``status=ACTIVE``; players upserted on ``puuid``; ladder rows ``ON CONFLICT DO
NOTHING`` so a re-run never resets someone's CR), so re-running is a no-op —
safe to wire into a container start command or a Make target. Nothing here runs
in production.

This module never surfaces ``mu``/``sigma`` or augment/item winrate; it only
seeds internal rows. User-facing strings are PT-BR per contract.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from arena.core.config import settings
from arena.core.logging import configure_logging, get_logger
from arena.db import models as m
from arena.db.session import dispose_engine, get_sessionmaker
from arena.rating import DEFAULT_PARAMS

_log = get_logger("arena.db.seed")

# Dev season runs on the LoL Arena queue.
DEV_QUEUE_ID: Final[int] = 1750
DEV_SEASON_NAME: Final[str] = "Temporada de Desenvolvimento"

#: Region stamped on seeded players — matches what the write path records for
#: an Arena lobby (``match_pipeline.register_players``).
DEV_PLAYER_REGION: Final[str] = "br"


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


# ---------------------------------------------------------------------------
# Tracked players
#
# Seeded players are REAL accounts: the Riot ID is resolved to its actual PUUID
# via account-v1, because the sweep workers poll Riot by PUUID. A synthetic id
# would make every sweep tick 404 forever, so a player we cannot resolve is
# skipped rather than inserted with a placeholder.
# ---------------------------------------------------------------------------


def parse_riot_id(riot_id: str) -> tuple[str, str] | None:
    """Split ``"gameName#tagLine"``. Returns ``None`` when malformed."""
    game_name, sep, tag_line = riot_id.strip().rpartition("#")
    if not sep or not game_name.strip() or not tag_line.strip():
        return None
    return game_name.strip(), tag_line.strip()


def configured_riot_ids() -> list[str]:
    """Riot IDs requested by ``settings.seed_players`` (comma-separated)."""
    return [part.strip() for part in settings.seed_players.split(",") if part.strip()]


async def resolve_puuids(riot_ids: list[str]) -> dict[str, tuple[str, str, str]]:
    """Resolve each Riot ID to ``(puuid, game_name, tag_line)`` via account-v1.

    Best-effort by design — the seed must never break ``docker compose up``
    (every service gates on it completing successfully). No Riot key, an unknown
    Riot ID, or a network/rate-limit failure logs a warning and drops that entry
    from the result instead of raising.
    """
    if not riot_ids:
        return {}
    if not settings.riot_api_key:
        _log.warning(
            "seed.players.no_riot_key",
            requested=len(riot_ids),
            hint="RIOT_API_KEY vazio — jogadores não semeados (PUUID real é obrigatório).",
        )
        return {}

    from redis.asyncio import Redis

    from arena.riot.client import build_default_client
    from arena.riot.errors import RiotError

    resolved: dict[str, tuple[str, str, str]] = {}
    redis = Redis.from_url(settings.redis_url)
    try:
        async with build_default_client(settings.riot_api_key, redis=redis) as client:
            for riot_id in riot_ids:
                parts = parse_riot_id(riot_id)
                if parts is None:
                    _log.warning("seed.player.malformed_riot_id", riotId=riot_id)
                    continue
                game_name, tag_line = parts
                try:
                    account = await client.get_account_by_riot_id(game_name, tag_line)
                except RiotError as exc:
                    _log.warning(
                        "seed.player.resolve_failed",
                        riotId=riot_id,
                        error=str(exc),
                    )
                    continue
                except Exception as exc:  # noqa: BLE001 - network/DNS/timeout
                    _log.warning("seed.player.resolve_error", riotId=riot_id, error=str(exc))
                    continue
                puuid = str(account.get("puuid") or "")
                if not puuid:
                    _log.warning("seed.player.no_puuid", riotId=riot_id)
                    continue
                resolved[riot_id] = (
                    puuid,
                    str(account.get("gameName") or game_name),
                    str(account.get("tagLine") or tag_line),
                )
    finally:
        await redis.aclose()
    return resolved


async def seed_players(
    session: AsyncSession,
    season: m.Season,
    resolved: dict[str, tuple[str, str, str]],
) -> list[dict[str, Any]]:
    """Upsert the resolved players + an empty ``player_seasons`` row for each.

    Idempotent: the player upsert keys on ``puuid`` (refreshing the display name
    only), and the season row uses ``ON CONFLICT DO NOTHING`` so an existing
    player's CR/mu/sigma is never reset by a re-run. Rows are sorted by puuid to
    keep the same lock-acquisition order as the write path's ``register_players``.
    """
    if not resolved:
        return []

    rows = sorted(
        (
            {
                "puuid": puuid,
                "summoner_name": game_name,
                "tag_line": tag_line,
                "region": DEV_PLAYER_REGION,
            }
            for puuid, game_name, tag_line in resolved.values()
        ),
        key=lambda r: str(r["puuid"]),
    )

    ins = pg_insert(m.Player).values(rows)
    upsert = ins.on_conflict_do_update(
        index_elements=["puuid"],
        set_={
            "summoner_name": func.coalesce(ins.excluded.summoner_name, m.Player.summoner_name),
            "tag_line": func.coalesce(ins.excluded.tag_line, m.Player.tag_line),
        },
    ).returning(m.Player.id, m.Player.puuid)
    player_ids = {puuid: pid for pid, puuid in (await session.execute(upsert)).all()}

    # Empty ladder rows: server defaults (CR 1000, provisional, 10 placements).
    season_rows = [
        {"player_id": player_ids[puuid], "season_id": season.id} for puuid in sorted(player_ids)
    ]
    ps_ins = pg_insert(m.PlayerSeason).values(season_rows)
    await session.execute(
        ps_ins.on_conflict_do_nothing(constraint="uq_player_seasons_player_season")
    )

    seeded = [
        {"riotId": riot_id, "playerId": str(player_ids[puuid])}
        for riot_id, (puuid, _gn, _tl) in sorted(resolved.items())
        if puuid in player_ids
    ]
    for entry in seeded:
        _log.info("seed.player.ready", **entry)
    return seeded


async def seed(session: AsyncSession) -> dict[str, Any]:
    """Run all idempotent dev seeders inside the caller's transaction.

    Returns a small JSON-serializable summary (``camelCase`` keys to match the
    API contract style) describing what now exists.
    """
    season = await seed_dev_season(session)
    requested = configured_riot_ids()
    resolved = await resolve_puuids(requested)
    players = await seed_players(session, season, resolved)
    return {
        "seasonId": str(season.id),
        "seasonName": season.name,
        "queueId": season.queue_id,
        "championsCount": len(CHAMPIONS),
        "playersRequested": len(requested),
        "playersSeeded": len(players),
        "players": [p["riotId"] for p in players],
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
    "DEV_PLAYER_REGION",
    "seed",
    "seed_dev_season",
    "seed_players",
    "parse_riot_id",
    "configured_riot_ids",
    "resolve_puuids",
    "main",
]
