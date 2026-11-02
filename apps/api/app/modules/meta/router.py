from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core.services import Services, get_services
from app.modules.abdm.service import AbdmSandboxClient, AbdmSandboxError
from app.modules.compliance import service as compliance

logger = logging.getLogger(__name__)
router = APIRouter(tags=["meta"])

DISCLAIMER = (
    "Sahyog Care Companion is a demonstration system using synthetic or public data. "
    "It is not a validated medical device and does not replace professional care."
)


def _channel_status(enabled: bool, configured: bool, adapter: str) -> dict[str, str]:
    if not enabled:
        return {"status": "disabled", "adapter": adapter}
    return {"status": "configured" if configured else "unconfigured", "adapter": adapter}


def _abdm_sandbox_configured(services: Services) -> bool:
    try:
        return AbdmSandboxClient(services.settings).configured
    except AbdmSandboxError:
        return False


def _adapters(services: Services) -> dict[str, Any]:
    settings = services.settings
    features = services.features
    return {
        "email": _channel_status(
            features.enabled("notifications_email"), settings.smtp_configured, "smtp"
        ),
        "sms": _channel_status(
            features.enabled("notifications_sms"),
            settings.sms_configured,
            (settings.sms_adapter or "http").strip().lower() or "http",
        ),
        "slack_staff": _channel_status(
            features.enabled("notifications_slack_staff"),
            settings.slack_staff_configured,
            "slack_bot",
        ),
        "slack_patient": _channel_status(
            features.enabled("notifications_slack_patient"),
            settings.slack_patient_configured,
            "slack_bot",
        ),
        "fhir": {
            "status": (
                "disabled"
                if not features.enabled("fhir_read")
                else "configured"
                if settings.fhir_configured
                else "unconfigured"
            ),
            "adapter": "http",
            "mode": "read_only",
        },
        "abdm_sandbox": {
            "status": (
                "disabled"
                if not features.enabled("abdm_link")
                else "configured"
                if _abdm_sandbox_configured(services)
                else "unconfigured"
            ),
            "adapter": "http",
            "certified": False,
        },
        # G-14: platform-side view of the kill switch. Enforcement lives on the
        # mcp-external container (EXTERNAL_MCP_ENABLED); keep both aligned.
        "external_mcp": {
            "status": "enabled" if features.enabled("external_mcp") else "disabled",
            "adapter": "mcp_signed_context",
            "mode": "read_only",
            "certified": False,
            "kill_switch": "FEATURE_EXTERNAL_MCP + EXTERNAL_MCP_ENABLED",
        },
        "external_llm": {
            "status": "enabled" if settings.external_egress_enabled else "disabled",
            "adapter": "litellm_openrouter",
        },
        "stt": {
            "status": "enabled" if settings.app_profile in {"core", "full"} else "disabled",
            "adapter": settings.stt_adapter,
            "cloud_allowed": bool(settings.allow_cloud_stt),
            "cloud_configured": bool(
                settings.allow_cloud_stt
                and settings.stt_cloud_base_url
                and settings.stt_cloud_api_key
            ),
        },
        "ha": {
            "status": "enabled" if settings.ha_mode else "disabled",
            "mode": bool(settings.ha_mode),
            "checkpointer_required": bool(
                settings.ha_mode or settings.checkpointer_required
            ),
            "multi_region": False,
            "note": "App multi-replica + Postgres checkpointer only; data plane is single-site.",
        },
    }


@router.get("/api/v1/meta")
async def meta(
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, Any]:
    purposes = {
        name: {
            "alias": config.get("primary"),
            "egress": config.get("egress"),
            "timeout_seconds": config.get("timeout_seconds"),
        }
        for name, config in services.models_config.get("purposes", {}).items()
    }
    clinical_status = "not_attested"
    dpdp_status = "not_attested"
    clinically_validated = False
    dpdp_processing_allowed = True
    if getattr(services.settings, "database_url", None):
        try:
            async with services.db.sessionmaker() as session:
                clinical = await compliance.get_attestation(session, compliance.CLINICAL)
                dpdp = await compliance.get_attestation(session, compliance.DPDP)
                clinical_status = clinical.status if clinical else "not_attested"
                dpdp_status = dpdp.status if dpdp else "not_attested"
                clinically_validated = clinical_status == "attested"
                dpdp_processing_allowed = not await compliance.dpdp_blocks_processing(session)
        except Exception as exc:  # noqa: BLE001 — meta must stay available if tables lag
            logger.debug("meta compliance status unavailable: %s", exc)
    return {
        "app": {
            "name": services.settings.app_name,
            "version": services.settings.version,
            "environment": services.settings.app_env,
            "profile": services.settings.app_profile,
            "locales": services.settings.locale_list,
            "default_locale": services.settings.default_locale,
            "timezone": services.app_config.get("app", {}).get("timezone", "Asia/Kolkata"),
        },
        "clinics": services.app_config.get("clinics", []),
        "specialties": [
            {
                "code": item["code"],
                "en": item.get("en", item["code"]),
                "hi": item.get("hi", item.get("en", item["code"])),
                "mr": item.get("mr", item.get("en", item["code"])),
            }
            for item in services.specialties.get("specialties", [])
        ],
        "features": services.features.public(),
        "purposes": purposes,
        "adapters": _adapters(services),
        "disclaimer": DISCLAIMER,
        "capabilities": {
            "chat": services.features.enabled("chat_sessions"),
            "analytics": services.features.enabled("analytics_dashboard"),
            "finops_what_if": services.features.enabled("finops_what_if"),
            "evaluations": services.features.enabled("evaluations"),
            "x01_nursing_summary": services.features.enabled("x01_nursing_summary"),
            "memory_preferences": services.features.enabled("memory_preferences"),
            "abdm_link": services.features.enabled("abdm_link"),
            "abdm_status": {"certified": False},
            "clinically_validated": clinically_validated,
            "clinical_validation_status": clinical_status,
            "dpdp_audit_status": dpdp_status,
            "dpdp_processing_allowed": dpdp_processing_allowed,
        },
    }
