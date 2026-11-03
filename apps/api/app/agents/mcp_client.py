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


# Span names follow the MCP server so Langfuse shows decider, clinical, records,
# platform, and pharmacy instead of a single generic tool span. Pharmacy stock
# is the clinical server's get_stock_status tool.
_TOOL_SERVERS: dict[str, str] = {
    "search_doctors": "scheduling",
    "get_availability": "scheduling",
    "hold_slot": "scheduling",
    "confirm_booking": "scheduling",
    "cancel_appointment": "scheduling",
    "reschedule_appointment": "scheduling",
    "get_appointment": "scheduling",
    "list_documents": "records",
    "get_document_status": "records",
    "search_records": "records",
    "get_document_chunk": "records",
    "list_medications": "records",
    "check_red_flags": "clinical",
    "get_specialty_catalogue": "clinical",
    "get_stock_status": "clinical",
    "get_preconsult_brief": "clinical",
    "get_consent": "platform",
    "list_notifications": "platform",
    "send_notification": "platform",
    "get_audit_event": "platform",
    "create_review_task": "platform",
    "classify_intent": "decider",
    "classify_red_flag": "decider",
    "explain_decision": "decider",
    "detect": "pii",
    "redact": "pii",
    "tokenize": "pii",
    "restore_in_private_boundary": "pii",
    "transcribe": "stt",
    "get_transcript": "stt",
    "stt_status": "stt",
}


def _span_name(tool: str) -> tuple[str, str]:
    server = _TOOL_SERVERS.get(tool, "tool")
    if tool == "get_stock_status":
        return "mcp.pharmacy", server
    return f"mcp.{server}", server


class McpToolClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def configured(self) -> bool:
        return bool(
            (self._settings.mcp_broker_url or self._settings.mcp_broker_public_url)
            and self._settings.mcp_context_secret
        )

    def _broker_bases(self) -> list[str]:
        primary = (self._settings.mcp_broker_url or "").strip().rstrip("/")
        public = (self._settings.mcp_broker_public_url or "").strip().rstrip("/")
        bases: list[str] = []
        for item in (primary, public):
            if item and item not in bases:
                bases.append(item)
        return bases

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
        span_name, server = _span_name(tool)
        attributes = {
            "graph": graph,
            "tool": tool,
            "mcp_server": server,
            "argument_digest": content_digest(json.dumps(arguments, sort_keys=True, default=str)),
        }
        with trace_span(span_name, attributes, kind="tool"):
            response: httpx.Response | None = None
            last_error: httpx.HTTPError | None = None
            for base in self._broker_bases():
                try:
                    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                        response = await client.post(
                            f"{base}/tools/invoke",
                            json={"graph": graph, "tool": tool, "arguments": arguments},
                            headers={
                                "X-Sahyog-Context": token,
                                "Content-Type": "application/json",
                            },
                        )
                    last_error = None
                    break
                except httpx.HTTPError as exc:
                    last_error = exc
                    response = None
            if last_error is not None or response is None:
                raise ToolUnavailable("mcp_unreachable") from last_error
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
            # The server envelope is {tool, service, trace_id, result: payload}.
            inner = result.get("result")
            if isinstance(inner, dict) and "service" in result and "tool" in result:
                return inner
            return result
