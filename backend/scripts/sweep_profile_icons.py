"""Backfill players.profile_icon_id for already-processed matches.

profile_icon is only on the raw Riot match payload (not on match_participants),
so this re-fetches every stored match, collects {puuid -> profileIcon}, and bulk-
updates the players. Run once after enabling profileIcon capture; future ingests
populate it inline via the hardened backfill upsert.

Run (cwd backend, RIOT_API_KEY in .env):
    DATABASE_URL=postgresql+asyncpg://arena:arena@localhost:5433/arena \
      python -m scripts.sweep_profile_icons
"""

from __future__ import annotations

import asyncio

import httpx
from sqlalchemy import select, text

from arena.core.config import settings
from arena.db import models as m
from arena.db.session import get_sessionmaker

REGION = "americas"


class Throttle:
    """Min-interval throttle (dev key ~100 req / 120s -> 1.3s keeps us under)."""

    def __init__(self, interval: float = 1.3) -> None:
        self.interval = interval
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = asyncio.get_event_loop().time()
            delta = self.interval - (now - self._last)
            if delta > 0:
                await asyncio.sleep(delta)
            self._last = asyncio.get_event_loop().time()


async def riot_get(client: httpx.AsyncClient, throttle: Throttle, url: str, params=None):
    for _ in range(6):
        await throttle.wait()
        r = await client.get(url, params=params)
        if r.status_code == 429:
            retry = int(r.headers.get("Retry-After", "5"))
            print(f"  429 -> sleep {retry}s")
            await asyncio.sleep(retry + 1)
            continue
        if r.status_code in (500, 502, 503, 504):
            await asyncio.sleep(2)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"riot_get gave up: {url}")


async def main() -> None:
    key = settings.riot_api_key
    if not key:
        print("RIOT_API_KEY empty")
        return
    base = f"https://{REGION}.api.riotgames.com"
    throttle = Throttle()
    factory = get_sessionmaker()

    async with (
        httpx.AsyncClient(headers={"X-Riot-Token": key}, timeout=20) as client,
        factory() as s,
    ):
        rids = (await s.execute(select(m.Match.riot_match_id))).scalars().all()
        print(f"matches to sweep: {len(rids)}")

        icons: dict[str, int] = {}
        done = 0
        for rid in rids:
            try:
                payload = await riot_get(client, throttle, f"{base}/lol/match/v5/matches/{rid}")
            except Exception as exc:  # noqa: BLE001
                print(f"  fail {rid}: {exc}")
                continue
            for p in payload.get("info", {}).get("participants", []):
                pu = str(p.get("puuid", ""))
                ic = p.get("profileIcon")
                if pu and isinstance(ic, int) and ic > 0:
                    icons[pu] = ic
            done += 1
            if done % 20 == 0:
                print(f"  swept {done}/{len(rids)} icons_collected={len(icons)}")

        updated = 0
        for pu, ic in icons.items():
            r = await s.execute(
                text(
                    "update players set profile_icon_id=:ic "
                    "where puuid=:pu and profile_icon_id is distinct from :ic"
                ),
                {"ic": ic, "pu": pu},
            )
            updated += r.rowcount or 0
        await s.commit()

        nnull = (
            await s.execute(text("select count(*) from players where profile_icon_id is not null"))
        ).scalar()
        total = (await s.execute(text("select count(*) from players"))).scalar()
        print(
            f"DONE: matches_swept={done} icons_collected={len(icons)} "
            f"rows_updated={updated} players_with_icon={nnull}/{total}"
        )


if __name__ == "__main__":
    asyncio.run(main())
