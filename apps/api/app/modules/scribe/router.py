from __future__ import annotations

import math
import uuid
from typing import Annotated, Any, Literal

from app.core.db import get_session
from app.core.pagination import GridMeta
from app.core.security import AuthContext, Role, get_auth_context, require_roles
from app.core.services import Services, get_services
from app.modules.scribe.schemas import (
    AudioUploadOut,
    AudioUploadRequest,
    CorrectionRequest,
    DraftEditRequest,
    EncounterCreate,
    EncounterOut,
    NoteOut,
    NoteVersionOut,
    RejectRequest,
    ScribeRunCreate,
    ScribeRunOut,
    SignatureOut,
    SignRequest,
    SourceOut,
    StockReservationOut,
    StockReservationRequest,
    TranscriptCreate,
    TranscriptOut,
)
from app.modules.scribe.service import ScribeService
from app.repositories.audit import AuditRepository
from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import Response
from sahyog_common.errors import ProblemError
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/scribe", tags=["scribe"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ContextDep = Annotated[AuthContext, Depends(get_auth_context)]
ServicesDep = Annotated[Services, Depends(get_services)]
DoctorDep = Annotated[AuthContext, Depends(require_roles(Role.DOCTOR))]


def _trace(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _scribe(services: Services, session: AsyncSession) -> ScribeService:
    return ScribeService(services, session)


def _require_feature(services: Services) -> None:
    if not services.features.enabled("all_role_assistants"):
        raise ProblemError(
            403,
            "feature_disabled",
            "Scribe unavailable",
            "The doctor scribe console is disabled by configuration.",
        )


@router.get("/preconsult")
async def preconsult_brief(
    request: Request,
    context: DoctorDep,
    services: ServicesDep,
    session: SessionDep,
    appointment_id: Annotated[uuid.UUID | None, Query()] = None,
    patient_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict[str, Any]:
    """Pre-consult brief from real appointments, meds, documents, and signed notes."""
    _require_feature(services)
    from app.core.security import doctor_schedule_name
    from app.modules.scribe.preconsult import build_preconsult_brief

    brief = await build_preconsult_brief(
        session,
        appointment_id=appointment_id,
        patient_id=patient_id,
        doctor_name=doctor_schedule_name(context),
        locale=context.locale,
        specialty_label_fn=services.specialty_label,
    )
    if brief.get("status") == "not_found":
        raise ProblemError(404, "appointment_not_found", "Not found", "No such appointment.")
    if brief.get("status") == "no_patient":
        raise ProblemError(
            422,
            "patient_required",
            "Patient required",
            "Select an appointment or patient for the pre-consult brief.",
        )
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="scribe.preconsult_viewed",
        resource_type="appointment" if appointment_id else "patient",
        resource_id=str(appointment_id or patient_id),
        patient_id=uuid.UUID(brief["patient_id"]) if brief.get("patient_id") else None,
        consent_id=context.consent_id,
        trace_id=_trace(request),
        metadata={"status": brief.get("status")},
    )
    await session.commit()
    return brief


@router.get("/encounters")
async def list_encounters(
    context: DoctorDep,
    services: ServicesDep,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=120)] = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=20)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort: Annotated[
        Literal["started_at", "patient_name", "doctor_name", "status", "clinic_code"], Query()
    ] = "started_at",
    order: Annotated[Literal["asc", "desc"], Query()] = "desc",
) -> dict[str, object]:
    _require_feature(services)
    items, total = await _scribe(services, session).list_encounters(
        context,
        query=q,
        status=status_filter,
        sort=sort,
        descending=order == "desc",
        page=page,
        page_size=page_size,
    )
    return {
        "items": items,
        "meta": GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort=sort,
            order=order,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    }


@router.post("/encounters", status_code=status.HTTP_201_CREATED)
async def start_encounter(
    body: EncounterCreate,
    request: Request,
    context: DoctorDep,
    services: ServicesDep,
    session: SessionDep,
) -> EncounterOut:
    _require_feature(services)
    result = await _scribe(services, session).start_encounter(context, body, _trace(request))
    await session.commit()
    return result


@router.get("/encounters/{encounter_id}")
async def get_encounter(
    encounter_id: uuid.UUID,
    context: DoctorDep,
    services: ServicesDep,
    session: SessionDep,
) -> EncounterOut:
    _require_feature(services)
    return await _scribe(services, session).get_encounter(context, encounter_id)


