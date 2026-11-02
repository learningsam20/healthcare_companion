#!/usr/bin/env python3
"""Generate deterministic synthetic scheduling, document and transcript fixtures.

Nothing here is real patient data. The generator writes through the same models and
storage as the application, tags every row `synthetic`, and never creates a clinical
note or signature. Doctors and slots are derived from appointments: the scheduling
module has no separate doctor or slot table.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import random
import sys
import uuid
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT / "packages" / "py-common"))
sys.path.insert(0, str(SCRIPT_DIR))

from app.composition import build_app_services  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.modules.records.ingest import checksum, ingest_document  # noqa: E402
from app.repositories.audit import AuditRepository  # noqa: E402
from app.repositories.models import (  # noqa: E402
    Appointment,
    Document,
    DocumentChunk,
    Encounter,
    Patient,
    Transcript,
    TranscriptTurn,
)
from app.repositories.scheduling import AppointmentRepository  # noqa: E402
from demo_fixtures import (  # noqa: E402
    DEMO_PATIENTS,
    USER_DOCTOR_RAO,
    loadtest_patient_id,
    loadtest_users,
)
from sahyog_common.logging import configure_logging  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
CLINICS = ("BANER", "KOTHRUD")
SPECIALTIES = (
    "general_medicine",
    "cardiology",
    "dermatology",
    "pediatrics",
    "orthopedics",
    "ent",
    "ophthalmology",
    "psychiatry",
    "obstetrics_gynecology",
    "pulmonology",
)
DOCTOR_NAMES = (
    "Dr. Meera Nair",
    "Dr. Aditya Kulkarni",
    "Dr. Sana Sheikh",
    "Dr. Rohit Deshpande",
    "Dr. Neha Iyer",
    "Dr. Kabir Menon",
    "Dr. Leena Joshi",
    "Dr. Arvind Pillai",
    "Dr. Tara Bhatt",
    "Dr. Nikhil Sethi",
    "Dr. Pooja Rane",
    "Dr. Vivek Anand",
)

DIALOGUES: tuple[tuple[str, list[tuple[str, str]]], ...] = (
    (
        "en-IN",
        [
            ("doctor", "What brings you in today?"),
            ("patient", "I have had a dry cough for five days and feel tired."),
            ("doctor", "Any fever, breathlessness or chest pain?"),
            ("patient", "No fever and no chest pain. I feel breathless only on stairs."),
            ("doctor", "Your oxygen saturation is 98 percent and the chest is clear."),
            ("patient", "Should I continue my regular inhaler?"),
            ("doctor", "Yes, continue it and come back if the breathlessness worsens."),
            ("patient", "Thank you, doctor."),
        ],
    ),
    (
        "hi-IN",
        [
            ("doctor", "नमस्ते, आज तबीयत कैसी है?"),
            ("patient", "दो दिन से हल्का बुखार और सिरदर्द है।"),
            ("doctor", "क्या खांसी, उल्टी या सांस लेने में तकलीफ है?"),
            ("patient", "नहीं, सांस ठीक है। भूख कम लग रही है।"),
            ("doctor", "पानी ज़्यादा पिएं और आराम करें। बुखार के लिए दवा लिख रहा हूं।"),
            ("patient", "ठीक है डॉक्टर, धन्यवाद।"),
        ],
    ),
    (
        "en-IN",
        [
            ("doctor", "How is the knee pain after the physiotherapy sessions?"),
            ("patient", "Better than last week, but it still hurts when I climb stairs."),
            ("doctor", "Any swelling, locking or instability?"),
            ("patient", "A little swelling in the evening, no locking."),
            ("doctor", "Continue the exercises and apply ice after activity."),
            ("patient", "How long should I continue the exercises?"),
            ("doctor", "For four more weeks, then we will review the range of motion."),
            ("patient", "Understood."),
        ],
    ),
)


def uid(prefix: str, number: int) -> uuid.UUID:
    return uuid.UUID(f"{prefix}-0000-4000-8000-{number:012d}")


def escape_pdf(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def wrap_text(lines: list[str], width: int = 88) -> list[str]:
    wrapped: list[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        remaining = line
        while len(remaining) > width:
            split_at = remaining.rfind(" ", 0, width + 1)
            if split_at <= 0:
                split_at = width
            wrapped.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip()
        wrapped.append(remaining)
    return wrapped


def build_pdf(lines: list[str]) -> bytes:
    wrapped = wrap_text(lines)
    commands = ["BT", "/F1 11 Tf", "14 TL", "72 742 Td"]
    for line in wrapped:
        commands.append(f"({escape_pdf(line)}) Tj")
        commands.append("T*")
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_offset = len(output)
    output += b"xref\n0 6\n0000000000 65535 f \n"
    for number in range(1, 6):
        output += f"{offsets[number]:010d} 00000 n \n".encode()
    output += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    return bytes(output)


def document_lines(index: int, seed: int) -> list[str]:
    variant = seed + index
    return [
        "SYNTHETIC CLINICAL DOCUMENT",
        "This document is generated test data and contains no real patient information.",
        "",
        f"Document reference: SYN-{index:04d}",
        f"Synthetic patient label: Synthetic Patient {chr(65 + (index % 26))}",
        "Department: General Medicine",
        "",
        "Visit summary",
        "The patient attended a scheduled review with stable vital signs. "
        f"Blood pressure was {116 + variant % 17} over {72 + variant % 9}.",
        "There was no reported fever, chest pain, breathlessness at rest or fainting.",
        "Medication adherence was discussed and the current regimen was continued.",
        "",
        "Assessment",
        "Synthetic follow-up record for a stable chronic condition. "
        "No acute red flag was recorded in this generated document.",
        "",
        "Plan",
        "Continue the existing medication list and review in four weeks.",
        "Return earlier if symptoms worsen or a new red flag appears.",
        "This document is not a signed clinical note and must not be used for care.",
    ]


def build_doctors(count: int, rng: random.Random) -> list[dict[str, str]]:
    names = list(DOCTOR_NAMES)
    rng.shuffle(names)
    doctors: list[dict[str, str]] = []
    for index in range(count):
        base = names[index % len(names)]
        suffix = "" if index < len(names) else f" {index // len(names) + 1:02d}"
        doctors.append(
            {
                "name": f"{base}{suffix}"[:120],
                "clinic": CLINICS[index % len(CLINICS)],
                "specialty": SPECIALTIES[index % len(SPECIALTIES)],
            }
        )
    return doctors


def future_starts(now: dt.datetime, *, days: int = 120) -> list[dt.datetime]:
    """Build open clinic slot starts for SCALE-02-sized generation.

    Default ~120 weekdays × 16 half-hour slots ≈ 1.9k candidates per doctor;
    raise ``days`` when filling hundreds of thousands of slots across many doctors.
    """
    starts: list[dt.datetime] = []
    day = now.date()
    for _ in range(max(1, days)):
        if day.weekday() != 6:
            cursor = dt.datetime.combine(day, dt.time(9, 0), tzinfo=IST)
            close = dt.datetime.combine(day, dt.time(17, 0), tzinfo=IST)
            while cursor < close:
                if cursor > now + dt.timedelta(minutes=30):
                    starts.append(cursor)
                cursor += dt.timedelta(minutes=30)
        day += dt.timedelta(days=1)
    return starts


async def generate_appointments(
    session: AsyncSession,
    doctors: list[dict[str, str]],
    slots: int,
    now: dt.datetime,
    rng: random.Random,
) -> tuple[int, int]:
    repo = AppointmentRepository(session)
    created = 0
    updated = 0
    requested = max(slots, len(doctors)) if doctors else 0
    # Enough calendar horizon so doctors × open slots can satisfy SCALE-02 (480k).
    horizon_days = max(120, min(730, (requested // max(len(doctors), 1) // 16) + 30))
    candidates: list[list[dt.datetime]] = []
    for _ in doctors:
        starts = future_starts(now, days=horizon_days)
        rng.shuffle(starts)
        candidates.append(starts)
    for index in range(requested):
        doctor_index = index % len(doctors)
        doctor = doctors[doctor_index]
        starts_at: dt.datetime | None = None
        while candidates[doctor_index]:
            candidate = candidates[doctor_index].pop(0)
            if not await repo.has_conflict(
                doctor_name=doctor["name"],
                clinic_code=doctor["clinic"],
                starts_at=candidate,
            ):
                starts_at = candidate
                break
        if starts_at is None:
            continue
        appointment_id = uid("8a000000", index + 1)
        existing = await session.get(Appointment, appointment_id)
        appointment = Appointment(
            id=appointment_id,
            patient_id=None,
            clinic_code=doctor["clinic"],
            doctor_name=doctor["name"],
            specialty_code=doctor["specialty"],
            starts_at=starts_at,
            duration_minutes=20,
            status="confirmed",
            traffic_class="synthetic",
        )
        if existing is None:
            session.add(appointment)
            created += 1
            AuditRepository(session).append(
                actor_subject="system:synthetic",
                actor_role="service",
                action="appointment.created",
                resource_type="appointment",
                resource_id=str(appointment_id),
                metadata={
                    "synthetic": True,
                    "clinic_code": doctor["clinic"],
                    "specialty_code": doctor["specialty"],
                },
            )
        else:
            existing.clinic_code = appointment.clinic_code
            existing.doctor_name = appointment.doctor_name
            existing.specialty_code = appointment.specialty_code
            existing.starts_at = appointment.starts_at
            existing.duration_minutes = appointment.duration_minutes
            existing.status = appointment.status
            existing.traffic_class = appointment.traffic_class
            updated += 1
        if (created + updated) % 500 == 0:
            await session.commit()
    await session.commit()
    return created, updated


async def _patients_for_cohort(session: AsyncSession, cohort: str) -> list[uuid.UUID]:
    patient_ids: list[uuid.UUID] = []
    if cohort in {"demo", "both"}:
        patient_ids.extend(uuid.UUID(str(item["id"])) for item in DEMO_PATIENTS)
    if cohort in {"loadtest", "both"}:
        # First five loadtest patients (PERF-02 / matched-load cohort).
        for user in loadtest_users(5):
            if user.get("role") != "patient":
                continue
            if user.get("patient_id"):
                patient_ids.append(uuid.UUID(str(user["patient_id"])))
            else:
                patient_ids.append(loadtest_patient_id(str(user["username"])))
    # De-dupe while preserving order
    seen: set[uuid.UUID] = set()
    ordered: list[uuid.UUID] = []
    for item in patient_ids:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    present = set(await session.scalars(select(Patient.id).where(Patient.id.in_(ordered))))
    missing = [str(item) for item in ordered if item not in present]
    if missing:
        raise RuntimeError(
            "required patients are missing "
            f"(cohort={cohort}); run scripts/load-data.sh --sample and "
            "scripts/seed-users.sh --load-test 5 first. missing="
            + ",".join(missing[:8])
        )
    return ordered


async def generate_documents(
    services: Any,
    session: AsyncSession,
    count: int,
    seed: int,
    *,
    cohort: str = "demo",
) -> tuple[int, int, list[uuid.UUID]]:
    patient_ids = await _patients_for_cohort(session, cohort)
    created = 0
    updated = 0
    pending: list[uuid.UUID] = []
    for index in range(count):
        patient_id = patient_ids[index % len(patient_ids)]
        document_id = uid("8b000000", index + 1)
        data = build_pdf(document_lines(index + 1, seed))
        digest = checksum(data)
        existing = await session.get(Document, document_id)
        if existing is not None and existing.checksum_sha256 == digest:
            if existing.status != "indexed":
                pending.append(document_id)
            continue
        await services.storage.put(
            key=f"documents/{patient_id}/{document_id}",
            data=data,
            content_type="application/pdf",
        )
        if existing is None:
            document = Document(
                id=document_id,
                patient_id=patient_id,
                uploaded_by_subject="system:synthetic",
                kind="discharge_summary",
                title=f"Synthetic discharge summary {index + 1:03d}",
                object_key=f"documents/{patient_id}/{document_id}",
                content_type="application/pdf",
                size_bytes=len(data),
                checksum_sha256=digest,
                language="en-IN",
                status="queued",
                traffic_class="synthetic",
            )
            session.add(document)
            created += 1
        else:
            existing.title = f"Synthetic discharge summary {index + 1:03d}"
            existing.object_key = f"documents/{patient_id}/{document_id}"
            existing.size_bytes = len(data)
            existing.checksum_sha256 = digest
            existing.language = "en-IN"
            existing.status = "queued"
            existing.error_code = None
            existing.traffic_class = "synthetic"
            await session.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
            updated += 1
        AuditRepository(session).append(
            actor_subject="system:synthetic",
            actor_role="service",
            action="records.document_uploaded",
            resource_type="document",
            resource_id=str(document_id),
            patient_id=patient_id,
            metadata={
                "synthetic": True,
                "kind": "discharge_summary",
                "content_type": "application/pdf",
                "size_bytes": len(data),
            },
        )
        pending.append(document_id)
    await session.commit()
    return created, updated, pending


async def generate_transcripts(
    session: AsyncSession, count: int, now: dt.datetime, *, cohort: str = "demo"
) -> tuple[int, int]:
    patient_ids = await _patients_for_cohort(session, cohort)
    created = 0
    updated = 0
    for index in range(count):
        patient_id = patient_ids[index % len(patient_ids)]
        encounter_id = uid("8c000000", index + 1)
        transcript_id = uid("8d000000", index + 1)
        language, turns = DIALOGUES[index % len(DIALOGUES)]
        started_at = now - dt.timedelta(days=(index % 21) + 1, minutes=25 * index)
        encounter = await session.get(Encounter, encounter_id)
        if encounter is None:
            encounter = Encounter(
                id=encounter_id,
                patient_id=patient_id,
                doctor_subject=USER_DOCTOR_RAO,
                doctor_name="Dr. Ananya Rao",
                clinic_code=CLINICS[index % len(CLINICS)],
                appointment_id=None,
                kind="walk_in",
                status="closed",
                started_at=started_at,
                ended_at=started_at + dt.timedelta(minutes=20),
                traffic_class="synthetic",
            )
            session.add(encounter)
            created += 1
            AuditRepository(session).append(
                actor_subject="system:synthetic",
                actor_role="service",
                action="encounter.started",
                resource_type="encounter",
                resource_id=str(encounter_id),
                patient_id=patient_id,
                metadata={"synthetic": True, "kind": "walk_in"},
            )
        else:
            encounter.clinic_code = CLINICS[index % len(CLINICS)]
            encounter.started_at = started_at
            encounter.ended_at = started_at + dt.timedelta(minutes=20)
            encounter.traffic_class = "synthetic"
            updated += 1
        transcript = await session.get(Transcript, transcript_id)
        duration_ms = len(turns) * 30_000
        if transcript is None:
            transcript = Transcript(
                id=transcript_id,
                encounter_id=encounter_id,
                status="ready",
                source="manual",
                language=language,
                duration_ms=duration_ms,
            )
            session.add(transcript)
            AuditRepository(session).append(
                actor_subject="system:synthetic",
                actor_role="service",
                action="transcript.uploaded",
                resource_type="transcript",
                resource_id=str(transcript_id),
                patient_id=patient_id,
                metadata={
                    "synthetic": True,
                    "turns": len(turns),
                    "source": "manual",
                    "language": language,
                },
            )
        else:
            transcript.status = "ready"
            transcript.language = language
            transcript.duration_ms = duration_ms
        for turn_index, (speaker, text) in enumerate(turns):
            await session.merge(
                TranscriptTurn(
                    id=uid("8e000000", index * 100 + turn_index + 1),
                    transcript_id=transcript_id,
                    turn_index=turn_index,
                    speaker=speaker,
                    start_ms=turn_index * 30_000,
                    end_ms=(turn_index + 1) * 30_000,
                    text=text,
                    language=language,
                )
            )
    await session.commit()
    return created, updated


async def generate(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    if args.slots > 0 and args.doctors == 0:
        raise ValueError("--slots requires at least one --doctor")
    if args.pdfs > 0 and not settings.s3_configured:
        raise ValueError("S3 is not configured; PDF generation needs object storage")
    configure_logging(settings.log_level)
    services = build_app_services(settings)
    now = dt.datetime.now(IST)
    rng = random.Random(args.seed)  # noqa: S311 - determinism, not security
    doctors = build_doctors(args.doctors, rng)
    counts: dict[str, Any] = {
        "doctors": len(doctors),
        "appointments_created": 0,
        "appointments_updated": 0,
        "documents_created": 0,
        "documents_updated": 0,
        "transcripts_created": 0,
        "transcripts_updated": 0,
    }
    pending: list[uuid.UUID] = []
    try:
        async with services.db.sessionmaker() as session:
            if doctors:
                created, updated = await generate_appointments(
                    session, doctors, args.slots, now, rng
                )
                counts["appointments_created"] = created
                counts["appointments_updated"] = updated
            if args.pdfs:
                created, updated, pending = await generate_documents(
                    services, session, args.pdfs, args.seed, cohort=args.patient_cohort
                )
                counts["documents_created"] = created
                counts["documents_updated"] = updated
                counts["patient_cohort"] = args.patient_cohort
            if args.transcripts:
                created, updated = await generate_transcripts(
                    session, args.transcripts, now, cohort=args.patient_cohort
                )
                counts["transcripts_created"] = created
                counts["transcripts_updated"] = updated
            if any(
                counts[key]
                for key in (
                    "appointments_created",
                    "appointments_updated",
                    "documents_created",
                    "documents_updated",
                    "transcripts_created",
                    "transcripts_updated",
                )
            ):
                AuditRepository(session).append(
                    actor_subject="system:synthetic",
                    actor_role="service",
                    action="synthetic.dataset_generated",
                    resource_type="synthetic_dataset",
                    metadata={"synthetic": True, **counts},
                )
                await session.commit()

        if args.ingest and pending:
            statuses: dict[str, int] = {}
            for index, document_id in enumerate(pending, start=1):
                status = await ingest_document(services, document_id)
                statuses[status] = statuses.get(status, 0) + 1
                print(
                    json.dumps(
                        {
                            "ingesting": f"{index}/{len(pending)}",
                            "document_id": str(document_id),
                            "result": status,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
            counts["ingestion"] = statuses
            failed = sum(value for key, value in statuses.items() if key != "indexed")
            if failed:
                counts["status"] = "partial"
                counts["ingestion_failures"] = failed
        elif pending:
            counts["ingestion"] = "skipped"
        counts["status"] = counts.get("status", "ok")
        return counts
    finally:
        await services.db.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doctors", type=int, default=6, metavar="N")
    parser.add_argument("--slots", type=int, default=24, metavar="N")
    parser.add_argument("--pdfs", type=int, default=4, metavar="N")
    parser.add_argument("--transcripts", type=int, default=2, metavar="N")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--patient-cohort",
        choices=("demo", "loadtest", "both"),
        default="demo",
        help="Attach PDFs/transcripts to demo patients, loadtest.* patients, or both "
        "(use loadtest for NFR-PERF-02 against the load cohort)",
    )
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="Ingest generated PDFs through the real LiteLLM embedding path",
    )
    args = parser.parse_args()
    # Caps align with NFR-SCALE-02 (500 doctors, 480k slots, 2k PDFs). Full runs are heavy.
    if not 0 <= args.doctors <= 500:
        parser.error("--doctors must be between 0 and 500 (NFR-SCALE-02)")
    if not 0 <= args.slots <= 480_000:
        parser.error("--slots must be between 0 and 480000 (NFR-SCALE-02)")
    if not 0 <= args.pdfs <= 2000:
        parser.error("--pdfs must be between 0 and 2000 (NFR-SCALE-02)")
    if not 0 <= args.transcripts <= 2000:
        parser.error("--transcripts must be between 0 and 2000")
    try:
        counts = asyncio.run(generate(args))
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(counts, indent=2, sort_keys=True))
    return 1 if counts.get("status") == "partial" else 0


if __name__ == "__main__":
    raise SystemExit(main())
