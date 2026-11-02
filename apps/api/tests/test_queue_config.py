from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from app.core import queue as queue_module
from app.core.config import get_settings
from app.scheduler import WorkerSettings as SchedulerWorkerSettings
from app.worker import WorkerSettings as JobWorkerSettings


def test_worker_and_scheduler_poll_distinct_queues() -> None:
    settings = get_settings()
    assert JobWorkerSettings.queue_name == settings.arq_worker_queue
    assert SchedulerWorkerSettings.queue_name == settings.arq_scheduler_queue
    assert JobWorkerSettings.queue_name != SchedulerWorkerSettings.queue_name


def test_enqueue_targets_the_requested_queue(monkeypatch: Any) -> None:
    calls: dict[str, Any] = {}

    class FakePool:
        async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> Any:
            calls["function"] = function
            calls["args"] = args
            calls["kwargs"] = kwargs
            return SimpleNamespace(job_id="job-1")

        async def aclose(self) -> None:
            calls["closed"] = True

    async def fake_create_pool(redis_settings: Any) -> FakePool:
        calls["redis_settings"] = redis_settings
        return FakePool()

    monkeypatch.setattr(queue_module, "create_pool", fake_create_pool)
    job_id = asyncio.run(
        queue_module.enqueue(
            "redis://localhost:6379/0",
            "ingest_document_job",
            "doc-1",
            queue_name="sahyog:worker",
        )
    )

    assert job_id == "job-1"
    assert calls["function"] == "ingest_document_job"
    assert calls["args"] == ("doc-1",)
    assert calls["kwargs"]["_queue_name"] == "sahyog:worker"
    assert calls["closed"] is True
