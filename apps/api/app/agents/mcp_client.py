"""Signed MCP tool calls through the broker.

Every agent tool call goes through this client. The broker enforces the per-graph
allowlist; this client never talks to an upstream MCP server directly.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from sahyog_common.context import ContextError, ExecutionContext, sign_context

from app.core.config import Settings
from app.core.tracing import content_digest, trace_span


class ToolUnavailable(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class McpToolClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def configured(self) -> bool:
        return bool(self._settings.mcp_broker_url and self._settings.mcp_context_secret)

    async def call(
        self,
        *,
        context: ExecutionContext,
        graph: str,
        tool: str,
        arguments: dict[str, Any],
        timeout_seconds: float = 20.0,
    ) -> dict[str, Any]:
        if not self.configured:
            raise ToolUnavailable("mcp_unconfigured")
        try:
            token = sign_context(context, self._settings.mcp_context_secret)
        except ContextError as exc:
            raise ToolUnavailable("context_unusable") from exc
        attributes = {
            "graph": graph,
            "tool": tool,
            "argument_digest": content_digest(json.dumps(arguments, sort_keys=True, default=str)),
        }
        with trace_span("mcp.tool", attributes, kind="tool"):
            try:
                async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                    response = await client.post(
                        f"{self._settings.mcp_broker_url.rstrip('/')}/tools/invoke",
                        json={"graph": graph, "tool": tool, "arguments": arguments},
                        headers={
                            "X-Sahyog-Context": token,
                            "Content-Type": "application/json",
                        },
                    )
            except httpx.HTTPError as exc:
                raise ToolUnavailable("mcp_unreachable") from exc
            if response.status_code >= 400:
                code = "tool_unavailable"
                try:
                    payload = response.json()
                    if isinstance(payload, dict) and isinstance(payload.get("code"), str):
                        code = str(payload["code"])
                except ValueError:
                    pass
                raise ToolUnavailable(code)
            try:
                payload = response.json()
                result = payload["result"]
            except (KeyError, TypeError, ValueError) as exc:
                raise ToolUnavailable("tool_invalid_response") from exc
            if not isinstance(result, dict):
                raise ToolUnavailable("tool_invalid_response")
            return result
