from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core.security import AuthContext, get_auth_context

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/me")
async def me(context: Annotated[AuthContext, Depends(get_auth_context)]) -> dict[str, Any]:
    return {
        "subject": context.subject,
        "roles": list(context.roles),
        "primary_role": context.primary_role.value,
        "patient_linked": context.patient_id is not None,
        "patient_id": str(context.patient_id) if context.patient_id else None,
        "consent_id": str(context.consent_id) if context.consent_id else None,
        "clinic_ids": list(context.clinic_ids),
        "locale": context.locale,
        "traffic_class": context.traffic_class,
        "preferred_username": context.preferred_username,
        "display_name": context.display_name,
        "doctor_display_name": context.doctor_display_name,
    }
