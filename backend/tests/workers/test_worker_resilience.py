"""Resilience: a Redis error inside a cron tick must NOT propagate.

arq does not catch exceptions raised from cron jobs — an uncaught
BusyLoadingError / ConnectionResetError would kill the worker process. Each
tick wraps its body in try/except and returns {"status": "error"} instead.
This is the exact failure that killed a manual backfill (Redis still LOADING
after a docker restart).
"""
from __future__ import annotations

import pytest
from redis.exceptions import BusyLoadingError

from arena.workers.sweep import priority_sweep_tick, sweep_tick

_TICKS = [sweep_tick, priority_sweep_tick]


@pytest.mark.parametrize("tick", _TICKS)
async def test_tick_survives_busy_loading(fake_redis, monkeypatch, tick):
    async def _boom(*a, **k):
        raise BusyLoadingError("Redis is loading the dataset in memory")

    monkeypatch.setattr(fake_redis, "get", _boom)
    result = await tick({"redis": fake_redis})  # must NOT raise
    assert result["status"] == "error"


@pytest.mark.parametrize("tick", _TICKS)
async def test_tick_survives_connection_reset(fake_redis, monkeypatch, tick):
    async def _boom(*a, **k):
        raise ConnectionResetError(64, "network name no longer available")

    monkeypatch.setattr(fake_redis, "get", _boom)
    result = await tick({"redis": fake_redis})
    assert result["status"] == "error"
