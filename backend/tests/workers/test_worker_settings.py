"""The WorkerSettings classes are importable and correctly wired."""
from __future__ import annotations

import pytest

from arena.workers.main import (
    IngestionWorker,
    PriorityWorker,
    PrioritySweepWorker,
    SchedulerWorker,
    StandardWorker,
    SweepWorker,
)


def test_cron_workers_have_distinct_queues():
    """Each cron worker needs its OWN arq queue, else one worker dequeues a cron
    job whose function it doesn't have registered ('function not found')."""
    qs = [
        IngestionWorker.queue_name,
        SchedulerWorker.queue_name,
        SweepWorker.queue_name,
        PrioritySweepWorker.queue_name,
    ]
    assert len(set(qs)) == len(qs), f"cron worker queues must be unique: {qs}"


def test_sweep_worker_cron_jobs():
    """sweep + rearm + reconcile + backfill ticks, all hosted on this pool."""
    assert len(SweepWorker.cron_jobs) == 4
    names = {job.name for job in SweepWorker.cron_jobs}
    assert names == {
        "cron:sweep_tick",
        "cron:rearm_tick",
        "cron:reconcile_tick",
        "cron:backfill_tick",
    }
    assert SweepWorker.functions == []


def test_priority_sweep_worker_cron_jobs():
    """priority_sweep + recent_activity_sweep ticks, both hosted on this pool —
    the latter closes the coverage gap for non-priority (low-CR/casual) players,
    see Settings.recent_activity_enabled's docstring."""
    assert len(PrioritySweepWorker.cron_jobs) == 2
    names = {job.name for job in PrioritySweepWorker.cron_jobs}
    assert names == {"cron:priority_sweep_tick", "cron:recent_activity_sweep_tick"}
    assert PrioritySweepWorker.functions == []


def test_consumer_workers_have_distinct_queues():
    """StandardWorker/PriorityWorker are continuous consumers — no cron_jobs
    attribute at all (unlike the cron pools above), each bound to its own arq
    queue_name."""
    assert StandardWorker.queue_name != PriorityWorker.queue_name
    assert "cron_jobs" not in StandardWorker.__dict__
    assert "cron_jobs" not in PriorityWorker.__dict__


@pytest.mark.parametrize("worker", [StandardWorker, PriorityWorker])
def test_consumer_worker_config_is_on_leaf_dict(worker):
    """arq 0.28 get_kwargs reads settings from ``cls.__dict__`` (NOT inherited).

    A consumer that only sets ``queue_name`` and inherits ``functions`` from a
    base would boot with no registered function -> RuntimeError. Guard that the
    shared config is flattened onto each leaf class's own __dict__.
    """
    d = worker.__dict__
    assert d.get("functions"), f"{worker.__name__}.functions missing from __dict__"
    assert "redis_settings" in d, f"{worker.__name__}.redis_settings missing"
    assert "queue_name" in d
    assert "on_startup" in d and "on_shutdown" in d
