from __future__ import annotations

import pytest

from scripts.backfill import parse_args, resolve_seeds


def test_parse_args_modes_and_defaults():
    a = parse_args(["--mode", "refresh"])
    assert a.mode == "refresh" and a.depth == 3 and a.max_matches is None
    b = parse_args(["--mode", "bootstrap", "--seed-riot-id", "Presente#1001", "--max-matches", "50"])
    assert b.mode == "bootstrap" and b.seed_riot_id == "Presente#1001" and b.max_matches == 50


@pytest.mark.asyncio
async def test_resolve_seeds_bootstrap_uses_account_lookup():
    class _Src:
        async def get_account_by_riot_id(self, name, tag, region=None):
            assert (name, tag) == ("Presente", "1001")
            return {"puuid": "PU-123"}
    seeds = await resolve_seeds(session=None, source=_Src(), mode="bootstrap",
                                seed_riot_id="Presente#1001", region="americas")
    assert seeds == ["PU-123"]
