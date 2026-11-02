"""DPDP stop-processing middleware (G-19)."""

from __future__ import annotations

import json
import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.modules.compliance import service as compliance

logger = logging.getLogger(__name__)

# Patient-linked surfaces blocked when DPDP disapproves / enforce without attestation.
# Privacy export/deletion and admin/compliance/meta/health stay reachable.
_BLOCKED_PREFIXES = (
    "/api/v1/patients",
    "/api/v1/chat",
    "/api/v1/scribe",
    "/api/v1/records",
    "/api/v1/scheduling",
    "/api/v1/pharmacy",
    "/api/v1/nursing",
    "/api/v1/memory",
    "/api/v1/handoffs",
    "/api/v1/fhir",
    "/api/v1/abdm",
    "/api/v1/review",
)

_ALWAYS_ALLOW_PREFIXES = (
    "/api/v1/health",
    "/api/v1/meta",
    "/api/v1/admin",
    "/api/v1/privacy",
    "/api/v1/auth",
    "/api/v1/consents",
    "/api/v1/notifications",
    "/api/v1/analytics",
    "/api/v1/incidents",
    "/docs",
    "/openapi.json",
    "/redoc",
)


def _path_blocked(path: str) -> bool:
    if any(path.startswith(prefix) for prefix in _ALWAYS_ALLOW_PREFIXES):
        return False
    return any(path.startswith(prefix) for prefix in _BLOCKED_PREFIXES)


class DpdpStopProcessingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method == "OPTIONS" or not _path_blocked(request.url.path):
            return await call_next(request)
        services = getattr(request.app.state, "services", None)
        if services is None or not getattr(services.settings, "database_url", None):
            return await call_next(request)
        try:
            async with services.db.sessionmaker() as session:
                blocked = await compliance.dpdp_blocks_processing(session)
        except Exception as exc:
            logger.warning(
                "dpdp guard check failed; allowing request",
                exc_info=exc,
                extra={"event": "compliance.dpdp_guard_error"},
            )
            return await call_next(request)
        if not blocked:
            return await call_next(request)
        body = {
            "type": "about:blank",
            "title": "Processing stopped",
            "status": 403,
            "code": "dpdp_processing_stopped",
            "detail": (
                "Patient-linked processing is stopped pending DPDP audit approval "
                "(or after explicit disapproval). Privacy export/deletion remains available."
            ),
        }
        return JSONResponse(
            status_code=403,
            content=body,
            media_type="application/problem+json",
            headers={"X-Sahyog-Dpdp-Blocked": "1"},
        )


def problem_json(detail: str) -> str:
    return json.dumps({"detail": detail})
