"""Scheduling MCP tools — call the API internal scheduling surface; never invent slots."""

from __future__ import annotations

import os
from typing import Any

import httpx
from sahyog_common.context import ExecutionContext
from sahyog_common.http_fallback import request_first
from sahyog_common.mcp_service import create_mcp_app

API_KEY_ENV = os.environ.get("INTERNAL_API_KEY_ENV", "STOCK_API_KEY")


def _headers() -> dict[str, str]:
    key = os.environ.get(API_KEY_ENV, os.environ.get("INTERNAL_API_KEY", "")).strip()
    if not key:
        raise ValueError("Internal API key is not configured for scheduling MCP")
    return {
        "X-Internal-Api-Key": key,
        "X-Stock-Api-Key": key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    response = await request_first("GET", path, params=params or {}, headers=_headers(), timeout=15.0)
    response.raise_for_status()
    return response.json()


async def _post(path: str, body: dict[str, Any]) -> Any:
    response = await request_first("POST", path, json_body=body, headers=_headers(), timeout=15.0)
    if response.status_code >= 400:
        detail = response.text[:500]
        raise ValueError(f"scheduling API {response.status_code}: {detail}")
    return response.json()


async def search_doctors(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    specialty = args.get("specialty_code") or args.get("specialty")
    clinic = args.get("clinic_code") or (context.clinic_ids[0] if context.clinic_ids else None)
    limit = int(args.get("limit") or 3)
    params: dict[str, Any] = {"limit": limit}
    if isinstance(specialty, str) and specialty.strip():
        params["specialty"] = specialty.strip()
    if isinstance(clinic, str) and clinic.strip():
        params["clinic_code"] = clinic.strip()
    if isinstance(args.get("q"), str) and args["q"].strip():
        params["q"] = args["q"].strip()
    try:
        doctors = await _get("/api/v1/internal/scheduling/doctors", params)
    except (httpx.HTTPError, ValueError) as exc:
        return {"doctors": [], "error": str(exc), "source": "scheduling_api"}
    return {"doctors": doctors if isinstance(doctors, list) else [], "source": "scheduling_api"}


async def get_availability(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    doctor_name = args.get("doctor_name")
    clinic_code = args.get("clinic_code") or (context.clinic_ids[0] if context.clinic_ids else None)
    if not isinstance(doctor_name, str) or not doctor_name.strip():
        raise ValueError("doctor_name is required")
    if not isinstance(clinic_code, str) or not clinic_code.strip():
        raise ValueError("clinic_code is required")
    params: dict[str, Any] = {
        "doctor_name": doctor_name.strip(),
        "clinic_code": clinic_code.strip(),
        "days": int(args.get("days") or 7),
    }
    if isinstance(args.get("specialty_code"), str):
        params["specialty_code"] = args["specialty_code"]
    try:
        slots = await _get("/api/v1/internal/scheduling/slots", params)
    except (httpx.HTTPError, ValueError) as exc:
        return {"slots": [], "error": str(exc), "source": "scheduling_api"}
    return {
        "doctor_name": doctor_name,
        "clinic_code": clinic_code,
        "slots": slots if isinstance(slots, list) else [],
        "source": "scheduling_api",
    }


async def hold_slot(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    required = ("doctor_name", "clinic_code", "specialty_code", "starts_at")
    for key in required:
        if not args.get(key):
            raise ValueError(f"{key} is required")
    body = {
        "doctor_name": str(args["doctor_name"]),
        "clinic_code": str(args["clinic_code"]),
        "specialty_code": str(args["specialty_code"]),
        "starts_at": str(args["starts_at"]),
        "duration_minutes": int(args.get("duration_minutes") or 20),
        "traffic_class": context.traffic_class,
        "patient_id": str(context.patient_id) if context.patient_id else args.get("patient_id"),
        "source": str(args.get("source") or "assistant"),
    }
    result = await _post("/api/v1/internal/scheduling/hold", body)
    return {"appointment": result, "source": "scheduling_api"}


async def confirm_booking(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    appointment_id = args.get("appointment_id")
    if not appointment_id:
        raise ValueError("appointment_id is required")
    result = await _post(
        "/api/v1/internal/scheduling/confirm",
        {"appointment_id": str(appointment_id)},
    )
    return {"appointment": result, "source": "scheduling_api"}


async def cancel_appointment(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    appointment_id = args.get("appointment_id")
    if not appointment_id:
        raise ValueError("appointment_id is required")
    result = await _post(
        "/api/v1/internal/scheduling/cancel",
        {"appointment_id": str(appointment_id)},
    )
    return {"appointment": result, "source": "scheduling_api"}


async def reschedule_appointment(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    appointment_id = args.get("appointment_id")
    starts_at = args.get("starts_at")
    if not appointment_id or not starts_at:
        raise ValueError("appointment_id and starts_at are required")
    body: dict[str, Any] = {
        "appointment_id": str(appointment_id),
        "starts_at": str(starts_at),
    }
    if args.get("duration_minutes") is not None:
        body["duration_minutes"] = int(args["duration_minutes"])
    result = await _post("/api/v1/internal/scheduling/reschedule", body)
    return {"appointment": result, "source": "scheduling_api"}


async def get_appointment(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    appointment_id = args.get("appointment_id")
    if not appointment_id:
        raise ValueError("appointment_id is required")
    try:
        result = await _get(f"/api/v1/internal/scheduling/appointments/{appointment_id}")
    except (httpx.HTTPError, ValueError) as exc:
        return {"appointment": None, "error": str(exc), "source": "scheduling_api"}
    return {"appointment": result, "source": "scheduling_api"}


app = create_mcp_app(
    "scheduling",
    {
        "search_doctors": (search_doctors, "Search clinic doctors by specialty/clinic from the API"),
        "get_availability": (get_availability, "List open slots for a doctor at a clinic"),
        "hold_slot": (hold_slot, "Hold a slot (creates held appointment)"),
        "confirm_booking": (confirm_booking, "Confirm a held appointment"),
        "cancel_appointment": (cancel_appointment, "Cancel a held or confirmed appointment"),
        "reschedule_appointment": (reschedule_appointment, "Move an appointment to a new start time"),
        "get_appointment": (get_appointment, "Fetch one appointment by id"),
    },
)
