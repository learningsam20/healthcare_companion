"""Pre-consult brief assembled from real appointment, meds, documents, notes."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import (
    Appointment,
    ClinicalNote,
    ClinicalNoteVersion,
    Document,
    Medication,
)
from app.repositories.scheduling import AppointmentRepository


async def build_preconsult_brief(
    session: AsyncSession,
    *,
    appointment_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    doctor_name: str | None = None,
    locale: str = "en-IN",
    specialty_label_fn: Any | None = None,
) -> dict[str, Any]:
    appointment: Appointment | None = None
    if appointment_id is not None:
        appointment = await AppointmentRepository(session).get(appointment_id)
        if appointment is None:
            return {"status": "not_found", "reason": "appointment_not_found"}
        patient_id = appointment.patient_id
    if patient_id is None:
        return {"status": "no_patient", "reason": "patient_required"}

    meds = list(
        await session.scalars(
            select(Medication)
            .where(Medication.patient_id == patient_id, Medication.status == "active")
            .order_by(Medication.created_at.desc())
            .limit(20)
        )
    )
    docs = list(
        await session.scalars(
            select(Document)
            .where(
                Document.patient_id == patient_id,
                Document.status.in_(("indexed", "quarantined")),
            )
            .order_by(Document.created_at.desc())
            .limit(12)
        )
    )
    notes = list(
        await session.scalars(
            select(ClinicalNote)
            .where(
                ClinicalNote.patient_id == patient_id,
                ClinicalNote.status.in_(("signed", "amended")),
            )
            .order_by(ClinicalNote.signed_at.desc().nullslast())
            .limit(3)
        )
    )
    last_note_summary: dict[str, Any] | None = None
    if notes:
        note = notes[0]
        version = await session.scalar(
            select(ClinicalNoteVersion)
            .where(
                ClinicalNoteVersion.note_id == note.id,
                ClinicalNoteVersion.version == note.current_version,
            )
            .limit(1)
        )
        content = version.content if version else {}
        last_note_summary = {
            "note_id": str(note.id),
            "signed_at": note.signed_at.isoformat() if note.signed_at else None,
            "title": note.title,
            "assessment": (content.get("assessment") or [])[:4],
            "plan": (content.get("plan") or [])[:4],
            "follow_up": content.get("follow_up"),
            "content_hash": note.signed_hash,
        }

    upcoming = list(
        await session.scalars(
            select(Appointment)
            .where(
                Appointment.patient_id == patient_id,
                Appointment.status.in_(("held", "confirmed")),
                Appointment.starts_at >= dt.datetime.now(dt.UTC) - dt.timedelta(hours=1),
            )
            .order_by(Appointment.starts_at.asc())
            .limit(5)
        )
    )

    specialty_label = None
    if appointment is not None and specialty_label_fn is not None:
        specialty_label = specialty_label_fn(appointment.specialty_code, locale)

    return {
        "status": "ok",
        "as_of": dt.datetime.now(dt.UTC).isoformat(),
        "patient_id": str(patient_id),
        "appointment": (
            {
                "id": str(appointment.id),
                "starts_at": appointment.starts_at.isoformat(),
                "doctor_name": appointment.doctor_name,
                "clinic_code": appointment.clinic_code,
                "specialty_code": appointment.specialty_code,
                "specialty_label": specialty_label,
                "status": appointment.status,
                "no_show_risk": appointment.no_show_risk,
                "no_show_band": appointment.no_show_band,
                "waitlist_suggested": appointment.waitlist_suggested,
            }
            if appointment
            else None
        ),
        "active_medications": [
            {
                "id": str(med.id),
                "name": med.name,
                "dose": med.dose,
                "frequency": med.frequency,
                "status": med.status,
            }
            for med in meds
        ],
        "documents": [
            {
                "id": str(doc.id),
                "title": doc.title,
                "kind": doc.kind,
                "status": doc.status,
                "language": doc.language,
                "created_at": doc.created_at.isoformat(),
                "citation": f"doc:{doc.id}",
                "quarantined": doc.status == "quarantined",
            }
            for doc in docs
        ],
        "last_signed_note": last_note_summary,
        "upcoming_appointments": [
            {
                "id": str(row.id),
                "starts_at": row.starts_at.isoformat(),
                "doctor_name": row.doctor_name,
                "status": row.status,
                "no_show_band": row.no_show_band,
            }
            for row in upcoming
            if doctor_name is None or row.doctor_name == doctor_name
        ],
        "stock_flags": [],  # filled by caller when clinic + meds known
        "provenance": {
            "sources": ["appointments", "medications", "documents", "clinical_notes"],
            "synthetic": False,
        },
    }
