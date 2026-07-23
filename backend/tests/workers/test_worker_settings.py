"""The three new WorkerSettings classes are importable and cron-wired."""
from __future__ import annotations

import pytest

from arena.workers.main import (
    BulkProcessorWorker,
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
        BulkProcessorWorker.queue_name,
    ]
    assert len(set(qs)) == len(qs), f"cron worker queues must be unique: {qs}"


def test_sweep_worker_cron_jobs():
    """sweep_tick + rearm_tick + reconcile_tick, all hosted on this pool."""
    assert len(SweepWorker.cron_jobs) == 3
    assert SweepWorker.functions == []


def test_priority_sweep_worker_has_one_cron():
    assert len(PrioritySweepWorker.cron_jobs) == 1


def test_bulk_processor_worker_has_one_cron():
    assert len(BulkProcessorWorker.cron_jobs) == 1


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
