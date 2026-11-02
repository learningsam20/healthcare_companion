from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sahyog_common.errors import ProblemError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import AuthContext, Role, require_roles
from app.core.services import Services, get_services
from app.modules.abdm.schemas import LinkOut, LinkRequest, StatusOut
from app.modules.abdm.service import AbdmSandboxClient, AbdmSandboxError
from app.repositories.audit import AuditRepository
from app.repositories.models import PatientExternalId
from app.repositories.patients import PatientRepository

router = APIRouter(prefix="/api/v1/abdm", tags=["abdm"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ServicesDep = Annotated[Services, Depends(get_services)]
AdminAccess = Annotated[AuthContext, Depends(require_roles(Role.ADMIN))]


def _require_feature(services: Services) -> None:
    if not services.features.enabled("abdm_link"):
        raise ProblemError(
            409,
            "abdm_disabled",
            "ABDM link is disabled",
            "Enable the startup-only abdm_link feature to use the sandbox seam.",
        )


def _client(services: Services) -> AbdmSandboxClient:
    try:
        return AbdmSandboxClient(services.settings)
    except AbdmSandboxError as exc:
        raise ProblemError(
            503,
            "abdm_sandbox_rejected",
            "ABDM sandbox URL rejected",
            str(exc),
        ) from exc


def _out(row: PatientExternalId) -> LinkOut:
    _, _, last4 = row.value_enc.partition("|last4:")
    return LinkOut(
        id=row.id,
        patient_id=row.patient_id,
        system=row.system,
        value_last4=last4,
        purpose=row.purpose,
        status=row.status,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        certified=False,
    )


async def _require_patient(session: AsyncSession, patient_id: uuid.UUID) -> None:
    patient = await PatientRepository(session).get(patient_id)
    if patient is None or patient.deleted_at is not None:
        raise ProblemError(404, "patient_not_found", "Not found", "No such patient.")


@router.get("/status")
async def abdm_status(services: ServicesDep) -> StatusOut:
    _require_feature(services)
    client = _client(services)
    detail = "unconfigured"
    if client.configured:
        try:
            health = await client.get_health()
            detail = str(health.get("mode") or health.get("status") or "configured")
        except Exception:  # noqa: BLE001
            detail = "configured_unreachable"
    return StatusOut(
        certified=False,
        sandbox_configured=client.configured,
        status=detail,
    )


@router.get("/stub/equality")
async def abdm_stub_equality(services: ServicesDep) -> dict[str, object]:
    """Proxy the stub equality index; always certified=false."""
    _require_feature(services)
    client = _client(services)
    try:
        payload = await client.equality_index()
    except Exception as exc:  # noqa: BLE001
        raise ProblemError(
            502,
            "abdm_stub_unreachable",
            "ABDM stub unreachable",
            str(exc),
        ) from exc
    payload["certified"] = False
    return payload


@router.put("/patients/{patient_id}/link")
async def link_patient(
    patient_id: uuid.UUID,
    body: LinkRequest,
    request: Request,
    context: AdminAccess,
    session: SessionDep,
    services: ServicesDep,
) -> LinkOut:
    _require_feature(services)
    await _require_patient(session, patient_id)
    row = await _client(services).link(
        session,
        patient_id=patient_id,
        system=body.system,
        value=body.value,
        created_by=context.subject,
    )
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="abdm.patient_linked",
        resource_type="patient_external_id",
        resource_id=str(row.id),
        patient_id=patient_id,
        trace_id=getattr(request.state, "trace_id", None),
        metadata={"system": row.system, "certified": False},
    )
    await session.commit()
    return _out(row)


@router.get("/patients/{patient_id}/links")
async def list_patient_links(
    patient_id: uuid.UUID,
    context: AdminAccess,
    session: SessionDep,
    services: ServicesDep,
) -> list[LinkOut]:
    _require_feature(services)
    await _require_patient(session, patient_id)
    result = await session.execute(
        select(PatientExternalId)
        .where(PatientExternalId.patient_id == patient_id)
        .order_by(PatientExternalId.created_at.desc())
    )
    return [_out(row) for row in result.scalars()]


@router.delete(
    "/patients/{patient_id}/links/{system}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unlink_patient(
    patient_id: uuid.UUID,
    system: str,
    request: Request,
    context: AdminAccess,
    session: SessionDep,
    services: ServicesDep,
) -> Response:
    _require_feature(services)
    result = await session.execute(
        select(PatientExternalId).where(
            PatientExternalId.patient_id == patient_id,
            PatientExternalId.system == system,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ProblemError(404, "abdm_link_not_found", "Not found", "No such patient link.")
    row.status = "unlinked"
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="abdm.patient_unlinked",
        resource_type="patient_external_id",
        resource_id=str(row.id),
        patient_id=patient_id,
        trace_id=getattr(request.state, "trace_id", None),
        metadata={"system": row.system, "certified": False},
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