@router.post("/encounters/{encounter_id}/close")
async def close_encounter(
    encounter_id: uuid.UUID,
    request: Request,
    context: DoctorDep,
    services: ServicesDep,
    session: SessionDep,
) -> EncounterOut:
    _require_feature(services)
    result = await _scribe(services, session).close_encounter(
        context, encounter_id, _trace(request)
    )
    await session.commit()
    return result


@router.post("/encounters/{encounter_id}/transcripts", status_code=status.HTTP_201_CREATED)
async def upload_transcript(
    encounter_id: uuid.UUID,
    body: TranscriptCreate,
    request: Request,
    context: DoctorDep,
    services: ServicesDep,
    session: SessionDep,
) -> TranscriptOut:
    _require_feature(services)
    result = await _scribe(services, session).upload_transcript(
        context, encounter_id, body, _trace(request)
    )
    await session.commit()
    return result


@router.get("/encounters/{encounter_id}/transcript")
async def get_transcript(
    encounter_id: uuid.UUID,
    context: DoctorDep,
    services: ServicesDep,
    session: SessionDep,
) -> TranscriptOut:
    _require_feature(services)
    return await _scribe(services, session).get_transcript(context, encounter_id)


@router.post("/encounters/{encounter_id}/audio", status_code=status.HTTP_201_CREATED)
async def start_audio_upload(
    encounter_id: uuid.UUID,
    body: AudioUploadRequest,
    request: Request,
    context: DoctorDep,
    services: ServicesDep,
    session: SessionDep,
) -> AudioUploadOut:
    _require_feature(services)
    result = await _scribe(services, session).start_audio_upload(
        context, encounter_id, body, _trace(request)
    )
    await session.commit()
    return result


@router.post("/encounters/{encounter_id}/audio/{transcript_id}/complete")
async def complete_audio_upload(
    encounter_id: uuid.UUID,
    transcript_id: uuid.UUID,
    request: Request,
    context: DoctorDep,
    services: ServicesDep,
    session: SessionDep,
) -> TranscriptOut:
    _require_feature(services)
    result = await _scribe(services, session).complete_audio_upload(
        context, encounter_id, transcript_id, _trace(request)
    )
    await session.commit()
    return result


@router.post("/encounters/{encounter_id}/runs")
async def start_run(
    encounter_id: uuid.UUID,
    body: ScribeRunCreate,
    request: Request,
    context: DoctorDep,
    services: ServicesDep,
    session: SessionDep,
) -> ScribeRunOut:
    _require_feature(services)
    result = await _scribe(services, session).start_run(
        context, encounter_id, body.transcript_id, _trace(request)
    )
    await session.commit()
    return result


@router.get("/runs/{run_id}")
async def get_run(
    run_id: uuid.UUID,
    context: DoctorDep,
    services: ServicesDep,
    session: SessionDep,
) -> ScribeRunOut:
    _require_feature(services)
    return await _scribe(services, session).get_run(context, run_id)


@router.post("/runs/{run_id}/acknowledge")
async def acknowledge_red_flags(
    run_id: uuid.UUID,
    request: Request,
    context: DoctorDep,
    services: ServicesDep,
    session: SessionDep,
) -> ScribeRunOut:
    _require_feature(services)
    result = await _scribe(services, session).acknowledge_red_flags(
        context, run_id, _trace(request)
    )
    await session.commit()
    return result


@router.patch("/runs/{run_id}/draft")
async def edit_draft(
    run_id: uuid.UUID,
    body: DraftEditRequest,
    request: Request,
    context: DoctorDep,
    services: ServicesDep,
    session: SessionDep,
) -> ScribeRunOut:
    _require_feature(services)
    result = await _scribe(services, session).edit_draft(context, run_id, body, _trace(request))
    await session.commit()
    return result


@router.post("/runs/{run_id}/reject")
async def reject_run(
    run_id: uuid.UUID,
    body: RejectRequest,
    request: Request,
    context: DoctorDep,
    services: ServicesDep,
    session: SessionDep,
) -> ScribeRunOut:
    _require_feature(services)
    result = await _scribe(services, session).reject_run(context, run_id, body, _trace(request))
    await session.commit()
    return result


