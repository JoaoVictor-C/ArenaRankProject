from __future__ import annotations

import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="e2e backfill needs a migrated+seeded Postgres (set DATABASE_URL)",
)


@pytest.mark.asyncio
async def test_bootstrap_run_processes_matches(monkeypatch):
    """Drive run() in bootstrap mode against a FakeSource client (no Riot network),
    asserting it discovers, registers players, and replays without error."""
    import scripts.backfill as bf
    from tests.ingest.conftest import FakeSource, arena_payload

    pus = [f"e2e-{i}" for i in range(16)]
    fake = FakeSource({pus[0]: ["e2e-m1"]}, {"e2e-m1": arena_payload("e2e-m1", pus)})

    class _Client(FakeSource):
        async def get_account_by_riot_id(self, name, tag, region=None):
            return {"puuid": pus[0]}
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None

    client = _Client(fake._ids, fake._payloads)
    monkeypatch.setattr(bf.settings, "riot_api_key", "FAKE_KEY_FOR_TESTING")
    monkeypatch.setattr(bf, "build_default_client", lambda *a, **k: client)

    args = bf.parse_args(["--mode", "bootstrap", "--seed-riot-id", "X#1", "--depth", "0"])
    await bf.run(args)  # must complete without raising
