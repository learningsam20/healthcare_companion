"""One MCP surface for model tool calls.

LiteLLM never sees upstream MCP servers. It calls this broker with a graph name, a tool
name and arguments. The broker verifies the server-signed execution context, enforces
the per-graph allowlist and forwards only declared tools.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sahyog_common.context import ContextError, verify_context
from sahyog_common.files import config_dir, load_yaml
from sahyog_common.logging import configure_logging

logger = logging.getLogger(__name__)
MAX_OUTPUT_CHARS = 12000


class InvokeRequest(BaseModel):
    graph: str = Field(min_length=2, max_length=40)
    tool: str = Field(min_length=2, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)


def _problem(status: int, code: str, title: str, detail: str) -> dict[str, Any]:
    return {
        "type": f"https://errors.sahyog.invalid/{code}",
        "title": title,
        "status": status,
        "code": code,
        "detail": detail,
    }


class Broker:
    def __init__(self, config: dict[str, Any], secret: str, ttl_seconds: int) -> None:
        self._config = config
        self._secret = secret
        self._ttl = ttl_seconds
        self._servers: dict[str, dict[str, Any]] = config.get("servers", {})
        self._graphs: dict[str, dict[str, Any]] = config.get("graphs", {})
        self._tool_to_server: dict[str, str] = {
            tool: name for name, server in self._servers.items() for tool in server.get("tools", [])
        }

    @property
    def configured(self) -> bool:
        return bool(self._secret)

    def allowed(self, graph: str, tool: str) -> str:
        graph_config = self._graphs.get(graph)
        if graph_config is None:
            raise ValueError(f"unknown graph {graph}")
        if tool not in graph_config.get("tools", []):
            raise PermissionError(f"tool {tool} is not allowed for graph {graph}")
        server = self._tool_to_server.get(tool)
        if server is None:
            raise PermissionError(f"tool {tool} has no upstream server")
        if server not in graph_config.get("servers", []):
            raise PermissionError(f"server {server} is not allowed for graph {graph}")
        return server

    async def forward(
        self, *, server: str, tool: str, arguments: dict[str, Any], context_token: str
    ) -> dict[str, Any]:
        server_config = self._servers[server]
        url = f"{str(server_config['url']).rstrip('/')}/tools/{tool}"
        timeout = float(server_config.get("timeout_seconds", 30))
        headers = {"X-Sahyog-Context": context_token, "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=arguments, headers=headers)
        if response.status_code >= 400:
            raise UpstreamError(response.status_code, response.text[:500])
        payload: dict[str, Any] = response.json()
        serialized = json.dumps(payload, ensure_ascii=False)
        if len(serialized) > MAX_OUTPUT_CHARS:
            return {
                "truncated": True,
                "preview": serialized[:MAX_OUTPUT_CHARS],
            }
        return payload

    async def upstream_health(self) -> list[dict[str, Any]]:
        async def check(name: str, server: dict[str, Any]) -> dict[str, Any]:
            url = f"{str(server['url']).rstrip('/')}/healthz"
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    response = await client.get(url)
                return {"name": name, "status": "up" if response.status_code < 500 else "down"}
            except httpx.HTTPError:
                return {"name": name, "status": "down"}

        return list(
            await asyncio.gather(
                *(check(name, server) for name, server in sorted(self._servers.items()))
            )
        )


class UpstreamError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _broker(request: Request) -> Broker:
    broker: Broker = request.app.state.broker
    return broker


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    raw_path = Path(os.environ.get("MCP_CONFIG_PATH", config_dir() / "mcp.yaml"))
    config = load_yaml(raw_path)
    secret = os.environ.get("MCP_CONTEXT_SECRET", "")
    ttl = int(os.environ.get("MCP_CONTEXT_TTL_SECONDS", "120"))
    if not secret and os.environ.get("APP_ENV", "dev") == "production":
        raise RuntimeError("MCP_CONTEXT_SECRET is required in production")
    app.state.broker = Broker(config, secret, ttl)
    yield


app = FastAPI(
    title="Sahyog MCP broker",
    version=os.environ.get("APP_VERSION", "0.1.0"),
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "mcp-broker"}


@app.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    broker = _broker(request)
    checks = await broker.upstream_health()
    ready = broker.configured and all(item["status"] == "up" for item in checks)
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "ready": ready,
            "service": "mcp-broker",
            "context_validation": "enabled" if broker.configured else "unconfigured",
            "servers": checks,
            "checked_at": dt.datetime.now(dt.UTC).isoformat(),
        },
    )


@app.get("/tools/catalogue")
async def catalogue(request: Request, graph: str) -> dict[str, Any]:
    broker = _broker(request)
    try:
        graph_config = broker._graphs[graph]  # noqa: SLF001
    except KeyError:
        return {"graph": graph, "tools": [], "status": "unknown_graph"}
    tools = [
        {"tool": tool, "server": broker._tool_to_server.get(tool)}  # noqa: SLF001
        for tool in graph_config.get("tools", [])
        if tool in broker._tool_to_server  # noqa: SLF001
    ]
    return {"graph": graph, "tools": tools}


@app.post("/tools/invoke")
async def invoke(
    body: InvokeRequest,
    request: Request,
    x_sahyog_context: Annotated[str | None, Header(alias="X-Sahyog-Context")] = None,
) -> JSONResponse:
    broker = _broker(request)
    if not broker.configured:
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
        context = verify_context(
            x_sahyog_context,
            broker._secret,
            max_ttl_seconds=broker._ttl,  # noqa: SLF001
        )
    except ContextError as exc:
        return JSONResponse(
            status_code=401,
            content=_problem(401, "context_invalid", "Context invalid", str(exc)),
            media_type="application/problem+json",
        )
    try:
        server = broker.allowed(body.graph, body.tool)
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content=_problem(404, "graph_not_found", "Graph not found", str(exc)),
            media_type="application/problem+json",
        )
    except PermissionError as exc:
        return JSONResponse(
            status_code=403,
            content=_problem(403, "tool_forbidden", "Tool not allowed", str(exc)),
            media_type="application/problem+json",
        )
    try:
        result = await broker.forward(
            server=server,
            tool=body.tool,
            arguments=body.arguments,
            context_token=x_sahyog_context,
        )
    except UpstreamError as exc:
        logger.warning(
            "mcp upstream error",
            extra={
                "event": "mcp.upstream.error",
                "extra_fields": {"server": server, "tool": body.tool, "status": exc.status},
            },
        )
        return JSONResponse(
            status_code=502,
            content=_problem(
                502,
                "tool_unavailable",
                "Tool unavailable",
                "The upstream MCP service rejected or failed the call.",
            ),
            media_type="application/problem+json",
        )
    except httpx.HTTPError:
        logger.warning(
            "mcp upstream unreachable",
            extra={
                "event": "mcp.upstream.unreachable",
                "extra_fields": {"server": server, "tool": body.tool},
            },
        )
        return JSONResponse(
            status_code=502,
            content=_problem(
                502,
                "tool_unavailable",
                "Tool unavailable",
                "The upstream MCP service is unreachable.",
            ),
            media_type="application/problem+json",
        )
    return JSONResponse(
        content={
            "graph": body.graph,
            "tool": body.tool,
            "server": server,
            "trace_id": context.trace_id,
            "as_of": dt.datetime.now(dt.UTC).isoformat(),
            "result": result,
        }
    )
