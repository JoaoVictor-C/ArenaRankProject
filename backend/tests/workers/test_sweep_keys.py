from __future__ import annotations

import pytest
from pydantic import ValidationError

from arena.core.config import Settings, settings
from arena.workers import queues as Q


def test_config_defaults():
    assert settings.sweep_batch_size == 100
    assert settings.sweep_interval_minutes == 5


def test_interval_must_divide_60():
    with pytest.raises(ValidationError):
        Settings(sweep_interval_minutes=7)
    assert Settings(sweep_interval_minutes=10).sweep_interval_minutes == 10


def test_key_helpers():
    assert Q.worker_enabled_key("sweep") == "arena:worker:enabled:sweep"
    assert Q.worker_tick_lock_key("sweep") == "arena:lock:worker:tick:sweep"
