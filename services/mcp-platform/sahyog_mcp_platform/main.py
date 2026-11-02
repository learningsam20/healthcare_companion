"""Platform MCP tools — read-only consent/notification/audit via API when configured.

Write tools (send_notification, create_review_task) stay unavailable until an internal
write surface is approved; they return a clear unavailable payload instead of inventing
effects.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from sahyog_common.context import ExecutionContext
from sahyog_common.mcp_service import create_mcp_app

API_BASE = os.environ.get("SAHYOG_API_URL", "http://api:8000").rstrip("/")
API_KEY_ENV = os.environ.get("INTERNAL_API_KEY_ENV", "STOCK_API_KEY")


def _headers() -> dict[str, str]:
    key = os.environ.get(API_KEY_ENV, os.environ.get("INTERNAL_API_KEY", "")).strip()
    return {
        "X-Internal-Api-Key": key,
        "X-Stock-Api-Key": key,
        "Accept": "application/json",
    }


def get_consent(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": "Consent reads stay on the JWT API; MCP returns no invented consent.",
        "actor_subject": context.actor_subject,
        "patient_id": str(context.patient_id) if context.patient_id else None,
    }


def list_notifications(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "notifications": [],
        "reason": "Notification list requires the authenticated notifications API.",
    }


def send_notification(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": "send_notification is not registered for unattended MCP writes in this build.",
    }


def get_audit_event(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    event_id = args.get("event_id")
    if not event_id:
        raise ValueError("event_id is required")
    # No invent: without an internal audit route, refuse.
    return {
        "status": "unavailable",
        "event_id": str(event_id),
        "reason": "Audit events are available via the admin API with JWT, not MCP invent.",
    }


def create_review_task(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": "create_review_task requires the authenticated review queue API.",
    }


# Optional external MCP probe when EXTERNAL_MCP=1 (R3 flag surface).
def external_ping(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    if os.environ.get("EXTERNAL_MCP", "").strip().lower() not in {"1", "true", "yes"}:
        raise ValueError("external_mcp is disabled")
    return {
        "ok": True,
        "mode": "read_only",
        "message": "External MCP probe reachable",
        "trace_id": context.trace_id,
    }


TOOLS: dict[str, tuple[Any, str]] = {
    "get_consent": (get_consent, "Describe consent availability (no invented grants)"),
    "list_notifications": (list_notifications, "List notifications (unavailable stub)"),
    "send_notification": (send_notification, "Send notification (blocked until write surface)"),
    "get_audit_event": (get_audit_event, "Fetch audit event (JWT admin API only)"),
    "create_review_task": (create_review_task, "Create review task (blocked until write surface)"),
}

if os.environ.get("EXTERNAL_MCP", "").strip().lower() in {"1", "true", "yes"}:
    TOOLS["external_ping"] = (external_ping, "Read-only external MCP probe")

app = create_mcp_app("platform", TOOLS)
