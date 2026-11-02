from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sahyog_common.errors import ProblemError

from app.core.db import get_session
from app.core.ports import FhirError
from app.core.security import AuthContext, Role, require_roles
from app.core.services import Services, get_services
from app.integrations.fhir import local_document_as_reference
from app.modules.fhir.schemas import (
    FhirDocumentReferencesOut,
    FhirEncountersOut,
    FhirLinkIn,
    FhirLinkOut,
    FhirPatientOut,
)
from app.repositories.audit import AuditRepository
from app.repositories.fhir import FhirLinkRepository
from app.repositories.patients import PatientRepository
from app.repositories.records import DocumentRepository

router = APIRouter(prefix="/api/v1/fhir", tags=["fhir"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ServicesDep = Annotated[Services, Depends(get_services)]
ClinicianAccess = Annotated[
    AuthContext,
    Depends(require_roles(Role.DOCTOR, Role.FRONT_DESK, Role.ADMIN, Role.COMPLIANCE)),
]
AdminAccess = Annotated[AuthContext, Depends(require_roles(Role.ADMIN))]


def _require_fhir(services: Services) -> None:
    if not services.features.enabled("fhir_read"):
        raise ProblemError(
            409,
            "fhir_disabled",
            "FHIR read is disabled",
            "Enable the fhir_read feature flag to use the read-only FHIR adapter.",
        )
    if services.fhir is None or not services.fhir.configured():
        raise ProblemError(
            503,
            "fhir_unconfigured",
            "FHIR is not configured",
            "Set FHIR_BASE_URL (and OAuth credentials when required).",
        )


def _link_out(row) -> FhirLinkOut:  # type: ignore[no-untyped-def]
    return FhirLinkOut(
        patient_id=row.patient_id,
        fhir_patient_id=row.fhir_patient_id,
        system=row.system,
        updated_at=row.updated_at,
    )


@router.get("/patients/{patient_id}")
async def read_fhir_patient(
    patient_id: uuid.UUID,
    request: Request,
    context: ClinicianAccess,
    session: SessionDep,
    services: ServicesDep,
) -> FhirPatientOut:
    _require_fhir(services)
    patient = await PatientRepository(session).get(patient_id)
    if patient is None or patient.deleted_at is not None:
        raise ProblemError(404, "patient_not_found", "Not found", "No such patient.")
    link = await FhirLinkRepository(session).get(patient_id)
    if link is None:
        raise ProblemError(
            404,
            "fhir_link_missing",
            "No FHIR link",
            "Map this patient to a FHIR Patient id before reading demographics.",
        )
    assert services.fhir is not None
    try:
        demographics = await services.fhir.get_patient(link.fhir_patient_id)
    except FhirError as exc:
        raise ProblemError(
            502 if exc.code != "fhir_not_found" else 404,
            exc.code,
            "FHIR read failed",
            "The FHIR server could not return this patient.",
        ) from exc
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="fhir.patient_read",
        resource_type="patient",
        resource_id=str(patient_id),
        patient_id=patient_id,
        trace_id=getattr(request.state, "trace_id", None),
        metadata={"fhir_patient_id": link.fhir_patient_id},
    )
    await session.commit()
    return FhirPatientOut(
        patient_id=patient_id,
        link=_link_out(link),
        demographics=demographics,
    )


@router.get("/patients/{patient_id}/encounters")
async def list_fhir_encounters(
    patient_id: uuid.UUID,
    request: Request,
    context: ClinicianAccess,
    session: SessionDep,
    services: ServicesDep,
    count: Annotated[int, Query(ge=1, le=50)] = 20,
) -> FhirEncountersOut:
    _require_fhir(services)
    patient = await PatientRepository(session).get(patient_id)
    if patient is None or patient.deleted_at is not None:
        raise ProblemError(404, "patient_not_found", "Not found", "No such patient.")
    link = await FhirLinkRepository(session).get(patient_id)
    if link is None:
        raise ProblemError(
            404,
            "fhir_link_missing",
            "No FHIR link",
            "Map this patient to a FHIR Patient id before reading encounters.",
        )
    assert services.fhir is not None
    try:
        encounters = await services.fhir.list_encounters(link.fhir_patient_id, count=count)
    except FhirError as exc:
        raise ProblemError(
            502 if exc.code != "fhir_not_found" else 404,
            exc.code,
            "FHIR read failed",
            "The FHIR server could not return encounters for this patient.",
        ) from exc
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="fhir.encounters_listed",
        resource_type="patient",
        resource_id=str(patient_id),
        patient_id=patient_id,
        trace_id=getattr(request.state, "trace_id", None),
        metadata={"fhir_patient_id": link.fhir_patient_id, "count": len(encounters)},
    )
    await session.commit()
    return FhirEncountersOut(
        patient_id=patient_id,
        fhir_patient_id=link.fhir_patient_id,
        encounters=encounters,
    )


