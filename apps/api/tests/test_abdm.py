from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from app.core.config import Settings
from app.core.errors import register_exception_handlers
from app.core.services import get_services
from app.modules.abdm.router import router
from app.modules.abdm.service import AbdmSandboxClient, AbdmSandboxError
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


class _Features:
    def enabled(self, key: str) -> bool:
        return key == "abdm_link"


@pytest.mark.asyncio
async def test_status_unconfigured() -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    services = SimpleNamespace(
        features=_Features(),
        settings=Settings(_env_file=None, app_env="test", abdm_sandbox_url=""),
    )
    app.dependency_overrides[get_services] = lambda: services

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/abdm/status")

    assert response.status_code == 200
    assert response.json() == {
        "certified": False,
        "sandbox_configured": False,
        "status": "unconfigured",
    }


def test_rejects_non_sandbox_url() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        abdm_sandbox_url="https://abdm.gov.in",
    )
    with pytest.raises(AbdmSandboxError, match="localhost|abdm-stub|sandbox"):
        AbdmSandboxClient(settings)


def test_allows_compose_stub_hostname() -> None:
    client = AbdmSandboxClient(
        Settings(_env_file=None, app_env="test", abdm_sandbox_url="http://abdm-stub:8090")
    )
    assert client.configured is True
    assert client.certified is False


@pytest.mark.asyncio
async def test_link_stores_hash_not_raw_value() -> None:
    class _Result:
        def scalar_one_or_none(self) -> None:
            return None

    class _Session:
        added: Any = None

        async def execute(self, statement: Any) -> _Result:
            return _Result()

        def add(self, row: Any) -> None:
            self.added = row

        async def flush(self) -> None:
            return None

    raw_abha = "91-2345-6789-0123"
    session = _Session()
    client = AbdmSandboxClient(
        Settings(
            _env_file=None,
            app_env="test",
            abdm_sandbox_url="http://localhost:8080",
        )
    )
    row = await client.link(
        session,  # type: ignore[arg-type]
        patient_id=uuid.uuid4(),
        system="abha",
        value=raw_abha,
        created_by="admin-test",
    )

    assert session.added is row
    assert raw_abha not in row.value_enc
    assert row.value_enc.startswith("sha256:")
    assert row.value_enc.endswith("|last4:0123")
