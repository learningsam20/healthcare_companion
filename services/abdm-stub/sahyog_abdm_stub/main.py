"""ABDM official-path stub.

Path shapes match documented ABDM sandbox/gateway families so hospital code can
exercise mapping against equality docs. Every response sets certified=false and
mode=stub. This is not Health Tech Committee access and not production ABDM.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

app = FastAPI(
    title="Sahyog ABDM Path Stub",
    version="0.1.0",
    description="Official ABDM v3 path shapes only. certified=false always.",
)

_SESSIONS: dict[str, dict[str, Any]] = {}
_BRIDGE: dict[str, Any] = {"url": None, "certs": []}
_CONSENTS: dict[str, dict[str, Any]] = {}
_LINKS: dict[str, dict[str, Any]] = {}


def _stub(**extra: Any) -> dict[str, Any]:
    payload = {
        "certified": False,
        "mode": "stub",
        "disclaimer": "Local ABDM path stub — not sandbox credentials and not certification.",
    }
    payload.update(extra)
    return payload


def _request_id(header_value: str | None) -> str:
    return (header_value or "").strip() or str(uuid.uuid4())


@app.get("/health")
@app.get("/healthz")
async def health() -> dict[str, Any]:
    return _stub(status="ok", service="abdm-stub")


@app.post("/health")
async def health_post() -> dict[str, Any]:
    return _stub(status="ok", service="abdm-stub")


# ---- Gateway (HI ECM) -------------------------------------------------------


@app.post("/api/hiecm/gateway/v3/sessions")
async def gateway_sessions(body: dict[str, Any] | None = None) -> dict[str, Any]:
    token = f"stub-access-{uuid.uuid4().hex}"
    _SESSIONS[token] = {"clientId": (body or {}).get("clientId"), "created": True}
    return _stub(
        accessToken=token,
        expiresIn=3600,
        refreshToken=f"stub-refresh-{uuid.uuid4().hex}",
        tokenType="bearer",
    )


@app.patch("/api/hiecm/gateway/v3/bridge/url")
async def bridge_url(body: dict[str, Any]) -> dict[str, Any]:
    _BRIDGE["url"] = body.get("url") or body.get("callbackUrl")
    return _stub(url=_BRIDGE["url"], updated=True)


@app.get("/api/hiecm/gateway/v3/bridge/url")
async def bridge_url_get() -> dict[str, Any]:
    return _stub(url=_BRIDGE.get("url"))


@app.patch("/api/hiecm/gateway/v3/bridge/certs")
async def bridge_certs(body: dict[str, Any]) -> dict[str, Any]:
    certs = body.get("certs") or body.get("certificates") or []
    _BRIDGE["certs"] = certs if isinstance(certs, list) else [certs]
    return _stub(certs=_BRIDGE["certs"], updated=True)


# ---- M1 ABHA ----------------------------------------------------------------


@app.post("/abha/api/v3/enrollment/request/otp")
async def abha_enrollment_otp(body: dict[str, Any]) -> dict[str, Any]:
    txn = str(uuid.uuid4())
    return _stub(txnId=txn, message="OTP sent (stub)", hint=body.get("loginId"))


@app.post("/abha/api/v3/enrollment/enrol/byAadhaar")
@app.post("/abha/api/v3/enrollment/enrol/byDocument")
async def abha_enrol(body: dict[str, Any]) -> dict[str, Any]:
    return _stub(
        txnId=body.get("txnId") or str(uuid.uuid4()),
        ABHANumber=f"91-{uuid.uuid4().hex[:14]}",
        ABHAProfile={"status": "stub"},
    )


@app.post("/abha/api/v3/profile/login/request/otp")
async def abha_login_otp(body: dict[str, Any]) -> dict[str, Any]:
    return _stub(txnId=str(uuid.uuid4()), message="OTP sent (stub)")


@app.post("/abha/api/v3/profile/login/verify")
async def abha_login_verify(body: dict[str, Any]) -> dict[str, Any]:
    return _stub(
        token=f"stub-abha-{uuid.uuid4().hex}",
        expiresIn=1800,
        refreshToken=f"stub-abha-refresh-{uuid.uuid4().hex}",
    )


@app.get("/abha/api/v3/profile/account")
async def abha_profile() -> dict[str, Any]:
    return _stub(
        ABHANumber="91-0000-0000-0000",
        preferredAbhaAddress="stub@sbx",
        status="ACTIVE",
    )


@app.post("/abha/api/v3/profile/account/abha-card")
async def abha_card() -> dict[str, Any]:
    return _stub(cardAvailable=False, reason="stub_does_not_issue_cards")


@app.get("/abha/api/v3/profile/account/abha-search")
@app.post("/abha/api/v3/phr/web/login/abha/search")
async def abha_search(request: Request) -> dict[str, Any]:
    q = dict(request.query_params)
    return _stub(accounts=[], query=q)


# ---- M2 HIP linking ---------------------------------------------------------


@app.post("/api/hiecm/gateway/v3/hip/token/generate")
@app.post("/v3/hip/token/generate")
async def hip_token(body: dict[str, Any] | None = None) -> dict[str, Any]:
    return _stub(accessToken=f"stub-hip-{uuid.uuid4().hex}", expiresIn=600)


@app.post("/api/hiecm/hip/v3/link/carecontext")
@app.post("/hip/v3/link/carecontext")
async def hip_link_carecontext(body: dict[str, Any]) -> dict[str, Any]:
    link_id = str(uuid.uuid4())
    _LINKS[link_id] = body
    return _stub(linkRefNumber=link_id, status="ACKNOWLEDGED")


@app.post("/api/v3/hip/link/on_carecontext")
@app.post("/api/v3/hip/patient/care-context/on-discover")
@app.post("/api/v3/hip/link/on_init")
@app.post("/api/v3/hip/link/on_confirm")
async def hip_callbacks(
    body: dict[str, Any],
    request_id: str | None = Header(default=None, alias="REQUEST-ID"),
) -> dict[str, Any]:
    return _stub(acknowledged=True, requestId=_request_id(request_id), echo=body)


# ---- M3 HIU consent ---------------------------------------------------------


@app.post("/api/hiecm/consent/v3/request/init")
@app.post("/consent/v3/request/init")
async def consent_init(body: dict[str, Any]) -> dict[str, Any]:
    consent_id = str(uuid.uuid4())
    _CONSENTS[consent_id] = {"status": "REQUESTED", "body": body}
    return _stub(consentRequestId=consent_id, status="REQUESTED")


@app.get("/api/hiecm/consent/v3/request/status/{consent_request_id}")
@app.get("/consent/v3/request/status/{consent_request_id}")
async def consent_status(consent_request_id: str) -> dict[str, Any]:
    row = _CONSENTS.get(consent_request_id) or {"status": "UNKNOWN"}
    return _stub(consentRequestId=consent_request_id, status=row.get("status", "UNKNOWN"))


@app.post("/api/v3/hiu/consent/request/on-init")
@app.post("/api/v3/hiu/consent/request/notify")
async def hiu_callbacks(
    body: dict[str, Any],
    request_id: str | None = Header(default=None, alias="REQUEST-ID"),
) -> JSONResponse:
    return JSONResponse(
        _stub(acknowledged=True, requestId=_request_id(request_id), echo=body)
    )


# ---- Hospital mapping helpers (equality matrix targets) ---------------------


@app.get("/stub/equality")
async def equality_index() -> dict[str, Any]:
    """Machine-readable map of official families → stub paths."""
    return _stub(
        families={
            "gateway_sessions": "POST /api/hiecm/gateway/v3/sessions",
            "bridge_url": "PATCH /api/hiecm/gateway/v3/bridge/url",
            "abha_enrollment_otp": "POST /abha/api/v3/enrollment/request/otp",
            "abha_login_verify": "POST /abha/api/v3/profile/login/verify",
            "hip_link_carecontext": "POST /api/hiecm/hip/v3/link/carecontext",
            "consent_init": "POST /api/hiecm/consent/v3/request/init",
            "hiu_on_init": "POST /api/v3/hiu/consent/request/on-init",
            "hospital_seam": "Sahyog /api/v1/abdm/* (opaque patient_external_ids)",
        },
        documentation="docs/abdm-stub-equality.md",
    )
