"""Small FastAPI kit for internal MCP tool services.

Every service verifies the broker-signed execution context itself, exposes only
declared tools, and caps response size. Tool arguments and results are never logged.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from sahyog_common.context import ContextError, ExecutionContext, verify_context

logger = logging.getLogger(__name__)

ToolHandler = Callable[[dict[str, Any], ExecutionContext], Awaitable[Any] | Any]


class ToolRateLimited(Exception):  # noqa: N818 - control-flow signal, not an error class
    """Raised by a tool handler/wrapper to return HTTP 429 with Retry-After."""

    def __init__(self, retry_after: int = 1) -> None:
        super().__init__("rate_limited")
        self.retry_after = max(1, int(retry_after))


class ToolSpec(BaseModel):
    name: str
    description: str


def _problem(status: int, code: str, title: str, detail: str) -> dict[str, Any]:
    return {
        "type": f"https://errors.sahyog.invalid/{code}",
        "title": title,
        "status": status,
        "code": code,
        "detail": detail,
    }


def create_mcp_app(
    service_name: str,
    tools: dict[str, tuple[ToolHandler, str]],
    *,
    version: str = "0.1.0",
    max_output_chars: int = 12000,
    api_version: str | None = None,
    supported_versions: tuple[str, ...] = (),
    catalogue_extra: dict[str, Any] | None = None,
) -> FastAPI:
    app = FastAPI(
        title=f"Sahyog MCP {service_name}",
        version=version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    secret = os.environ.get("MCP_CONTEXT_SECRET", "")
    max_ttl = int(os.environ.get("MCP_CONTEXT_TTL_SECONDS", "120"))

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"status": "ok", "service": f"mcp-{service_name}"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        ready = bool(secret)
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "ready": ready,
                "service": f"mcp-{service_name}",
                "tools": sorted(tools),
                "context_validation": "enabled" if secret else "unconfigured",
            },
        )

    @app.get("/tools")
    async def catalogue() -> dict[str, Any]:
        payload: dict[str, Any] = {
            "service": f"mcp-{service_name}",
            "tools": [
                ToolSpec(name=name, description=description).model_dump()
                for name, (_, description) in sorted(tools.items())
            ],
        }
        if api_version:
            payload["api_version"] = api_version
            payload["supported_versions"] = list(supported_versions or (api_version,))
        if catalogue_extra:
            payload.update(catalogue_extra)
        return payload

    @app.post("/tools/{tool_name}")
    async def invoke(
        tool_name: str,
        request: Request,
        body: dict[str, Any],
        x_sahyog_context: str | None = Header(default=None),
        x_sahyog_api_version: str | None = Header(default=None),
    ) -> JSONResponse:
        if (
            x_sahyog_api_version
            and supported_versions
            and x_sahyog_api_version not in supported_versions
        ):
            return JSONResponse(
                status_code=400,
                content=_problem(
                    400,
                    "unsupported_api_version",
                    "Unsupported API version",
                    f"Supported versions: {', '.join(supported_versions)}.",
                ),
                media_type="application/problem+json",
            )
        if tool_name not in tools:
            return JSONResponse(
                status_code=404,
                content=_problem(404, "tool_not_found", "Tool not found", "Unknown tool."),
                media_type="application/problem+json",
            )
        if not secret:
            return JSONResponse(
                status_code=503,
                content=_problem(
                    503,
                    "context_unconfigured",
                    "Context validation unavailable",
                    "MCP_CONTEXT_SECRET is not configured.",
                ),
                media_type="application/problem+json",
            )
        if not x_sahyog_context:
            return JSONResponse(
                status_code=401,
                content=_problem(
                    401, "context_required", "Context required", "A signed context is required."
                ),
                media_type="application/problem+json",
            )
        try:
            context = verify_context(x_sahyog_context, secret, max_ttl_seconds=max_ttl)
        except ContextError as exc:
            return JSONResponse(
                status_code=401,
                content=_problem(401, "context_invalid", "Context invalid", str(exc)),
                media_type="application/problem+json",
            )
        handler, _ = tools[tool_name]
        try:
            result = handler(body, context)
            if inspect.isawaitable(result):
                result = await result
        except ToolRateLimited as exc:
            return JSONResponse(
                status_code=429,
                content=_problem(
                    429, "rate_limited", "Rate limit exceeded", "Retry after the indicated delay."
                ),
                media_type="application/problem+json",
                headers={"Retry-After": str(exc.retry_after)},
            )
        except ValueError as exc:
            return JSONResponse(
                status_code=422,
                content=_problem(422, "tool_input_invalid", "Invalid tool input", str(exc)),
                media_type="application/problem+json",
            )
        except Exception:
            logger.exception(
                "tool failed",
                extra={
                    "event": "mcp.tool.failed",
                    "extra_fields": {"service": service_name, "tool": tool_name},
                },
            )
            return JSONResponse(
                status_code=502,
                content=_problem(
                    502, "tool_failed", "Tool failed", "The tool could not complete the request."
                ),
                media_type="application/problem+json",
            )
        serialized = json.dumps(result, ensure_ascii=False, default=str)
        if len(serialized) > max_output_chars:
            serialized = json.dumps(
                {
                    "truncated": True,
                    "tool": tool_name,
                    "preview": serialized[:max_output_chars],
                },
                ensure_ascii=False,
            )
        return JSONResponse(
            content={
                "tool": tool_name,
                "service": f"mcp-{service_name}",
                "trace_id": context.trace_id,
                "result": json.loads(serialized),
            },
            headers={"X-Sahyog-Api-Version": api_version} if api_version else None,
        )

    return app
