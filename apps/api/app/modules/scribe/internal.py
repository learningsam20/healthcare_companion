"""Internal clinical tools for MCP (key-auth)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.internal_auth import require_internal_api_key
from app.core.services import Services, get_services
from app.modules.scribe.preconsult import build_preconsult_brief

router = APIRouter(
    prefix="/api/v1/internal/clinical",
    tags=["internal-clinical"],
    dependencies=[Depends(require_internal_api_key)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ServicesDep = Annotated[Services, Depends(get_services)]


class PreconsultIn(BaseModel):
    appointment_id: uuid.UUID | None = None
    patient_id: uuid.UUID | None = None
    doctor_name: str | None = Field(default=None, max_length=120)
    locale: str = "en-IN"


async def _brief(
    session: AsyncSession,
    services: Services,
    *,
    appointment_id: uuid.UUID | None,
    patient_id: uuid.UUID | None,
    doctor_name: str | None,
    locale: str,
) -> dict[str, Any]:
    brief = await build_preconsult_brief(
        session,
        appointment_id=appointment_id,
        patient_id=patient_id,
        doctor_name=doctor_name,
        locale=locale,
        specialty_label_fn=services.specialty_label,
    )
    if brief.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="appointment_not_found")
    if brief.get("status") == "no_patient":
        raise HTTPException(status_code=422, detail="patient_required")
    return brief


@router.get("/preconsult")
async def get_preconsult(
    session: SessionDep,
    services: ServicesDep,
    appointment_id: Annotated[uuid.UUID | None, Query()] = None,
    patient_id: Annotated[uuid.UUID | None, Query()] = None,
    doctor_name: Annotated[str | None, Query(max_length=120)] = None,
    locale: Annotated[str, Query(max_length=10)] = "en-IN",
) -> dict[str, Any]:
    return await _brief(
        session,
        services,
        appointment_id=appointment_id,
        patient_id=patient_id,
        doctor_name=doctor_name,
        locale=locale,
    )


@router.post("/preconsult")
async def post_preconsult(
    body: PreconsultIn,
    session: SessionDep,
    services: ServicesDep,
) -> dict[str, Any]:
    return await _brief(
        session,
        services,
        appointment_id=body.appointment_id,
        patient_id=body.patient_id,
        doctor_name=body.doctor_name,
        locale=body.locale,
    )
