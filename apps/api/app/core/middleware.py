from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid

from fastapi import Request, Response
from opentelemetry import trace
from sahyog_common.telemetry import record_http_request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.tracing import export_trace, start_trace

logger = logging.getLogger(__name__)
_TRACE_RE = re.compile(r"^[0-9a-f]{32}$")


class TraceMiddleware(BaseHTTPMiddleware):
    @staticmethod
    def _route(request: Request) -> str:
        route = request.scope.get("route")
        return str(getattr(route, "path", "unmatched"))

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-trace-id", "")
        trace_id = incoming if _TRACE_RE.match(incoming) else uuid.uuid4().hex
        request.state.trace_id = trace_id
        collector = start_trace(trace_id, f"{request.method} {request.url.path}")
        tracer = trace.get_tracer("sahyog.http")
        started = time.perf_counter()
        with tracer.start_as_current_span("http.request") as span:
            span.set_attribute("http.request.method", request.method)
            span.set_attribute("url.path", request.url.path)
            span.set_attribute("sahyog.trace_id", trace_id)
            try:
                response = await call_next(request)
            except Exception:
                span.set_attribute("http.response.status_code", 500)
                record_http_request(
                    method=request.method,
                    route=self._route(request),
                    status_code=500,
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                    traffic_class=getattr(request.state, "traffic_class", "unknown"),
                )
                raise
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            span.set_attribute("http.response.status_code", response.status_code)
            record_http_request(
                method=request.method,
                route=self._route(request),
                status_code=response.status_code,
                duration_ms=duration_ms,
                traffic_class=getattr(request.state, "traffic_class", "unknown"),
            )
            response.headers["X-Trace-Id"] = trace_id
            logger.info(
                "http.request",
                extra={
                    "trace_id": trace_id,
                    "extra_fields": {
                        "method": request.method,
                        "path": request.url.path,
                        "status": response.status_code,
                        "duration_ms": duration_ms,
                    },
                },
            )
            services = getattr(request.app.state, "services", None)
            if services is not None:
                asyncio.create_task(export_trace(services.settings, collector))
            return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, hsts: bool = False) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._hsts = hsts

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault("Cache-Control", "no-store")
        if self._hsts:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response
