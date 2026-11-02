"""G-14 external MCP conformance: signed-context refusal + kill switch."""

from __future__ import annotations

import inspect
import time

import pytest
from fastapi.testclient import TestClient
from sahyog_common.context import ExecutionContext, Role, sign_context
from sahyog_common.mcp_service import create_mcp_app

SECRET = "test-external-mcp-secret-that-is-long-enough"


def _token(secret: str = SECRET) -> str:
    now = int(time.time())
    context = ExecutionContext(
        actor_subject="partner:demo",
        actor_role=Role.SERVICE,
        patient_id=None,
        trace_id="trace-conformance",
        issued_at=now,
        expires_at=now + 60,
    )
    return sign_context(context, secret)


def _enabled_tools():
    from sahyog_mcp_external import main as mod

    return {
        "ping": (mod.ping, "Liveness probe for external MCP consumers"),
        "search_doctors": (mod.search_doctors, "Read-only doctor shortlist"),
        "get_stock_status": (mod.get_stock_status, "Read-only pharmacy stock lookup"),
    }


def test_tools_empty_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTERNAL_MCP_ENABLED", "false")
    from sahyog_mcp_external import main as mod

    assert mod._enabled() is False
    assert "create" not in " ".join(mod.TOOLS.keys()).lower()


def test_http_catalogue_empty_when_kill_switch_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """EXTERNAL_MCP_ENABLED=false → empty catalogue (mirrors main.py import path)."""
    monkeypatch.setenv("EXTERNAL_MCP_ENABLED", "false")
    monkeypatch.setenv("MCP_CONTEXT_SECRET", SECRET)
    app = create_mcp_app("external", {})
    client = TestClient(app)
    body = client.get("/tools").json()
    assert body["tools"] == []
    response = client.post("/tools/ping", json={})
    assert response.status_code == 404
    assert response.json()["code"] == "tool_not_found"


def test_invoke_refuses_missing_signed_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTERNAL_MCP_ENABLED", "true")
    monkeypatch.setenv("MCP_CONTEXT_SECRET", SECRET)
    app = create_mcp_app("external", _enabled_tools())
    client = TestClient(app)
    response = client.post("/tools/ping", json={})
    assert response.status_code == 401
    assert response.json()["code"] == "context_required"


def test_invoke_refuses_forged_signed_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTERNAL_MCP_ENABLED", "true")
    monkeypatch.setenv("MCP_CONTEXT_SECRET", SECRET)
    app = create_mcp_app("external", _enabled_tools())
    client = TestClient(app)
    response = client.post(
        "/tools/ping",
        json={},
        headers={"X-Sahyog-Context": _token("wrong-secret-that-is-still-long-enough-xx")},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "context_invalid"


@pytest.mark.asyncio
async def test_ping_exposes_actor_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTERNAL_MCP_ENABLED", "true")
    from sahyog_mcp_external import main as mod

    class Ctx:
        actor_subject = "partner:demo"
        trace_id = "trace-conformance"

    result = mod.ping({}, Ctx())
    if inspect.isawaitable(result):
        result = await result
    assert result["mode"] == "read_only"
    assert result["actor"] == "partner:demo"
    assert result["trace_id"] == "trace-conformance"


def test_valid_signed_context_reaches_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTERNAL_MCP_ENABLED", "true")
    monkeypatch.setenv("MCP_CONTEXT_SECRET", SECRET)
    app = create_mcp_app("external", _enabled_tools())
    client = TestClient(app)
    response = client.post(
        "/tools/ping",
        json={},
        headers={"X-Sahyog-Context": _token()},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["ok"] is True
    assert body["result"]["actor"] == "partner:demo"
    assert body["trace_id"] == "trace-conformance"


def test_create_mcp_app_accepts_empty_catalogue() -> None:
    app = create_mcp_app("external_conformance", {})
    assert app is not None


def test_quota_limiter_enforces_per_actor_window() -> None:
    from sahyog_common.mcp_service import ToolRateLimited
    from sahyog_mcp_external.main import QuotaLimiter

    now = [0.0]
    limiter = QuotaLimiter(
        default_rpm=2, consumers={"partner:vip": 3}, clock=lambda: now[0], window_seconds=60
    )
    limiter.check("partner:a")
    limiter.check("partner:a")
    with pytest.raises(ToolRateLimited) as exc:
        limiter.check("partner:a")
    assert exc.value.retry_after >= 1
    limiter.check("partner:b")  # separate actor
    for _ in range(3):
        limiter.check("partner:vip")
    with pytest.raises(ToolRateLimited):
        limiter.check("partner:vip")
    now[0] = 61.0
    limiter.check("partner:a")  # window slid


def test_contract_file_declares_versioning_and_quota() -> None:
    from sahyog_mcp_external.main import QuotaLimiter, load_contract

    contract = load_contract()
    assert contract["source"] == "file"
    assert contract["api_version"] in contract["supported_versions"]
    assert QuotaLimiter.from_contract(contract).limit_for("anyone") >= 1
    assert all(tool["read_only"] is True for tool in contract["tools"].values())


def test_http_429_with_retry_after_and_version_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    from sahyog_mcp_external import main as mod

    monkeypatch.setenv("EXTERNAL_MCP_ENABLED", "true")
    monkeypatch.setenv("MCP_CONTEXT_SECRET", SECRET)
    monkeypatch.setattr(mod, "LIMITER", mod.QuotaLimiter(default_rpm=1))
    app = create_mcp_app(
        "external",
        {"ping": (mod._limited(mod.ping), "ping")},
        api_version="v1",
        supported_versions=("v1",),
    )
    client = TestClient(app)
    headers = {"X-Sahyog-Context": _token()}
    first = client.post("/tools/ping", json={}, headers=headers)
    assert first.status_code == 200
    assert first.headers["X-Sahyog-Api-Version"] == "v1"
    second = client.post("/tools/ping", json={}, headers=headers)
    assert second.status_code == 429
    assert second.json()["code"] == "rate_limited"
    assert int(second.headers["Retry-After"]) >= 1


def test_unsupported_api_version_rejected_and_catalogue_reports_version() -> None:
    app = create_mcp_app(
        "external",
        {},
        api_version="v1",
        supported_versions=("v1",),
        catalogue_extra={"read_only": True},
    )
    client = TestClient(app)
    body = client.get("/tools").json()
    assert body["api_version"] == "v1" and body["supported_versions"] == ["v1"]
    assert body["read_only"] is True
    refused = client.post("/tools/ping", json={}, headers={"X-Sahyog-Api-Version": "v9"})
    assert refused.status_code == 400
    assert refused.json()["code"] == "unsupported_api_version"
