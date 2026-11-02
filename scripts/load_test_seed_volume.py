#!/usr/bin/env python3
"""Seed load-test volume: pharmacy stock + appointments for loadtest patients.

Expects datasets from ``scripts/load_test_prepare_datasets.py``:
  - docs/evidence/datasets/load_test_pharmacy_stock.csv
  - docs/evidence/datasets/load_test_doctors.csv

Also attaches/indexes a few synthetic PDFs onto loadtest patients when ``--ingest-pdfs``
is set (NFR-PERF-02). Run via ``compose_run_api`` / ``./scripts/load_test_setup.sh``.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT / "packages" / "py-common"))
sys.path.insert(0, str(SCRIPT_DIR))

from demo_fixtures import loadtest_patient_id, loadtest_users  # noqa: E402


async def import_pharmacy(services: Any, path: Path) -> dict[str, Any]:
    from app.modules.pharmacy.service import PharmacyService

    async with services.db.sessionmaker() as session:
        pharmacy = PharmacyService(services, session)
        result = await pharmacy.import_csv(
            None,
            raw=path.read_bytes(),
            source="load_test_pharmacy_stock",
            actor_subject="system:load-test-seed",
        )
        await session.commit()
        return {
            "status": result.status,
            "row_count": result.row_count,
            "source": result.source,
        }


async def seed_appointments(
    services: Any,
    *,
    doctors_csv: Path,
    slots: int,
    cohort_size: int,
    seed: int,
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.repositories.models import Appointment, Patient
    rng = random.Random(seed)
    doctors: list[dict[str, str]] = []
    with doctors_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            doctors.append(
                {
                    "name": row["doctor_name"],
                    "clinic": row["clinic_code"],
                    "specialty": row["specialty_code"],
                }
            )
    if not doctors:
        raise RuntimeError(f"no doctors in {doctors_csv}")

    patient_ids = [
        loadtest_patient_id(str(user["username"]))
        for user in loadtest_users(cohort_size)
        if user.get("role") == "patient"
    ]
    created = 0
    updated = 0
    now = datetime.now(UTC)
    async with services.db.sessionmaker() as session:
        present = set(
            await session.scalars(select(Patient.id).where(Patient.id.in_(patient_ids)))
        )
        missing = [str(pid) for pid in patient_ids if pid not in present]
        if missing:
            raise RuntimeError(
                "loadtest patients missing; run scripts/seed-users.sh --load-test "
                f"{cohort_size} first. missing={missing[:5]}"
            )
        # Build future half-hour slots over ~120 weekdays; assign uniquely per doctor.
        starts: list[datetime] = []
        day = now.date()
        for _ in range(180):
            if day.weekday() != 6:
                cursor = datetime.combine(day, datetime.min.time().replace(hour=9), tzinfo=UTC)
                close = datetime.combine(day, datetime.min.time().replace(hour=17), tzinfo=UTC)
                while cursor < close:
                    if cursor > now + timedelta(minutes=30):
                        starts.append(cursor)
                    cursor += timedelta(minutes=30)
            day += timedelta(days=1)
        if not starts:
            raise RuntimeError("no future appointment starts available")
        # Per-doctor cursor into the shared start list so we avoid conflict queries at volume.
        doctor_offsets = {doctor["name"]: rng.randrange(len(starts)) for doctor in doctors}
        for index in range(slots):
            doctor = doctors[index % len(doctors)]
            patient_id = patient_ids[index % len(patient_ids)]
            offset = doctor_offsets[doctor["name"]]
            starts_at = starts[offset % len(starts)]
            doctor_offsets[doctor["name"]] = offset + 1
            appointment_id = uuid.UUID(f"8a100000-0000-4000-8000-{index + 1:012d}")
            existing = await session.get(Appointment, appointment_id)
            if existing is None:
                session.add(
                    Appointment(
                        id=appointment_id,
                        patient_id=patient_id,
                        clinic_code=doctor["clinic"],
                        doctor_name=doctor["name"],
                        specialty_code=doctor["specialty"],
                        starts_at=starts_at,
                        duration_minutes=20,
                        status="confirmed",
                        traffic_class="synthetic",
                    )
                )
                created += 1
            else:
                existing.patient_id = patient_id
                existing.clinic_code = doctor["clinic"]
                existing.doctor_name = doctor["name"]
                existing.specialty_code = doctor["specialty"]
                existing.starts_at = starts_at
                existing.traffic_class = "synthetic"
                existing.status = "confirmed"
                updated += 1
            if (created + updated) % 500 == 0:
                await session.commit()
        await session.commit()
    return {"appointments_created": created, "appointments_updated": updated, "slots": slots}


async def ingest_loadtest_pdfs(services: Any, *, count: int, seed: int) -> dict[str, Any]:
    # Reuse generate_synthetic helpers when available.
    from generate_synthetic import generate_documents

    async with services.db.sessionmaker() as session:
        created, updated, pending = await generate_documents(
            services, session, count, seed, cohort="loadtest"
        )
        await session.commit()
    statuses: dict[str, int] = {}
    for document_id in pending:
        from generate_synthetic import ingest_document

        status = await ingest_document(services, document_id)
        statuses[status] = statuses.get(status, 0) + 1
    return {
        "documents_created": created,
        "documents_updated": updated,
        "ingestion": statuses,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    from app.composition import build_app_services
    from app.core.config import get_settings
    from sahyog_common.logging import configure_logging

    settings = get_settings()
    configure_logging(settings.log_level)
    services = build_app_services(settings)
    report: dict[str, Any] = {"started_at": datetime.now(UTC).isoformat()}
    try:
        pharmacy_csv = Path(args.pharmacy_csv)
        doctors_csv = Path(args.doctors_csv)
        if not pharmacy_csv.is_absolute():
            pharmacy_csv = ROOT / pharmacy_csv
        if not doctors_csv.is_absolute():
            doctors_csv = ROOT / doctors_csv
        if args.import_pharmacy:
            report["pharmacy"] = await import_pharmacy(services, pharmacy_csv)
        if args.slots > 0:
            report["appointments"] = await seed_appointments(
                services,
                doctors_csv=doctors_csv,
                slots=args.slots,
                cohort_size=args.cohort_size,
                seed=args.seed,
            )
        if args.ingest_pdfs > 0:
            report["pdfs"] = await ingest_loadtest_pdfs(
                services, count=args.ingest_pdfs, seed=args.seed
            )
        report["status"] = "ok"
        return report
    finally:
        await services.db.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pharmacy-csv",
        default="docs/evidence/datasets/load_test_pharmacy_stock.csv",
    )
    parser.add_argument(
        "--doctors-csv",
        default="docs/evidence/datasets/load_test_doctors.csv",
    )
    parser.add_argument("--import-pharmacy", action="store_true", default=True)
    parser.add_argument("--no-import-pharmacy", action="store_false", dest="import_pharmacy")
    parser.add_argument("--slots", type=int, default=5000)
    parser.add_argument("--cohort-size", type=int, default=5)
    parser.add_argument("--ingest-pdfs", type=int, default=10)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    try:
        report = asyncio.run(run(args))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "failed", "error": str(exc)}), flush=True)
        return 2
    print(json.dumps(report, indent=2, default=str), flush=True)
    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
