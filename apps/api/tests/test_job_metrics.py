"""G-30 Prometheus job metrics from job_runs."""

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.services import get_services
from app.main import create_app


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None


@pytest.mark.asyncio
async def test_metrics_exports_job_gauges() -> None:
    finished = dt.datetime(2026, 10, 31, 12, 0, tzinfo=dt.UTC)
    calls = {"n": 0}

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, _stmt):  # noqa: ANN001
            calls["n"] += 1
            if calls["n"] == 1:
                return _Result([("analytics.snapshot", finished)])
            if calls["n"] == 2:
                return _Result([("ops.backup", 2)])
            recon = MagicMock()
            recon.variance_pct = 3.5
            recon.status = "variance"
            return _Result([recon])

    services = MagicMock()
    services.settings.database_url = "postgresql+asyncpg://x"
    services.db.sessionmaker = MagicMock(return_value=_Session())

    app = create_app()
    app.dependency_overrides[get_services] = lambda: services

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    body = response.text
    assert "sahyog_job_last_success_timestamp" in body
    assert 'job_name="analytics.snapshot"' in body
    assert str(int(finished.timestamp())) in body
    assert "sahyog_job_failures_total" in body
    assert 'job_name="ops.backup"' in body
    assert "sahyog_finops_variance_pct" in body
    assert "3.5000" in body
    assert "sahyog_finops_variance_over_tolerance 1" in body
