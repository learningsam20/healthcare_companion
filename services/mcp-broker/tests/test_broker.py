from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sahyog_common.context import ExecutionContext, Role, sign_context
from sahyog_common.files import load_yaml
from sahyog_mcp_broker.main import Broker

CONFIG = load_yaml(Path("config/mcp.yaml"))
SECRET = "test-broker-secret-that-is-long-enough-123"


def _broker() -> Broker:
    return Broker(CONFIG, SECRET, 120)


def _token(secret: str = SECRET) -> str:
    now = int(time.time())
    context = ExecutionContext(
        actor_subject="doctor-1",
        actor_role=Role.DOCTOR,
        patient_id=uuid.uuid4(),
        trace_id="trace-1",
        issued_at=now,
        expires_at=now + 60,
    )
    return sign_context(context, secret)


def test_triage_graph_resolves_declared_tool() -> None:
    assert _broker().allowed("triage", "search_doctors") == "scheduling"


def test_tool_outside_graph_is_denied() -> None:
    with pytest.raises(PermissionError, match="not allowed"):
        _broker().allowed("triage", "list_documents")


def test_unknown_graph_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown graph"):
        _broker().allowed("unknown", "search_doctors")


def test_missing_context_is_rejected() -> None:
    from sahyog_mcp_broker.main import app

    app.state.broker = _broker()
    client = TestClient(app)
    response = client.post(
        "/tools/invoke",
        json={"graph": "triage", "tool": "search_doctors", "arguments": {}},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "context_required"


def test_forged_context_is_rejected() -> None:
    from sahyog_mcp_broker.main import app

    app.state.broker = _broker()
    client = TestClient(app)
    response = client.post(
        "/tools/invoke",
        json={"graph": "triage", "tool": "search_doctors", "arguments": {}},
        headers={"X-Sahyog-Context": _token("wrong-secret-that-is-still-long-enough")},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "context_invalid"


def test_forbidden_tool_is_rejected_before_upstream_call() -> None:
    from sahyog_mcp_broker.main import app

    app.state.broker = _broker()
    client = TestClient(app)
    response = client.post(
        "/tools/invoke",
        json={"graph": "triage", "tool": "list_documents", "arguments": {}},
        headers={"X-Sahyog-Context": _token()},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "tool_forbidden"


def test_catalogue_only_returns_declared_tools() -> None:
    from sahyog_mcp_broker.main import app

    app.state.broker = _broker()
    client = TestClient(app)
    response = client.get("/tools/catalogue", params={"graph": "triage"})
    body = response.json()
    tools = {item["tool"] for item in body["tools"]}
    assert "search_doctors" in tools
    assert "list_documents" not in tools
