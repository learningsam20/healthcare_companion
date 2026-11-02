"""Official ABDM path shapes exist on the local stub."""

from __future__ import annotations

from fastapi.testclient import TestClient

from sahyog_abdm_stub.main import app


client = TestClient(app)


def test_health_uncertified() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["certified"] is False
    assert body["mode"] == "stub"


def test_gateway_session_path() -> None:
    response = client.post("/api/hiecm/gateway/v3/sessions", json={"clientId": "x"})
    assert response.status_code == 200
    body = response.json()
    assert body["certified"] is False
    assert "accessToken" in body


def test_abha_and_consent_families() -> None:
    assert client.post("/abha/api/v3/enrollment/request/otp", json={}).status_code == 200
    assert client.post("/api/hiecm/hip/v3/link/carecontext", json={}).status_code == 200
    init = client.post("/api/hiecm/consent/v3/request/init", json={})
    assert init.status_code == 200
    consent_id = init.json()["consentRequestId"]
    status = client.get(f"/api/hiecm/consent/v3/request/status/{consent_id}")
    assert status.status_code == 200
    assert status.json()["certified"] is False


def test_equality_index() -> None:
    response = client.get("/stub/equality")
    assert response.status_code == 200
    families = response.json()["families"]
    assert "gateway_sessions" in families
    assert "hospital_seam" in families
