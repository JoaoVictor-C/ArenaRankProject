"""PROVISIONAL — populate ``champion_build_ref`` with reference build data.

Caches a per-champion Arena aggregate (augment/item/teammate placement stats)
as one JSONB snapshot per (champion_id, patch), backing a stop-gap "build
recomendada" surface until native augment ingestion lands. Drop the whole
feature (table, model, this script) once we have our own augment data.

Champion ids come from Data Dragon (public). Politely throttled (~1 req/s),
retries 429/5xx. Idempotent upsert on (champion_id, patch).

Run (cwd backend):
    DATABASE_URL=postgresql+asyncpg://arena:...@host:5432/arena \
      python -m scripts.fetch_build_ref
    python -m scripts.fetch_build_ref --only 876,127   # subset
    python -m scripts.fetch_build_ref --interval 1.5   # slower
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

import httpx
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from arena.db import models as m
from arena.db.session import get_sessionmaker

SOURCE_URL = "https://data.v2.iesdev.com/api/v1/query_objects/prod/lol/arena_champion"
DDRAGON_VERSIONS = "https://ddragon.leagueoflegends.com/api/versions.json"
UA = "Mozilla/5.0 (ArenaRank build-ref fetch)"


async def _champion_ids(client: httpx.AsyncClient) -> list[int]:
    """All numeric championIds from the latest Data Dragon champion.json."""
    ver = (await client.get(DDRAGON_VERSIONS)).json()[0]
    url = f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/champion.json"
    entries = (await client.get(url)).json()["data"]
    ids: list[int] = []
    for entry in entries.values():
        try:
            ids.append(int(entry["key"]))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(ids)


async def _fetch_one(client: httpx.AsyncClient, cid: int) -> dict[str, Any] | None:
    """GET one champion's aggregate; None on non-200 after retries."""
    for _ in range(5):
        r = await client.get(SOURCE_URL, params={"champion_id": cid})
        if r.status_code == 429:
            await asyncio.sleep(int(r.headers.get("Retry-After", "5")) + 1)
            continue
        if r.status_code in (500, 502, 503, 504):
            await asyncio.sleep(2)
            continue
        if r.status_code == 200:
            body: Any = r.json()
            return body if isinstance(body, dict) else None
        return None
    return None


def _extract(cid: int, doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """Pull the champion's inner aggregate + patch/dt into an upsert row."""
    if not isinstance(doc, dict):
        return None
    data = doc.get("data")
    if not isinstance(data, list) or not data:
        return None
    obj = data[0]
    inner = obj.get("data")
    if not isinstance(inner, dict) or not inner:
        return None
    return {
        "champion_id": int(obj.get("champion_id", cid)),
        "patch": str(obj.get("patch") or "unknown"),
        "dt": str(obj["dt"]) if obj.get("dt") else None,
        "payload": inner,
    }


async def main() -> None:
    ap = argparse.ArgumentParser(description="Cache per-champion Arena build aggregates.")
    ap.add_argument("--only", default="", help="comma-separated championId subset")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between requests")
    args = ap.parse_args()

    factory = get_sessionmaker()
    async with httpx.AsyncClient(headers={"User-Agent": UA}, timeout=25) as client:
        if args.only:
            ids = [int(x) for x in args.only.split(",") if x.strip().isdigit()]
        else:
            ids = await _champion_ids(client)
        print(f"champions to fetch: {len(ids)}")

        ok = skipped = 0
        async with factory() as session:
            for i, cid in enumerate(ids, 1):
                doc = await _fetch_one(client, cid)
                await asyncio.sleep(args.interval)
                row = _extract(cid, doc)
                if row is None:
                    skipped += 1
                    continue
                ins = pg_insert(m.ChampionBuildRef).values(**row)
                stmt = ins.on_conflict_do_update(
                    index_elements=["champion_id", "patch"],
                    set_={
                        "dt": ins.excluded.dt,
                        "payload": ins.excluded.payload,
                        "fetched_at": func.now(),
                    },
                )
                await session.execute(stmt)
                ok += 1
                if i % 20 == 0:
                    await session.commit()
                    print(f"  {i}/{len(ids)} ok={ok} skipped={skipped}")
            await session.commit()
        print(f"DONE ok={ok} skipped={skipped}")


if __name__ == "__main__":
    asyncio.run(main())
