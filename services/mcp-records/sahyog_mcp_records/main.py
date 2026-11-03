"""Records MCP tools — call the API internal records surface; never invent evidence."""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID

import httpx
from sahyog_common.context import ExecutionContext
from sahyog_common.http_fallback import request_first
from sahyog_common.mcp_service import create_mcp_app

API_KEY_ENV = os.environ.get("INTERNAL_API_KEY_ENV", "STOCK_API_KEY")


def _headers() -> dict[str, str]:
    key = os.environ.get(API_KEY_ENV, os.environ.get("INTERNAL_API_KEY", "")).strip()
    if not key:
        raise ValueError("Internal API key is not configured for records MCP")
    return {
        "X-Internal-Api-Key": key,
        "X-Stock-Api-Key": key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _patient_id(args: dict[str, Any], context: ExecutionContext) -> str:
    raw = args.get("patient_id") or (str(context.patient_id) if context.patient_id else None)
    if not raw:
        raise ValueError("patient_id is required")
    UUID(str(raw))  # validate
    return str(raw)


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    response = await request_first("GET", path, params=params or {}, headers=_headers(), timeout=20.0)
    response.raise_for_status()
    return response.json()


async def _post(path: str, body: dict[str, Any]) -> Any:
    response = await request_first("POST", path, json_body=body, headers=_headers(), timeout=20.0)
    if response.status_code >= 400:
        raise ValueError(f"records API {response.status_code}: {response.text[:500]}")
    return response.json()


async def list_documents(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    patient_id = _patient_id(args, context)
    try:
        docs = await _get(
            "/api/v1/internal/records/documents",
            {"patient_id": patient_id, "limit": int(args.get("limit") or 20)},
        )
    except (httpx.HTTPError, ValueError) as exc:
        return {"documents": [], "error": str(exc), "source": "records_api"}
    return {"documents": docs if isinstance(docs, list) else [], "source": "records_api"}


async def get_document_status(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    document_id = args.get("document_id")
    if not document_id:
        raise ValueError("document_id is required")
    try:
        status = await _get(f"/api/v1/internal/records/documents/{document_id}/status")
    except (httpx.HTTPError, ValueError) as exc:
        return {"document": None, "error": str(exc), "source": "records_api"}
    return {"document": status, "source": "records_api"}


async def search_records(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    patient_id = _patient_id(args, context)
    query = args.get("query") or args.get("q")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query is required")
    body: dict[str, Any] = {
        "patient_id": patient_id,
        "query": query.strip(),
        "top_k": int(args.get("top_k") or args.get("limit") or 6),
    }
    if args.get("document_id"):
        body["document_id"] = str(args["document_id"])
    try:
        hits = await _post("/api/v1/internal/records/search", body)
    except (httpx.HTTPError, ValueError) as exc:
        return {"results": [], "error": str(exc), "source": "records_api"}
    return {"results": hits if isinstance(hits, list) else [], "source": "records_api"}


async def get_document_chunk(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    chunk_id = args.get("chunk_id")
    if not chunk_id:
        raise ValueError("chunk_id is required")
    try:
        chunk = await _get(f"/api/v1/internal/records/chunks/{chunk_id}")
    except (httpx.HTTPError, ValueError) as exc:
        return {"chunk": None, "error": str(exc), "source": "records_api"}
    return {"chunk": chunk, "source": "records_api"}


async def list_medications(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    patient_id = _patient_id(args, context)
    try:
        payload = await _get("/api/v1/internal/records/medications", {"patient_id": patient_id})
    except (httpx.HTTPError, ValueError) as exc:
        return {"medications": [], "error": str(exc), "source": "records_api"}
    return payload if isinstance(payload, dict) else {"medications": [], "source": "records_api"}


app = create_mcp_app(
    "records",
    {
        "list_documents": (list_documents, "List documents for a patient"),
        "get_document_status": (get_document_status, "Get indexing status for one document"),
        "search_records": (search_records, "Vector search patient records; returns cited snippets"),
        "get_document_chunk": (get_document_chunk, "Fetch one document chunk by id"),
        "list_medications": (list_medications, "List active medications from the medications table"),
    },
)
