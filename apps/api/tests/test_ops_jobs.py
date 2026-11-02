"""G-30 scheduled backup + stock-import job stubs (unit-level, no Docker)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.ops.jobs import OpsJobUnconfigured, run_scheduled_backup, run_stock_drop_import
from app.scheduler import WorkerSettings as SchedulerWorkerSettings
from app.worker import WorkerSettings as JobWorkerSettings


def test_scheduler_registers_backup_cron() -> None:
    names = {fn.__name__ for fn in SchedulerWorkerSettings.functions}
    assert "scheduled_backup_job" in names
    assert "handoff_sla_job" in names
    assert "audit_verify_job" in names
    cron_names = {job.coroutine.__name__ for job in SchedulerWorkerSettings.cron_jobs}
    assert "handoff_sla_job" in cron_names
    assert "scheduled_backup_job" in cron_names
    assert "audit_verify_job" in cron_names


def test_worker_registers_stock_import_cron() -> None:
    names = {fn.__name__ for fn in JobWorkerSettings.functions}
    assert "import_pharmacy_stock" in names
    cron_names = {job.coroutine.__name__ for job in JobWorkerSettings.cron_jobs}
    assert "import_pharmacy_stock" in cron_names


@pytest.mark.asyncio
async def test_backup_fails_visibly_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[Any] = []

    class _JobCtx:
        def __init__(self) -> None:
            self.run = SimpleNamespace(detail={}, status="running", error_code=None, finished_at=None)

        async def __aenter__(self) -> tuple[Any, Any]:
            runs.append(self.run)
            return SimpleNamespace(), self.run

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            if exc_type is not None:
                self.run.status = "failed"
                self.run.error_code = exc_type.__name__[:80]
            else:
                self.run.status = "succeeded"
            return False

    monkeypatch.setattr("app.modules.ops.jobs._job", lambda _services, _name: _JobCtx())
    services = SimpleNamespace(settings=SimpleNamespace(backup_out_dir=""))

    with pytest.raises(OpsJobUnconfigured, match="backup_unconfigured"):
        await run_scheduled_backup(services)  # type: ignore[arg-type]

    assert runs[0].detail["configured"] is False
    assert runs[0].detail["error_code"] == "backup_unconfigured"
    assert runs[0].status == "failed"


@pytest.mark.asyncio
async def test_stock_import_fails_when_drop_dir_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[Any] = []

    class _JobCtx:
        def __init__(self) -> None:
            self.run = SimpleNamespace(detail={}, status="running", error_code=None, finished_at=None)

        async def __aenter__(self) -> tuple[Any, Any]:
            runs.append(self.run)
            return SimpleNamespace(), self.run

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            if exc_type is not None:
                self.run.status = "failed"
            else:
                self.run.status = "succeeded"
            return False

    monkeypatch.setattr("app.modules.ops.jobs._job", lambda _services, _name: _JobCtx())
    services = SimpleNamespace(stock_config={})

    with pytest.raises(OpsJobUnconfigured, match="stock_drop_unconfigured"):
        await run_stock_drop_import(services)  # type: ignore[arg-type]

    assert runs[0].detail["error_code"] == "stock_drop_unconfigured"


@pytest.mark.asyncio
async def test_stock_import_records_drop_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[Any] = []

    class _JobCtx:
        def __init__(self) -> None:
            self.run = SimpleNamespace(detail={}, status="running")

        async def __aenter__(self) -> tuple[Any, Any]:
            runs.append(self.run)
            return SimpleNamespace(), self.run

        async def __aexit__(self, *_args: Any) -> bool:
            self.run.status = "succeeded"
            return False

    monkeypatch.setattr("app.modules.ops.jobs._job", lambda _services, _name: _JobCtx())

    class _Pharmacy:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        async def import_drop_directory(self) -> dict[str, Any]:
            return {"processed": 0, "files": []}

    monkeypatch.setattr("app.modules.ops.jobs.PharmacyService", _Pharmacy)
    services = SimpleNamespace(stock_config={"drop_dir": "data/stock/incoming"})
    payload = await run_stock_drop_import(services)  # type: ignore[arg-type]
    assert payload["processed"] == 0
    assert runs[0].detail["configured"] is True
