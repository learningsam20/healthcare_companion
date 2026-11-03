"""Clinical MCP tools that do not need the application database.

`check_red_flags` runs the deterministic rule set. `get_specialty_catalogue` exposes the
closed specialty list so a model cannot invent one. `get_stock_status` calls the pharmacy
API (DB-backed stock_items) — never invents quantities.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any

import httpx
from sahyog_common.context import ExecutionContext
from sahyog_common.files import config_dir, load_yaml
from sahyog_common.http_fallback import candidate_urls, request_first
from sahyog_common.mcp_service import create_mcp_app
from sahyog_common.red_flags import detect_red_flags

CONFIG_DIR = config_dir()
RED_FLAGS = load_yaml(CONFIG_DIR / "red_flags.yaml")
SPECIALTIES = load_yaml(CONFIG_DIR / "specialties.yaml")
STOCK = load_yaml(CONFIG_DIR / "stock.yaml")


def check_red_flags(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    text = args.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text is required")
    locale = args.get("locale", context.locale)
    if not isinstance(locale, str):
        raise ValueError("locale must be a string")
    matches = detect_red_flags(text, RED_FLAGS, locale)
    return {
        "engine": "deterministic_rules",
        "rule_version": RED_FLAGS.get("version"),
        "locale": locale,
        "count": len(matches),
        "matches": [asdict(match) for match in matches],
        "requires_emergency_action": any(match.severity == "emergency" for match in matches),
    }


def get_specialty_catalogue(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    return {
        "version": SPECIALTIES.get("version"),
        "specialties": SPECIALTIES.get("specialties", []),
    }


async def get_stock_status(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    drug_name = args.get("drug_name")
    clinic_code = args.get("clinic_code")
    if not isinstance(drug_name, str) or not drug_name.strip():
        raise ValueError("drug_name is required")
    if not isinstance(clinic_code, str) or not clinic_code.strip():
        raise ValueError("clinic_code is required")

    source = str(STOCK.get("source_label", "stock"))
    adapter = str(STOCK.get("adapter", "api")).strip().lower()
    if adapter != "api":
        return {
            "status": "unknown",
            "drug_name": drug_name,
            "clinic_code": clinic_code,
            "source": source,
            "reason": "stock adapter must be api",
            "as_of": None,
            "stale": True,
        }

    url = str(STOCK.get("api_url", "")).strip()
    key_env = str(STOCK.get("api_key_env", "STOCK_API_KEY"))
    api_key = os.environ.get(key_env, "").strip()
    urls = candidate_urls(url)
    if not urls or not api_key:
        return {
            "status": "unknown",
            "drug_name": drug_name,
            "clinic_code": clinic_code,
            "source": source,
            "reason": "stock API is not configured",
            "as_of": None,
            "stale": True,
        }

    payload: Any = None
    last_error: Exception | None = None
    for index, candidate in enumerate(urls):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    candidate,
                    params={"drug_name": drug_name.strip(), "clinic_code": clinic_code.strip()},
                    headers={"X-Stock-Api-Key": api_key, "Accept": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
            last_error = None
            break
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if index < len(urls) - 1:
                continue
    if last_error is not None or payload is None:
        return {
            "status": "unknown",
            "drug_name": drug_name,
            "clinic_code": clinic_code,
            "source": source,
            "reason": f"stock API unavailable: {last_error}",
            "as_of": None,
            "stale": True,
        }

    if not isinstance(payload, dict):
        return {
            "status": "unknown",
            "drug_name": drug_name,
            "clinic_code": clinic_code,
            "source": source,
            "reason": "stock API returned an invalid response",
            "as_of": None,
            "stale": True,
        }
    return payload


async def get_preconsult_brief(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    """Doctor pre-consult brief from appointments, meds, documents, and signed notes."""
    key_env = os.environ.get("INTERNAL_API_KEY_ENV", "STOCK_API_KEY")
    api_key = os.environ.get(key_env, os.environ.get("INTERNAL_API_KEY", "")).strip()
    if not api_key:
        return {"status": "unavailable", "reason": "internal API key not configured"}

    params: dict[str, Any] = {"locale": args.get("locale") or context.locale or "en-IN"}
    if args.get("appointment_id"):
        params["appointment_id"] = str(args["appointment_id"])
    if args.get("patient_id"):
        params["patient_id"] = str(args["patient_id"])
    if args.get("doctor_name"):
        params["doctor_name"] = str(args["doctor_name"])
    elif getattr(context, "doctor_display_name", None):
        params["doctor_name"] = str(context.doctor_display_name)

    try:
        response = await request_first(
            "GET",
            "/api/v1/internal/clinical/preconsult",
            params=params,
            headers={"X-Internal-Api-Key": api_key, "Accept": "application/json"},
            timeout=15.0,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"status": "unavailable", "reason": f"preconsult API unavailable: {exc}"}
    if not isinstance(payload, dict):
        return {"status": "unavailable", "reason": "invalid preconsult payload"}
    return payload


app = create_mcp_app(
    "clinical",
    {
        "check_red_flags": (
            check_red_flags,
            "Run deterministic red-flag rules over text. Returns rule IDs and guidance only.",
        ),
        "get_specialty_catalogue": (
            get_specialty_catalogue,
            "Return the closed specialty catalogue used to validate specialty codes.",
        ),
        "get_stock_status": (
            get_stock_status,
            "Return pharmacy stock quantity, clinic, source, as_of and stale flag via the stock API.",
        ),
        "get_preconsult_brief": (
            get_preconsult_brief,
            "Return a pre-consult brief from real appointments, meds, documents, and signed notes.",
        ),
    },
)