@router.post("/runs/{run_id}/sign")
async def sign_run(
    run_id: uuid.UUID,
    body: SignRequest,
    request: Request,
    context: DoctorDep,
    services: ServicesDep,
    session: SessionDep,
) -> SignatureOut:
    _require_feature(services)
    result = await _scribe(services, session).sign_run(
        context,
        run_id,
        body,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        trace_id=_trace(request),
    )
    await session.commit()
    return result


@router.get("/notes")
async def list_notes(
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=120)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, object]:
    _require_feature(services)
    items, total = await _scribe(services, session).list_notes(
        context, query=q, page=page, page_size=page_size
    )
    return {
        "items": items,
        "meta": GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort="signed_at",
            order="desc",
            pages=math.ceil(total / page_size) if total else 0,
        ),
    }


@router.get("/notes/{note_id}")
async def get_note(
    note_id: uuid.UUID,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> NoteOut:
    _require_feature(services)
    service = _scribe(services, session)
    result = await service.get_note(context, note_id)
    if context.primary_role is not Role.ADMIN and context.primary_role is not Role.COMPLIANCE:
        AuditRepository(session).append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="note.viewed",
            resource_type="clinical_note",
            resource_id=str(note_id),
            patient_id=result.patient_id,
            consent_id=context.consent_id,
            trace_id=_trace(request),
        )
        await session.commit()
    return result


@router.get("/notes/{note_id}/versions")
async def note_versions(
    note_id: uuid.UUID,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> list[NoteVersionOut]:
    _require_feature(services)
    service = _scribe(services, session)
    note, _, metadata_only = await service.note_visible(context, note_id)
    if metadata_only:
        raise ProblemError(
            403, "forbidden", "Access denied", "Version content is not visible to this role."
        )
    versions = await service.note_versions(context, note_id)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="note.versions_viewed",
        resource_type="clinical_note",
        resource_id=str(note_id),
        patient_id=note.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
    )
    await session.commit()
    return versions


@router.post("/notes/{note_id}/corrections")
async def correct_note(
    note_id: uuid.UUID,
    body: CorrectionRequest,
    request: Request,
    context: DoctorDep,
    services: ServicesDep,
    session: SessionDep,
) -> NoteOut:
    _require_feature(services)
    result = await _scribe(services, session).correct_note(context, note_id, body, _trace(request))
    await session.commit()
    return result


@router.get("/notes/{note_id}/sources")
async def note_sources(
    note_id: uuid.UUID,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> list[SourceOut]:
    _require_feature(services)
    service = _scribe(services, session)
    note, _, _ = await service.note_visible(context, note_id)
    rows = await service.note_sources(context, note_id, version)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="note.sources_viewed",
        resource_type="clinical_note",
        resource_id=str(note_id),
        patient_id=note.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
    )
    await session.commit()
    return rows


@router.get("/notes/{note_id}/download")
async def download_note(
    note_id: uuid.UUID,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> Response:
    _require_feature(services)
    service = _scribe(services, session)
    note, _, _ = await service.note_visible(context, note_id)
    document = await service.note_download(context, note_id)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="note.downloaded",
        resource_type="clinical_note",
        resource_id=str(note_id),
        patient_id=note.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
    )
    await session.commit()
    return Response(
        content=document,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="clinical-note-{note_id}.pdf"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/notes/{note_id}/reservations", status_code=status.HTTP_201_CREATED)
async def reserve_stock(
    note_id: uuid.UUID,
    body: StockReservationRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_roles(Role.DOCTOR, Role.PHARMACIST))],
    services: ServicesDep,
    session: SessionDep,
) -> StockReservationOut:
    _require_feature(services)
    result = await _scribe(services, session).reserve_stock(context, note_id, body, _trace(request))
    await session.commit()
    return result


@router.get("/stock")
async def stock_lookup(
    context: Annotated[
        AuthContext, Depends(require_roles(Role.DOCTOR, Role.PHARMACIST, Role.FRONT_DESK))
    ],
    services: ServicesDep,
    session: SessionDep,
    drug_name: Annotated[str, Query(min_length=2, max_length=120)],
    clinic: Annotated[str, Query(min_length=2, max_length=40)],
) -> dict[str, Any]:
    _require_feature(services)
    if context.primary_role is not Role.ADMIN and clinic not in context.clinic_ids:
        raise ProblemError(403, "forbidden", "Access denied", "Clinic is outside your scope.")
    return await _scribe(services, session).stock_lookup(
        context, drug_name=drug_name, clinic_code=clinic
    )
