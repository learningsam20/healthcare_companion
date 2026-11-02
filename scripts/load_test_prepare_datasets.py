#!/usr/bin/env python3
"""Build load_test_* CSV datasets from checked-in public Kaggle extracts.

Sources (already under data/raw/ when downloaded via load-data.sh):
  - medicines: A-Z Medicine Dataset of India → pharmacy stock CSV
  - patients: Healthcare Dataset → doctor + patient name catalogues for load tests

Does not invent public-source rows; it only reshapes existing extracts into the
stock import schema and a load-test doctor/patient reference used by
``scripts/load_test_seed_volume.py``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "evidence" / "datasets"
MEDICINES = ROOT / "data" / "raw" / "medicines" / "A_Z_medicines_dataset_of_India.csv"
HEALTHCARE = ROOT / "data" / "raw" / "patients" / "healthcare_dataset.csv"

CLINICS = ("BANER", "KOTHRUD")


def _sku(index: int) -> str:
    return f"LT-{index:06d}"


def _parse_form_strength(name: str, pack: str, composition: str) -> tuple[str, str]:
    pack_l = (pack or "").lower()
    form = "other"
    for token in ("tablet", "capsule", "syrup", "injection", "cream", "ointment", "drops", "inhaler", "powder"):
        if token in pack_l or token in name.lower():
            form = token
            break
    strength = ""
    match = re.search(r"(\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|%)(?:\s*/\s*\d+\s*ml)?)", composition or "", re.I)
    if match:
        strength = match.group(1).strip()
    return form, strength


def build_pharmacy(*, limit: int, seed: int) -> dict[str, object]:
    if not MEDICINES.is_file():
        raise SystemExit(
            f"missing {MEDICINES}; run ./scripts/load-data.sh --download --source medicines"
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "load_test_pharmacy_stock.csv"
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    written = 0
    skipped_disc = 0
    with MEDICINES.open(newline="", encoding="utf-8") as src, out.open(
        "w", newline="", encoding="utf-8"
    ) as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(
            dst,
            fieldnames=[
                "sku",
                "drug_name",
                "form",
                "strength",
                "quantity",
                "clinic_code",
                "updated_at",
                "source",
            ],
        )
        writer.writeheader()
        for row in reader:
            if str(row.get("Is_discontinued", "")).strip().upper() in {"TRUE", "1", "YES"}:
                skipped_disc += 1
                continue
            name = (row.get("name") or "").strip()
            if not name:
                continue
            form, strength = _parse_form_strength(
                name,
                row.get("pack_size_label") or "",
                (row.get("short_composition1") or "") + (row.get("short_composition2") or ""),
            )
            # Deterministic quantity from name hash so re-runs stay stable.
            digest = int(hashlib.sha256(f"{seed}:{name}".encode()).hexdigest()[:8], 16)
            quantity = 20 + (digest % 480)
            clinic = CLINICS[written % len(CLINICS)]
            writer.writerow(
                {
                    "sku": _sku(written + 1),
                    "drug_name": name[:200],
                    "form": form,
                    "strength": strength[:80],
                    "quantity": quantity,
                    "clinic_code": clinic,
                    "updated_at": now,
                    "source": "kaggle:az-medicine-dataset-of-india",
                }
            )
            written += 1
            if written >= limit:
                break
    return {
        "wrote": str(out.relative_to(ROOT)),
        "rows": written,
        "skipped_discontinued": skipped_disc,
        "limit": limit,
    }


def build_doctors_patients(*, doctor_limit: int, patient_limit: int) -> dict[str, object]:
    if not HEALTHCARE.is_file():
        raise SystemExit(
            f"missing {HEALTHCARE}; run ./scripts/load-data.sh --download --source patients"
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doctors_out = OUT_DIR / "load_test_doctors.csv"
    patients_out = OUT_DIR / "load_test_patients_ref.csv"
    doctors: list[str] = []
    patients: list[dict[str, str]] = []
    seen_doc: set[str] = set()
    seen_pat: set[str] = set()
    with HEALTHCARE.open(newline="", encoding="utf-8") as src:
        for row in csv.DictReader(src):
            doc = " ".join((row.get("Doctor") or "").split())
            if doc and doc not in seen_doc and len(doctors) < doctor_limit:
                seen_doc.add(doc)
                doctors.append(doc)
            name = " ".join((row.get("Name") or "").split())
            if name and name.casefold() not in seen_pat and len(patients) < patient_limit:
                seen_pat.add(name.casefold())
                patients.append(
                    {
                        "display_name": name.title(),
                        "doctor": doc or "",
                        "medical_condition": (row.get("Medical Condition") or "").strip(),
                        "medication": (row.get("Medication") or "").strip(),
                        "hospital": (row.get("Hospital") or "").strip(),
                    }
                )
            if len(doctors) >= doctor_limit and len(patients) >= patient_limit:
                break
    with doctors_out.open("w", newline="", encoding="utf-8") as dst:
        writer = csv.DictWriter(
            dst, fieldnames=["doctor_name", "clinic_code", "specialty_code"]
        )
        writer.writeheader()
        specialties = ("gp", "internal_medicine", "pediatrics", "ent", "dermatology")
        for index, name in enumerate(doctors):
            writer.writerow(
                {
                    "doctor_name": f"Dr. {name}" if not name.lower().startswith("dr") else name,
                    "clinic_code": CLINICS[index % len(CLINICS)],
                    "specialty_code": specialties[index % len(specialties)],
                }
            )
    with patients_out.open("w", newline="", encoding="utf-8") as dst:
        writer = csv.DictWriter(
            dst,
            fieldnames=[
                "display_name",
                "doctor",
                "medical_condition",
                "medication",
                "hospital",
            ],
        )
        writer.writeheader()
        writer.writerows(patients)
    return {
        "doctors_csv": str(doctors_out.relative_to(ROOT)),
        "patients_ref_csv": str(patients_out.relative_to(ROOT)),
        "doctors": len(doctors),
        "patients_ref": len(patients),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pharmacy-limit",
        type=int,
        default=25_000,
        help="Max active medicine rows to map into stock (default 25000)",
    )
    parser.add_argument("--doctor-limit", type=int, default=500)
    parser.add_argument("--patient-ref-limit", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    pharmacy = build_pharmacy(limit=max(1, args.pharmacy_limit), seed=args.seed)
    people = build_doctors_patients(
        doctor_limit=max(1, args.doctor_limit),
        patient_limit=max(1, args.patient_ref_limit),
    )
    print({"pharmacy": pharmacy, "cohort_ref": people})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
