"""Attach stock tool evidence to draft medicines through the MCP broker."""

from __future__ import annotations

from typing import Any

from app.agents.mcp_client import McpToolClient, ToolUnavailable
from sahyog_common.context import ExecutionContext


async def enrich_medicines(
    *,
    draft: dict[str, Any],
    sources: list[dict[str, Any]],
    tools: McpToolClient,
    context: ExecutionContext,
    clinic_code: str,
    source_label: str,
) -> dict[str, Any]:
    enriched: list[dict[str, Any]] = []
    for index, medicine in enumerate(draft.get("medicines", [])):
        stock = await stock_status(
            tools=tools,
            context=context,
            drug_name=str(medicine["name"]),
            clinic_code=clinic_code,
            source_label=source_label,
        )
        enriched.append({**medicine, "stock": stock})
        sources.append(
            {
                "field": "medicine",
                "line_index": index,
                "source_type": "tool",
                "source_ref": {
                    "tool": "get_stock_status",
                    "graph": "scribe",
                    "clinic_code": clinic_code,
                },
                "status": "resolved" if stock.get("status") != "unknown" else "missing",
                "as_of": stock.get("as_of"),
            }
        )
    return {**draft, "medicines": enriched}


async def stock_status(
    *,
    tools: McpToolClient,
    context: ExecutionContext,
    drug_name: str,
    clinic_code: str,
    source_label: str,
) -> dict[str, Any]:
    try:
        result = await tools.call(
            context=context,
            graph="scribe",
            tool="get_stock_status",
            arguments={"drug_name": drug_name, "clinic_code": clinic_code},
            timeout_seconds=10,
        )
    except ToolUnavailable as exc:
        return {
            "status": "unknown",
            "drug_name": drug_name,
            "clinic_code": clinic_code,
            "source": source_label,
            "reason": exc.code,
            "as_of": None,
            "stale": True,
        }
    return result
