from __future__ import annotations

import datetime as dt
import math
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sahyog_common.errors import ProblemError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.pagination import GridMeta, GridResponse
from app.core.security import AuthContext, Role, get_auth_context
from app.modules.consents.schemas import ConsentCreate, ConsentOut, ContextOut
from app.repositories.audit import AuditRepository
from app.repositories.consents import ConsentRepository
from app.repositories.models import Consent
from app.repositories.patients import PatientRepository

router = APIRouter(prefix="/api/v1", tags=["consents"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ContextDep = Annotated[AuthContext, Depends(get_auth_context)]


def _trace(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _consent_out(consent: Consent, patient_name: str | None) -> ConsentOut:
    return ConsentOut(
        id=consent.id,
        patient_id=consent.patient_id,
        patient_name=patient_name,
        grantor_subject=consent.grantor_subject,
        caregiver_subject=consent.caregiver_subject,
        scopes=list(consent.scopes or []),
        purpose=consent.purpose,
        status=consent.status,
        granted_at=consent.granted_at,
        expires_at=consent.expires_at,
        revoked_at=consent.revoked_at,
    )


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


async def _own_patient(context: AuthContext, session: AsyncSession) -> uuid.UUID:
    if context.patient_id is None or not await PatientRepository(session).exists(
        context.patient_id
    ):
        raise ProblemError(
            409,
            "account_not_linked",
            "Account not linked",
            "This account is not linked to a patient record. Contact the clinic.",
        )
    return context.patient_id


@router.get("/consents")
async def list_consents(
    context: ContextDep,
    session: SessionDep,
    patient_id: Annotated[uuid.UUID | None, Query()] = None,
    consent_status: Annotated[str | None, Query(alias="status", max_length=20)] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort: Annotated[
        Literal["granted_at", "expires_at", "status", "created_at"], Query()
    ] = "granted_at",
    order: Annotated[Literal["asc", "desc"], Query()] = "desc",
) -> GridResponse[ConsentOut]:
    scoped_patient: uuid.UUID | None
    caregiver_subject: str | None
    role = context.primary_role
    if role is Role.PATIENT:
        scoped_patient = await _own_patient(context, session)
        caregiver_subject = None
    elif role is Role.CAREGIVER:
        scoped_patient = None
        caregiver_subject = context.subject
    elif role in {Role.ADMIN, Role.COMPLIANCE}:
        scoped_patient = patient_id
        caregiver_subject = None
    else:
        raise ProblemError(
            403, "forbidden", "Access denied", "Your role cannot view consent records."
        )
    rows, total = await ConsentRepository(session).list_grid(
        patient_id=scoped_patient,
        caregiver_subject=caregiver_subject,
        status=consent_status,
        query=q,
        sort=sort,
        descending=order == "desc",
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return GridResponse[ConsentOut](
        items=[_consent_out(row, name) for row, name in rows],
        meta=GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort=sort,
            order=order,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    )


@router.post("/consents", status_code=status.HTTP_201_CREATED)
async def grant_consent(
    request: Request,
    body: ConsentCreate,
    context: ContextDep,
    session: SessionDep,
) -> ConsentOut:
    role = context.primary_role
    if role is Role.PATIENT:
        patient_id = await _own_patient(context, session)
        if body.patient_id is not None and body.patient_id != patient_id:
            raise ProblemError(
                403, "forbidden", "Access denied", "You can only share your own record."
            )
    elif role is Role.ADMIN:
        if body.patient_id is None:
            raise ProblemError(
                400, "patient_required", "Patient required", "Select a patient for this consent."
            )
        patient_id = body.patient_id
        if not await PatientRepository(session).exists(patient_id):
            raise ProblemError(404, "patient_not_found", "Not found", "No such patient.")
    else:
        raise ProblemError(
            403, "forbidden", "Access denied", "Only a patient or administrator can grant consent."
        )
    if body.caregiver_subject == context.subject:
        raise ProblemError(
            400,
            "self_consent",
            "Invalid caregiver",
            "You cannot grant consent to your own account.",
        )
    expires_at = _aware(body.expires_at)
    now = dt.datetime.now(dt.UTC)
    if expires_at is not None and expires_at <= now:
        raise ProblemError(
            422, "invalid_expiry", "Invalid expiry", "Choose an expiry date in the future."
        )
    repo = ConsentRepository(session)
    existing = await repo.active_for_pair(
        patient_id=patient_id, caregiver_subject=body.caregiver_subject
    )
    if existing is not None:
        raise ProblemError(
            409,
            "consent_exists",
            "Consent already active",
            "An active consent already exists for this caregiver. Revoke it before granting again.",
        )
    consent = Consent(
        patient_id=patient_id,
        grantor_subject=context.subject,
        caregiver_subject=body.caregiver_subject,
        scopes=list(body.scopes),
        purpose=body.purpose,
        status="active",
        granted_at=now,
        expires_at=expires_at,
    )
    await repo.create(consent)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="consent.granted",
        resource_type="consent",
        resource_id=str(consent.id),
        patient_id=patient_id,
        trace_id=_trace(request),
        metadata={
            "caregiver_subject": body.caregiver_subject,
            "scopes": list(body.scopes),
            "purpose": body.purpose,
            "expires_at": expires_at.isoformat() if expires_at else None,
        },
    )
    await session.commit()
    patient = await PatientRepository(session).get(patient_id)
    return _consent_out(consent, patient.display_name if patient else None)


@router.post("/consents/{consent_id}/revoke")
async def revoke_consent(
    consent_id: uuid.UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> ConsentOut:
    consent = await ConsentRepository(session).get(consent_id)
    if consent is None:
        raise ProblemError(404, "consent_not_found", "Not found", "No such consent.")
    role = context.primary_role
    if role is Role.PATIENT:
        own = await _own_patient(context, session)
        if consent.patient_id != own:
            raise ProblemError(404, "consent_not_found", "Not found", "No such consent.")
    elif role not in {Role.ADMIN, Role.COMPLIANCE}:
        raise ProblemError(
            403, "forbidden", "Access denied", "Your role cannot revoke this consent."
        )
    if consent.status == "active":
        await ConsentRepository(session).revoke(consent)
        AuditRepository(session).append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="consent.revoked",
            resource_type="consent",
            resource_id=str(consent.id),
            patient_id=consent.patient_id,
            trace_id=_trace(request),
            metadata={
                "caregiver_subject": consent.caregiver_subject,
                "scopes": list(consent.scopes or []),
            },
        )
        await session.commit()
    patient = await PatientRepository(session).get(consent.patient_id)
    return _consent_out(consent, patient.display_name if patient else None)


@router.get("/me/contexts")
async def list_contexts(
    context: ContextDep,
    session: SessionDep,
) -> list[ContextOut]:
    if context.primary_role is not Role.CAREGIVER:
        raise ProblemError(
            403, "forbidden", "Access denied", "Caregiver context is only available to caregivers."
        )
    rows = await ConsentRepository(session).active_contexts(caregiver_subject=context.subject)
    return [
        ContextOut(
            consent_id=consent.id,
            patient_id=consent.patient_id,
            patient_name=name,
            scopes=list(consent.scopes or []),
            expires_at=consent.expires_at,
        )
        for consent, name in rows
    ]


@router.post("/me/contexts/{consent_id}/activate")
async def activate_context(
    consent_id: uuid.UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> ContextOut:
    if context.primary_role is not Role.CAREGIVER:
        raise ProblemError(
            403, "forbidden", "Access denied", "Caregiver context is only available to caregivers."
        )
    consent = await ConsentRepository(session).active_for_subject(
        consent_id=consent_id, caregiver_subject=context.subject
    )
    if consent is None:
        raise ProblemError(
            403,
            "consent_required",
            "Consent required",
            "No active consent matches this context. Ask the patient to share their record.",
        )
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="consent.context_activated",
        resource_type="consent",
        resource_id=str(consent.id),
        patient_id=consent.patient_id,
        trace_id=_trace(request),
        metadata={"scopes": list(consent.scopes or [])},
    )
    await session.commit()
    patient = await PatientRepository(session).get(consent.patient_id)
    return ContextOut(
        consent_id=consent.id,
        patient_id=consent.patient_id,
        patient_name=patient.display_name if patient else None,
        scopes=list(consent.scopes or []),
        expires_at=consent.expires_at,
    )


@router.delete("/me/context", status_code=status.HTTP_204_NO_CONTENT)
async def clear_context(
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> Response:
    if context.primary_role is not Role.CAREGIVER:
        raise ProblemError(
            403, "forbidden", "Access denied", "Caregiver context is only available to caregivers."
        )
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="consent.context_cleared",
        resource_type="consent",
        resource_id=str(context.consent_id) if context.consent_id else None,
        patient_id=context.patient_id,
        trace_id=_trace(request),
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