@router.get("/patients/{patient_id}/document-references")
async def list_patient_records(
    patient_id: uuid.UUID,
    request: Request,
    context: ClinicianAccess,
    session: SessionDep,
    services: ServicesDep,
    count: Annotated[int, Query(ge=1, le=50)] = 20,
) -> FhirDocumentReferencesOut:
    """Local Sahyog documents plus optional FHIR DocumentReference rows.

    Local records are always returned when the patient exists (clinician roles).
    Remote FHIR DocumentReferences require ``fhir_read`` + a patient link; missing
    link/config yields an empty ``fhir_records`` list rather than 404 so the UI can
    still show local charts.
    """
    patient = await PatientRepository(session).get(patient_id)
    if patient is None or patient.deleted_at is not None:
        raise ProblemError(404, "patient_not_found", "Not found", "No such patient.")

    local_docs, _total = await DocumentRepository(session).list_grid(
        patient_id=patient_id,
        query=None,
        status=None,
        kind=None,
        sort="created_at",
        descending=True,
        limit=count,
        offset=0,
    )
    local_records = [local_document_as_reference(doc) for doc in local_docs]

    fhir_records: list[dict] = []
    fhir_patient_id: str | None = None
    link = await FhirLinkRepository(session).get(patient_id)
    if (
        link is not None
        and services.features.enabled("fhir_read")
        and services.fhir is not None
        and services.fhir.configured()
    ):
        fhir_patient_id = link.fhir_patient_id
        try:
            fhir_records = await services.fhir.list_document_references(
                link.fhir_patient_id, count=count
            )
        except FhirError:
            # Keep local records visible; remote bundle failure is non-fatal here.
            fhir_records = []

    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="fhir.document_references_listed",
        resource_type="patient",
        resource_id=str(patient_id),
        patient_id=patient_id,
        trace_id=getattr(request.state, "trace_id", None),
        metadata={
            "fhir_patient_id": fhir_patient_id,
            "local_count": len(local_records),
            "fhir_count": len(fhir_records),
        },
    )
    await session.commit()
    return FhirDocumentReferencesOut(
        patient_id=patient_id,
        fhir_patient_id=fhir_patient_id,
        local_records=local_records,
        fhir_records=fhir_records,
        source="local+fhir" if fhir_patient_id else "local",
    )


@router.put("/patients/{patient_id}/link")
async def upsert_fhir_link(
    patient_id: uuid.UUID,
    body: FhirLinkIn,
    request: Request,
    context: AdminAccess,
    session: SessionDep,
    services: ServicesDep,
) -> FhirLinkOut:
    if not services.features.enabled("fhir_read"):
        raise ProblemError(
            409,
            "fhir_disabled",
            "FHIR read is disabled",
            "Enable the fhir_read feature flag before creating links.",
        )
    patient = await PatientRepository(session).get(patient_id)
    if patient is None or patient.deleted_at is not None:
        raise ProblemError(404, "patient_not_found", "Not found", "No such patient.")
    row = await FhirLinkRepository(session).upsert(
        patient_id=patient_id,
        fhir_patient_id=body.fhir_patient_id.strip(),
        system=body.system.strip() or "fhir",
    )
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="fhir.link_upserted",
        resource_type="patient",
        resource_id=str(patient_id),
        patient_id=patient_id,
        trace_id=getattr(request.state, "trace_id", None),
        metadata={"fhir_patient_id": row.fhir_patient_id, "system": row.system},
    )
    await session.commit()
    return _link_out(row)
