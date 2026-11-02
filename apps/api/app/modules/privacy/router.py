from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Annotated, Any

from app.core.db import get_session
from app.core.security import AuthContext, Role, get_auth_context
from app.core.services import Services, get_services
from app.repositories.audit import AuditRepository
from app.repositories.models import (
    Appointment,
    AuditEvent,
    ChatMessage,
    ChatSession,
    ClinicalNote,
    Consent,
    ContactChannel,
    DataDeletionRequest,
    Document,
    Encounter,
    Medication,
    Notification,
    Patient,
)
from app.repositories.patients import PatientRepository
from app.repositories.privacy import DataDeletionRequestRepository
from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sahyog_common.errors import ProblemError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/me", tags=["privacy"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ContextDep = Annotated[AuthContext, Depends(get_auth_context)]
ServicesDep = Annotated[Services, Depends(get_services)]

EXPORT_LIMIT = 5000


class DeletionRequestCreate(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class DeletionRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    reason: str | None
    requested_at: dt.datetime
    scheduled_for: dt.datetime
    completed_at: dt.datetime | None


def _trace(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


async def _linked_patient(
    context: AuthContext, session: AsyncSession, *, allow_deleted: bool = False
) -> Patient:
    if context.primary_role is not Role.PATIENT:
        raise ProblemError(
            403,
            "forbidden",
            "Access denied",
            "This endpoint is available only to a patient account.",
        )
    if context.patient_id is None:
        raise ProblemError(
            409,
            "account_not_linked",
            "Account not linked",
            "This account is not linked to a patient record. Contact the clinic.",
        )
    patient = await PatientRepository(session).get(context.patient_id)
    if patient is None or (patient.deleted_at is not None and not allow_deleted):
        raise ProblemError(
            403,
            "account_deleted",
            "Account deletion requested",
            "This record is pending deletion and cannot be used for this request.",
        )
    return patient


async def _rows(session: AsyncSession, model: Any, patient_id: uuid.UUID) -> list[Any]:
    rows = await session.scalars(
        select(model)
        .where(model.patient_id == patient_id)
        .order_by(model.created_at.desc())
        .limit(EXPORT_LIMIT)
    )
    return list(rows)


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None


async def _export_payload(session: AsyncSession, patient: Patient) -> dict[str, Any]:
    appointments = await _rows(session, Appointment, patient.id)
    medications = await _rows(session, Medication, patient.id)
    documents = await _rows(session, Document, patient.id)
    encounters = await _rows(session, Encounter, patient.id)
    notes = await _rows(session, ClinicalNote, patient.id)
    consents = await _rows(session, Consent, patient.id)
    notifications = await _rows(session, Notification, patient.id)
    channels = await _rows(session, ContactChannel, patient.id)
    sessions = await _rows(session, ChatSession, patient.id)
    message_counts = dict(
        (
            await session.execute(
                select(ChatMessage.session_id, func.count())
                .join(ChatSession, ChatSession.id == ChatMessage.session_id)
                .where(ChatSession.patient_id == patient.id)
                .group_by(ChatMessage.session_id)
            )
        ).all()
    )
    audit_count, audit_first, audit_last = (
        await session.execute(
            select(
                func.count(),
                func.min(AuditEvent.created_at),
                func.max(AuditEvent.created_at),
            ).where(AuditEvent.patient_id == patient.id)
        )
    ).one()

    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "patient": {
            "id": str(patient.id),
            "display_name": patient.display_name,
            "locale": patient.locale,
            "created_at": _iso(patient.created_at),
            "deleted_at": _iso(patient.deleted_at),
        },
        "appointments": [
            {
                "id": str(row.id),
                "clinic_code": row.clinic_code,
                "doctor_name": row.doctor_name,
                "specialty_code": row.specialty_code,
                "starts_at": _iso(row.starts_at),
                "duration_minutes": row.duration_minutes,
                "status": row.status,
                "created_at": _iso(row.created_at),
            }
            for row in appointments
        ],
        "medications": [
            {
                "id": str(row.id),
                "name": row.name,
                "dose": row.dose,
                "frequency": row.frequency,
                "status": row.status,
                "created_at": _iso(row.created_at),
            }
            for row in medications
        ],
        "documents": [
            {
                "id": str(row.id),
                "kind": row.kind,
                "title": row.title,
                "content_type": row.content_type,
                "size_bytes": row.size_bytes,
                "language": row.language,
                "status": row.status,
                "page_count": row.page_count,
                "created_at": _iso(row.created_at),
            }
            for row in documents
        ],
        "encounters": [
            {
                "id": str(row.id),
                "doctor_name": row.doctor_name,
                "clinic_code": row.clinic_code,
                "kind": row.kind,
                "status": row.status,
                "started_at": _iso(row.started_at),
                "ended_at": _iso(row.ended_at),
                "created_at": _iso(row.created_at),
            }
            for row in encounters
        ],
        "clinical_notes": [
            {
                "id": str(row.id),
                "title": row.title,
                "language": row.language,
                "status": row.status,
                "signed_at": _iso(row.signed_at),
                "created_at": _iso(row.created_at),
            }
            for row in notes
        ],
        "consents": [
            {
                "id": str(row.id),
                "caregiver_subject": row.caregiver_subject,
                "scopes": list(row.scopes or []),
                "purpose": row.purpose,
                "status": row.status,
                "granted_at": _iso(row.granted_at),
                "expires_at": _iso(row.expires_at),
                "revoked_at": _iso(row.revoked_at),
            }
            for row in consents
        ],
        "notifications": [
            {
                "id": str(row.id),
                "recipient_role": row.recipient_role,
                "template_id": row.template_id,
                "channel": row.channel,
                "status": row.status,
                "title": row.title,
                "read_at": _iso(row.read_at),
                "created_at": _iso(row.created_at),
            }
            for row in notifications
        ],
        "contact_channels": [
            {
                "channel": row.channel,
                "address": row.address,
                "verified": row.verified,
                "opt_in": row.opt_in,
                "created_at": _iso(row.created_at),
            }
            for row in channels
        ],
        "chat_sessions": [
            {
                "id": str(row.id),
                "title": row.title,
                "status": row.status,
                "locale": row.locale,
                "message_count": int(message_counts.get(row.id, 0)),
                "created_at": _iso(row.created_at),
                "updated_at": _iso(row.updated_at),
            }
            for row in sessions
        ],
        "audit_summary": {
            "event_count": int(audit_count or 0),
            "first_event_at": _iso(audit_first),
            "last_event_at": _iso(audit_last),
        },
        "scope": {
            "format": "metadata_only",
            "excludes": [
                "document bytes",
                "document chunk text and vectors",
                "clinical note content",
                "transcript and chat message content",
                "audit event detail",
            ],
            "limit_per_collection": EXPORT_LIMIT,
        },
    }


@router.get("/export")
async def export_my_record(
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> Response:
    patient = await _linked_patient(context, session, allow_deleted=True)
    payload = await _export_payload(session, patient)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="privacy.export_downloaded",
        resource_type="patient_record",
        resource_id=str(patient.id),
        patient_id=patient.id,
        trace_id=_trace(request),
        metadata={"format": "metadata_json", "limit_per_collection": EXPORT_LIMIT},
    )
    await session.commit()
    filename = f"sahyog-record-{patient.id}.json"
    return Response(
        content=json.dumps(payload, ensure_ascii=False, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/deletion-request")
async def get_deletion_request(
    context: ContextDep,
    session: SessionDep,
) -> dict[str, Any]:
    patient = await _linked_patient(context, session, allow_deleted=True)
    row = await DataDeletionRequestRepository(session).latest_open(patient.id)
    return {"request": DeletionRequestOut.model_validate(row) if row else None}


@router.post("/deletion-request", status_code=status.HTTP_201_CREATED)
async def request_deletion(
    request: Request,
    body: DeletionRequestCreate,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> DeletionRequestOut:
    patient = await _linked_patient(context, session, allow_deleted=True)
    repo = DataDeletionRequestRepository(session)
    if await repo.latest_open(patient.id) is not None:
        raise ProblemError(
            409,
            "deletion_request_exists",
            "Request already open",
            "A deletion request is already pending for this record.",
        )
    now = dt.datetime.now(dt.UTC)
    grace_days = int(services.app_config.get("retention", {}).get("deletion_grace_days", 30))
    deletion = DataDeletionRequest(
        patient_id=patient.id,
        requested_by_subject=context.subject,
        status="pending",
        reason=body.reason,
        requested_at=now,
        scheduled_for=now + dt.timedelta(days=grace_days),
        evidence={"grace_days": grace_days, "requested_via": "patient_portal"},
    )
    await repo.create(deletion)
    patient.deleted_at = now
    revoked = await session.execute(
        update(Consent)
        .where(Consent.patient_id == patient.id, Consent.status == "active")
        .values(status="revoked", revoked_at=now)
    )
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="privacy.deletion_requested",
        resource_type="data_deletion_request",
        resource_id=str(deletion.id),
        patient_id=patient.id,
        trace_id=_trace(request),
        metadata={
            "grace_days": grace_days,
            "scheduled_for": deletion.scheduled_for.isoformat(),
            "consents_revoked": int(revoked.rowcount or 0),
        },
    )
    await session.commit()
    return DeletionRequestOut.model_validate(deletion)


@router.delete("/deletion-request", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_deletion(
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> Response:
    patient = await _linked_patient(context, session, allow_deleted=True)
    row = await DataDeletionRequestRepository(session).latest_open(patient.id)
    if row is None:
        raise ProblemError(
            404, "deletion_request_not_found", "Not found", "There is no open deletion request."
        )
    row.status = "cancelled"
    patient.deleted_at = None
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="privacy.deletion_cancelled",
        resource_type="data_deletion_request",
        resource_id=str(row.id),
        patient_id=patient.id,
        trace_id=_trace(request),
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
