#!/usr/bin/env python3
"""Idempotent synthetic demo data for local and acceptance environments.

Creates patients, consent, medicines, appointments, in-app notifications, chat history,
a W3 encounter/transcript and one preference memory. It never creates signed notes and
never writes real data. IDs are fixed so re-running updates rather than duplicates.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import sys
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT / "packages" / "py-common"))

from app.core.config import get_settings  # noqa: E402
from app.repositories.audit import AuditRepository  # noqa: E402
from app.repositories.models import (  # noqa: E402
    Appointment,
    ChatMessage,
    ChatSession,
    ClinicalNote,
    Consent,
    ContactChannel,
    Document,
    Encounter,
    FhirPatientLink,
    Handoff,
    Medication,
    MemoryPreference,
    Notification,
    Patient,
    ReviewTask,
    Transcript,
    TranscriptTurn,
)
from demo_contacts import enrich_demo_patients, planned_contacts  # noqa: E402
from demo_fixtures import (  # noqa: E402
    PATIENT_ARJUN,
    PATIENT_FATIMA,
    PATIENT_PRIYA,
    PATIENT_ROHAN,
    USER_CAREGIVER_MEENA,
    USER_DOCTOR_RAO,
    USER_FRONTDESK_IMRAN,
    USER_PATIENT_PRIYA,
    loadtest_users,
)
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

NOW = dt.datetime.now(dt.UTC)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _display_time(value: dt.datetime) -> str:
    return value.astimezone(IST).strftime("%d %b %Y, %I:%M %p")


CLINIC_DOCTOR = "Dr. Ananya Rao"
CLINIC_DOCTOR_2 = "Dr. Vikram Kulkarni"


def uid(prefix: str, number: int) -> uuid.UUID:
    return uuid.UUID(f"{prefix}-0000-4000-8000-{number:012d}")


def _source(title: str, locator: str, patient_id: uuid.UUID, snippet: str) -> dict[str, object]:
    return {
        "id": locator,
        "type": "tool",
        "title": title,
        "locator": locator,
        "patient_id": str(patient_id),
        "observed_at": (NOW - dt.timedelta(minutes=4)).isoformat(),
        "status": "resolved",
        "snippet": snippet,
        "metadata": {"system": "scheduling"},
    }


async def seed(load_test: int) -> dict[str, int]:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    counts = {
        "patients": 0,
        "consents": 0,
        "medications": 0,
        "appointments": 0,
        "notifications": 0,
        "chat_sessions": 0,
        "chat_messages": 0,
        "encounters": 0,
        "transcripts": 0,
        "review_tasks": 0,
        "handoffs": 0,
        "fhir_links": 0,
        "contact_channels": 0,
        "stock_items": 0,
        "documents": 0,
    }
    try:
        async with sessionmaker() as session:
            for item in enrich_demo_patients():
                patient = Patient(
                    id=item["id"],
                    display_name=item["display_name"],
                    locale=item["locale"],
                    keycloak_subject=item["keycloak_subject"],
                    notify_email=item.get("notify_email"),
                    slack_user_id=item.get("slack_user_id"),
                    deleted_at=None,
                )
                await session.merge(patient)
                # merge does not always clear soft-delete on existing rows
                existing = await session.get(Patient, item["id"])
                if existing is not None and existing.deleted_at is not None:
                    existing.deleted_at = None
                    existing.notify_email = item.get("notify_email")
                    existing.slack_user_id = item.get("slack_user_id")
                counts["patients"] += 1

            from demo_contacts import contact_targets

            targets = contact_targets()
            for index, user in enumerate(loadtest_users(load_test), start=1):
                if user["role"] != "patient":
                    continue
                patient_id = uuid.UUID(str(user["patient_id"]))
                await session.merge(
                    Patient(
                        id=patient_id,
                        display_name=f"Load Test Patient {index:02d}",
                        locale="en-IN",
                        keycloak_subject=str(user["id"]),
                        notify_email=targets["patient_email"],
                        slack_user_id=targets["patient_slack"],
                    )
                )
                counts["patients"] += 1

            # Crosswalk to the public HAPI R4 sample Patient/example when using the
            # default demo FHIR_BASE_URL. Replace in staging with the HIS patient id.
            await session.merge(
                FhirPatientLink(
                    patient_id=PATIENT_PRIYA,
                    fhir_patient_id="example",
                    system="https://hapi.fhir.org/baseR4",
                )
            )
            counts["fhir_links"] += 1

            consents = [
                Consent(
                    id=uid("30000000", 1),
                    patient_id=PATIENT_PRIYA,
                    grantor_subject=USER_PATIENT_PRIYA,
                    caregiver_subject=USER_CAREGIVER_MEENA,
                    scopes=["chat", "records", "scheduling", "notifications"],
                    purpose="care",
                    status="active",
                    granted_at=NOW,
                    expires_at=NOW + dt.timedelta(days=180),
                )
            ]
            for consent in consents:
                await session.merge(consent)
                counts["consents"] += 1

            medications = [
                ("Metformin", "500 mg", "Twice daily after meals", "active"),
                ("Amlodipine", "5 mg", "Once daily in the morning", "active"),
                ("Vitamin D3", "60,000 IU", "Weekly for 8 weeks", "active"),
                ("Azithromycin", "500 mg", "Once daily for 3 days", "completed"),
            ]
            for index, (name, dose, frequency, status) in enumerate(medications, start=1):
                await session.merge(
                    Medication(
                        id=uid("40000000", index),
                        patient_id=PATIENT_PRIYA,
                        name=name,
                        dose=dose,
                        frequency=frequency,
                        status=status,
                        started_on=(NOW - dt.timedelta(days=30 + index)).date(),
                        ended_on=(
                            (NOW - dt.timedelta(days=5)).date() if status == "completed" else None
                        ),
                    )
                )
                counts["medications"] += 1

            appointments = [
                (
                    PATIENT_PRIYA,
                    "BANER",
                    CLINIC_DOCTOR,
                    "general_medicine",
                    NOW + dt.timedelta(days=6, hours=2),
                    "confirmed",
                ),
                (
                    PATIENT_PRIYA,
                    "BANER",
                    CLINIC_DOCTOR,
                    "general_medicine",
                    NOW - dt.timedelta(days=21),
                    "completed",
                ),
                (
                    PATIENT_ARJUN,
                    "KOTHRUD",
                    CLINIC_DOCTOR_2,
                    "orthopedics",
                    NOW + dt.timedelta(days=2, hours=5),
                    "confirmed",
                ),
                (
                    PATIENT_FATIMA,
                    "BANER",
                    CLINIC_DOCTOR,
                    "pediatrics",
                    NOW + dt.timedelta(days=1, hours=3),
                    "held",
                ),
                (
                    PATIENT_ROHAN,
                    "KOTHRUD",
                    CLINIC_DOCTOR_2,
                    "dermatology",
                    NOW - dt.timedelta(days=10),
                    "no_show",
                ),
            ]
            for index, (patient_id, clinic, doctor, specialty, starts_at, status) in enumerate(
                appointments, start=1
            ):
                await session.merge(
                    Appointment(
                        id=uid("41000000", index),
                        patient_id=patient_id,
                        clinic_code=clinic,
                        doctor_name=doctor,
                        specialty_code=specialty,
                        starts_at=starts_at,
                        duration_minutes=20,
                        status=status,
                        traffic_class="real",
                    )
                )
                counts["appointments"] += 1

            # Unlinked patients get Slack/email contacts here. Linked demo users are
            # mapped in keycloak_admin seed-demo / sync-demo-links with real Keycloak IDs
            # (fixture subject IDs diverge once Keycloak has already issued user UUIDs).
            contact_plans = planned_contacts(
                staff_workspace=settings.slack_staff_workspace_id,
                patient_workspace=settings.slack_patient_workspace_id,
                users=[],
            )
            if load_test > 0:
                contact_plans.extend(
                    planned_contacts(
                        staff_workspace=settings.slack_staff_workspace_id,
                        patient_workspace=settings.slack_patient_workspace_id,
                        users=loadtest_users(load_test),
                        patients=[],
                    )
                )
            for contact in contact_plans:
                row = await session.scalar(
                    select(ContactChannel).where(
                        ContactChannel.subject == contact["subject"],
                        ContactChannel.channel == contact["channel"],
                    )
                )
                if row is None:
                    session.add(
                        ContactChannel(
                            id=uuid.uuid5(
                                uuid.NAMESPACE_URL,
                                f"sahyog:contact:{contact['subject']}:{contact['channel']}",
                            ),
                            subject=contact["subject"],
                            patient_id=contact["patient_id"],
                            channel=contact["channel"],
                            address=contact["address"],
                            verified=contact["verified"],
                            opt_in=contact["opt_in"],
                            workspace_id=contact["workspace_id"],
                            verified_at=NOW,
                        )
                    )
                else:
                    row.address = contact["address"]
                    row.patient_id = contact["patient_id"]
                    row.verified = contact["verified"]
                    row.opt_in = contact["opt_in"]
                    row.workspace_id = contact["workspace_id"]
                    row.verified_at = NOW
                counts["contact_channels"] += 1

            next_appointment = appointments[0]
            appointment_id = uid("41000000", 1)
            notifications = [
                Notification(
                    id=uid("70000000", 1),
                    patient_id=PATIENT_PRIYA,
                    recipient_subject=USER_PATIENT_PRIYA,
                    recipient_role="patient",
                    template_id="booking_confirmed",
                    template_version=1,
                    channel="in_app",
                    status="sent",
                    title="Appointment confirmed",
                    body=(
                        f"Your appointment with {next_appointment[2]} at the Baner clinic is "
                        f"confirmed for {_display_time(next_appointment[4])}."
                    ),
                    payload={"appointment_id": str(appointment_id)},
                    traffic_class="real",
                ),
                Notification(
                    id=uid("70000000", 2),
                    patient_id=PATIENT_PRIYA,
                    recipient_subject=USER_PATIENT_PRIYA,
                    recipient_role="patient",
                    template_id="document_ready",
                    template_version=1,
                    channel="in_app",
                    status="read",
                    title="A document is ready",
                    body="A document shared by your care team is ready to view in Sahyog.",
                    payload={},
                    traffic_class="real",
                    read_at=NOW - dt.timedelta(days=1),
                ),
                Notification(
                    id=uid("70000000", 3),
                    patient_id=PATIENT_PRIYA,
                    recipient_subject=USER_DOCTOR_RAO,
                    recipient_role="doctor",
                    template_id="staff_handoff",
                    template_version=1,
                    channel="in_app",
                    status="sent",
                    title="Patient question awaiting review",
                    body="A patient has a question that needs a clinician decision.",
                    payload={},
                    traffic_class="real",
                ),
                Notification(
                    id=uid("70000000", 4),
                    patient_id=PATIENT_PRIYA,
                    recipient_subject=USER_FRONTDESK_IMRAN,
                    recipient_role="front_desk",
                    template_id="staff_handoff",
                    template_version=1,
                    channel="in_app",
                    status="sent",
                    title="Front-desk hand-off waiting",
                    body="A routine intake needs a booking confirmation at Baner.",
                    payload={},
                    traffic_class="real",
                ),
            ]
            for notification in notifications:
                await session.merge(notification)
                counts["notifications"] += 1

            priya_session = ChatSession(
                id=uid("50000000", 1),
                owner_subject=USER_PATIENT_PRIYA,
                owner_role="patient",
                patient_id=PATIENT_PRIYA,
                title="My next appointment",
                locale="en-IN",
                status="active",
                traffic_class="real",
            )
            doctor_session = ChatSession(
                id=uid("50000000", 2),
                owner_subject=USER_DOCTOR_RAO,
                owner_role="doctor",
                patient_id=None,
                title="Today's schedule",
                locale="en-IN",
                status="active",
                traffic_class="real",
            )
            for chat_session in (priya_session, doctor_session):
                await session.merge(chat_session)
                counts["chat_sessions"] += 1

            messages = [
                ChatMessage(
                    id=uid("51000000", 1),
                    session_id=priya_session.id,
                    role="user",
                    content="When is my next appointment?",
                    language="en-IN",
                    sources=[],
                    trace_id="demo-priya-1",
                ),
                ChatMessage(
                    id=uid("51000000", 2),
                    session_id=priya_session.id,
                    role="assistant",
                    content=(
                        f"Your next appointment is with {CLINIC_DOCTOR} at the Baner clinic on "
                        f"{_display_time(next_appointment[4])}. "
                        "This answer came from your scheduling record."
                    ),
                    language="en-IN",
                    sources=[
                        _source(
                            "Appointment record",
                            f"appointments/{appointment_id}",
                            PATIENT_PRIYA,
                            "Confirmed appointment, Baner clinic.",
                        )
                    ],
                    trace_id="demo-priya-1",
                    model_alias="local_small",
                ),
                ChatMessage(
                    id=uid("51000000", 3),
                    session_id=doctor_session.id,
                    role="user",
                    content="How many appointments are scheduled this week?",
                    language="en-IN",
                    sources=[],
                    trace_id="demo-doctor-1",
                ),
                ChatMessage(
                    id=uid("51000000", 4),
                    session_id=doctor_session.id,
                    role="assistant",
                    content=(
                        "Two upcoming appointments are visible in the Baner clinic scope. "
                        "Open the appointments grid for the full, server-filtered list."
                    ),
                    language="en-IN",
                    sources=[
                        _source(
                            "Appointment grid",
                            "appointments?clinic=BANER",
                            PATIENT_PRIYA,
                            "Two upcoming confirmed appointments.",
                        )
                    ],
                    trace_id="demo-doctor-1",
                    model_alias="local_small",
                ),
            ]
            for message in messages:
                await session.merge(message)
                counts["chat_messages"] += 1

            encounter = Encounter(
                id=uid("60000000", 1),
                patient_id=PATIENT_PRIYA,
                doctor_subject=USER_DOCTOR_RAO,
                doctor_name=CLINIC_DOCTOR,
                clinic_code="BANER",
                appointment_id=appointment_id,
                kind="scheduled",
                status="active",
                started_at=NOW - dt.timedelta(minutes=18),
                traffic_class="real",
            )
            await session.merge(encounter)
            counts["encounters"] += 1

            transcript = Transcript(
                id=uid("61000000", 1),
                encounter_id=encounter.id,
                status="ready",
                source="manual",
                language="en-IN",
                duration_ms=240_000,
            )
            await session.merge(transcript)
            counts["transcripts"] += 1

            turns = [
                ("doctor", "What brings you in today?"),
                ("patient", "I have had a mild headache for three days and my sleep is poor."),
                ("doctor", "Any fever, vomiting, weakness or vision change?"),
                ("patient", "No fever or vomiting. No weakness. My vision is normal."),
                (
                    "doctor",
                    "Your blood pressure today is 128 over 82. We will review your medicines.",
                ),
            ]
            for index, (speaker, text) in enumerate(turns, start=1):
                await session.merge(
                    TranscriptTurn(
                        id=uid("62000000", index),
                        transcript_id=transcript.id,
                        turn_index=index - 1,
                        speaker=speaker,
                        start_ms=(index - 1) * 45_000,
                        end_ms=index * 45_000,
                        text=text,
                        language="en-IN",
                    )
                )

            review = ReviewTask(
                id=uid("63000000", 1),
                patient_id=PATIENT_FATIMA,
                created_by_subject=USER_FRONTDESK_IMRAN,
                assigned_role="doctor",
                reason="Front desk requested a booking exception review",
                status="open",
                resource_type="appointment",
                resource_id=str(uid("41000000", 4)),
                due_at=NOW + dt.timedelta(hours=8),
            )
            await session.merge(review)
            counts["review_tasks"] += 1
            await session.merge(
                ReviewTask(
                    id=uid("63000000", 2),
                    patient_id=PATIENT_PRIYA,
                    created_by_subject=USER_FRONTDESK_IMRAN,
                    assigned_role="doctor",
                    reason="Confirm follow-up plan after mild headache consult",
                    status="open",
                    resource_type="encounter",
                    resource_id=str(uid("60000000", 1)),
                    due_at=NOW + dt.timedelta(hours=4),
                )
            )
            counts["review_tasks"] += 1

            handoffs = [
                Handoff(
                    id=uid("65000000", 1),
                    patient_id=PATIENT_PRIYA,
                    created_by_subject=USER_FRONTDESK_IMRAN,
                    clinic_code="BANER",
                    reason="Chest discomfort reported at front desk — clinician review needed",
                    status="open",
                    priority="emergency",
                    notes="Patient waiting in triage bay. BP 142/90.",
                    resource_type="chat_session",
                    resource_id=str(uid("50000000", 1)),
                    rule_ids=["chest_pain"],
                    sla_due_at=NOW + dt.timedelta(minutes=2),
                    delivery_status="sent",
                    notified_at=NOW - dt.timedelta(minutes=1),
                ),
                Handoff(
                    id=uid("65000000", 2),
                    patient_id=PATIENT_ARJUN,
                    created_by_subject=USER_FRONTDESK_IMRAN,
                    clinic_code="BANER",
                    reason="Medication clarification before refill",
                    status="open",
                    priority="urgent",
                    notes="Pharmacist flagged dose mismatch on last script.",
                    resource_type="appointment",
                    resource_id=str(uid("41000000", 2)),
                    rule_ids=["med_clarification"],
                    sla_due_at=NOW + dt.timedelta(minutes=15),
                    delivery_status="sent",
                    notified_at=NOW,
                ),
            ]
            for handoff in handoffs:
                await session.merge(handoff)
                counts["handoffs"] = counts.get("handoffs", 0) + 1

            await session.merge(
                MemoryPreference(
                    id=uid("64000000", 1),
                    subject=USER_PATIENT_PRIYA,
                    key="preferred_clinic",
                    value="BANER",
                )
            )

            signed_notes = await session.scalar(
                select(ClinicalNote).where(ClinicalNote.patient_id == PATIENT_PRIYA).limit(1)
            )

            from app.composition import build_app_services
            from app.modules.pharmacy.service import PharmacyService

            pharmacy = PharmacyService(build_app_services(settings), session)
            imported = await pharmacy.import_configured_csv()
            counts["stock_items"] = imported.row_count

            # One text PDF for Priya so the patient records view has a file to open.
            # pypdf reads embedded text; this sample is not a scan and does not use OCR.
            sys.path.insert(0, str(SCRIPT_DIR))
            from generate_synthetic import build_pdf

            sample_id = uid("70000000", 1)
            sample = await session.get(Document, sample_id)
            if sample is None or sample.status != "indexed":
                pdf_bytes = build_pdf(
                    [
                        "SYNTHETIC SAMPLE — NOT A SIGNED CLINICAL NOTE",
                        "Patient label: Priya Sharma",
                        "Department: General Medicine",
                        "Clinic: BANER",
                        "",
                        "Visit summary",
                        "Seasonal allergic rhinitis. The patient takes cetirizine at night.",
                        "No fever, chest pain, or breathlessness was recorded in this sample.",
                        "",
                        "Assessment",
                        "Symptoms are stable on the current antihistamine.",
                        "This file is synthetic demo data and must not be used for care.",
                        "",
                        "Plan",
                        "Continue cetirizine as already used. Review if symptoms worsen.",
                        "Text in this PDF is embedded so it can be read without OCR.",
                    ]
                )
                object_key = f"documents/{PATIENT_PRIYA}/{sample_id}"
                record_services = build_app_services(settings)
                try:
                    await record_services.storage.put(
                        key=object_key,
                        data=pdf_bytes,
                        content_type="application/pdf",
                    )
                    await session.merge(
                        Document(
                            id=sample_id,
                            patient_id=PATIENT_PRIYA,
                            uploaded_by_subject="system:seed",
                            kind="other",
                            title="Priya Sharma visit summary (sample)",
                            object_key=object_key,
                            content_type="application/pdf",
                            size_bytes=len(pdf_bytes),
                            checksum_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
                            language="en-IN",
                            status="queued",
                            error_code=None,
                            page_count=1,
                            scan_status="clean",
                            traffic_class="synthetic",
                        )
                    )
                    await session.commit()
                    from app.modules.records.ingest import ingest_document

                    await ingest_document(record_services, sample_id)
                finally:
                    await record_services.db.dispose()
            counts["documents"] = 1

            AuditRepository(session).append(
                actor_subject="system:seed",
                actor_role="service",
                action="seed.demo_synthetic_loaded",
                resource_type="demo_dataset",
                patient_id=PATIENT_PRIYA,
                metadata={
                    "counts": counts,
                    "load_test_patients": load_test,
                    "signed_notes_created": signed_notes is not None,
                },
            )
            await session.commit()
    finally:
        await engine.dispose()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--load-test", type=int, default=0, metavar="N")
    args = parser.parse_args()
    if args.load_test < 0 or args.load_test > 100:
        print("error: --load-test must be between 0 and 100", file=sys.stderr)
        return 2
    counts = asyncio.run(seed(args.load_test))
    print(json.dumps({"status": "seeded", "counts": counts}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
