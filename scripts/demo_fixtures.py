"""Deterministic identities shared by Keycloak seeding and database seeding.

The IDs are fixed so a re-run is idempotent and the patient link in a Keycloak token
matches the patient row. Nothing here is real data.
"""

from __future__ import annotations

import uuid

PATIENT_PRIYA = uuid.UUID("20000000-0000-4000-8000-000000000001")
PATIENT_ARJUN = uuid.UUID("20000000-0000-4000-8000-000000000002")
PATIENT_FATIMA = uuid.UUID("20000000-0000-4000-8000-000000000003")
PATIENT_ROHAN = uuid.UUID("20000000-0000-4000-8000-000000000004")

USER_PATIENT_PRIYA = "10000000-0000-4000-8000-000000000001"
USER_CAREGIVER_MEENA = "10000000-0000-4000-8000-000000000002"
USER_DOCTOR_RAO = "10000000-0000-4000-8000-000000000003"
USER_FRONTDESK_IMRAN = "10000000-0000-4000-8000-000000000004"
USER_PHARMACIST_KAVITA = "10000000-0000-4000-8000-000000000005"
USER_COMPLIANCE_AUDITOR = "10000000-0000-4000-8000-000000000006"
USER_ADMIN_OPS = "10000000-0000-4000-8000-000000000007"
USER_DOCTOR_KULKARNI = "10000000-0000-4000-8000-000000000008"
USER_PATIENT_ARJUN = "10000000-0000-4000-8000-000000000009"

_ALL_CLINICS = ["BANER", "KOTHRUD"]

DEMO_USERS: list[dict[str, object]] = [
    {
        "id": USER_PATIENT_PRIYA,
        "username": "patient.priya",
        "first_name": "Priya",
        "last_name": "Sharma",
        "email": "patient.priya@example.test",
        "role": "patient",
        "clinic_ids": ["BANER"],
        "patient_id": str(PATIENT_PRIYA),
        "locale": "en-IN",
        "traffic_class": "real",
        "cohort": "demo",
    },
    {
        "id": USER_CAREGIVER_MEENA,
        "username": "caregiver.meena",
        "first_name": "Meena",
        "last_name": "Sharma",
        "email": "caregiver.meena@example.test",
        "role": "caregiver",
        "clinic_ids": ["BANER"],
        "patient_id": str(PATIENT_PRIYA),
        "locale": "hi-IN",
        "traffic_class": "real",
        "cohort": "demo",
    },
    {
        "id": USER_DOCTOR_RAO,
        "username": "doctor.rao",
        "first_name": "Ananya",
        "last_name": "Rao",
        "email": "doctor.rao@example.test",
        "role": "doctor",
        "clinic_ids": ["BANER"],
        "patient_id": None,
        "doctor_display_name": "Dr. Ananya Rao",
        "locale": "en-IN",
        "traffic_class": "real",
        "cohort": "demo",
    },
    {
        "id": USER_DOCTOR_KULKARNI,
        "username": "doctor.kulkarni",
        "first_name": "Vikram",
        "last_name": "Kulkarni",
        "email": "doctor.kulkarni@example.test",
        "role": "doctor",
        "clinic_ids": ["BANER", "KOTHRUD"],
        "patient_id": None,
        "doctor_display_name": "Dr. Vikram Kulkarni",
        "locale": "en-IN",
        "traffic_class": "real",
        "cohort": "demo",
    },
    {
        "id": USER_PATIENT_ARJUN,
        "username": "patient.arjun",
        "first_name": "Arjun",
        "last_name": "Patil",
        "email": "patient.arjun@example.test",
        "role": "patient",
        "clinic_ids": ["BANER"],
        "patient_id": str(PATIENT_ARJUN),
        "locale": "mr-IN",
        "traffic_class": "real",
        "cohort": "demo",
    },
    {
        "id": USER_FRONTDESK_IMRAN,
        "username": "frontdesk.imran",
        "first_name": "Imran",
        "last_name": "Qureshi",
        "email": "frontdesk.imran@example.test",
        "role": "front_desk",
        "clinic_ids": ["BANER"],
        "patient_id": None,
        "locale": "hi-IN",
        "traffic_class": "real",
        "cohort": "demo",
    },
    {
        "id": USER_PHARMACIST_KAVITA,
        "username": "pharmacist.kavita",
        "first_name": "Kavita",
        "last_name": "Jadhav",
        "email": "pharmacist.kavita@example.test",
        "role": "pharmacist",
        "clinic_ids": ["BANER"],
        "patient_id": None,
        "locale": "mr-IN",
        "traffic_class": "real",
        "cohort": "demo",
    },
    {
        "id": USER_COMPLIANCE_AUDITOR,
        "username": "compliance.auditor",
        "first_name": "Rita",
        "last_name": "Fernandes",
        "email": "compliance.auditor@example.test",
        "role": "compliance",
        "clinic_ids": _ALL_CLINICS,
        "patient_id": None,
        "locale": "en-IN",
        "traffic_class": "real",
        "cohort": "demo",
    },
    {
        "id": USER_ADMIN_OPS,
        "username": "admin.ops",
        "first_name": "Sameer",
        "last_name": "Operations",
        "email": "admin.ops@example.test",
        "role": "admin",
        "clinic_ids": [],
        "patient_id": None,
        "locale": "en-IN",
        "traffic_class": "real",
        "cohort": "demo",
    },
]

DEMO_PATIENTS = [
    {
        "id": PATIENT_PRIYA,
        "display_name": "Priya Sharma",
        "locale": "en-IN",
        "keycloak_subject": USER_PATIENT_PRIYA,
    },
    {
        "id": PATIENT_ARJUN,
        "display_name": "Arjun Patil",
        "locale": "mr-IN",
        "keycloak_subject": USER_PATIENT_ARJUN,
    },
    {
        "id": PATIENT_FATIMA,
        "display_name": "Fatima Ansari",
        "locale": "hi-IN",
        "keycloak_subject": None,
    },
    {
        "id": PATIENT_ROHAN,
        "display_name": "Rohan Deshmukh",
        "locale": "en-IN",
        "keycloak_subject": None,
    },
]


def loadtest_subject(username: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"sahyog:loadtest:{username}"))


def loadtest_patient_id(username: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"sahyog:loadtest:patient:{username}")


def loadtest_users(count: int) -> list[dict[str, object]]:
    users: list[dict[str, object]] = []
    for index in range(1, count + 1):
        suffix = f"{index:02d}"
        patient_name = f"loadtest.patient{suffix}"
        users.append(
            {
                "id": loadtest_subject(patient_name),
                "username": patient_name,
                "first_name": "Load",
                "last_name": f"Patient {suffix}",
                "email": f"{patient_name}@example.test",
                "role": "patient",
                "clinic_ids": ["BANER"],
                "patient_id": str(loadtest_patient_id(patient_name)),
                "locale": "en-IN",
                "traffic_class": "synthetic",
                "cohort": "loadtest",
            }
        )
        desk_name = f"loadtest.frontdesk{suffix}"
        users.append(
            {
                "id": loadtest_subject(desk_name),
                "username": desk_name,
                "first_name": "Load",
                "last_name": f"Front desk {suffix}",
                "email": f"{desk_name}@example.test",
                "role": "front_desk",
                "clinic_ids": ["BANER"],
                "patient_id": None,
                "locale": "en-IN",
                "traffic_class": "synthetic",
                "cohort": "loadtest",
            }
        )
        doctor_name = f"loadtest.doctor{suffix}"
        users.append(
            {
                "id": loadtest_subject(doctor_name),
                "username": doctor_name,
                "first_name": "Load",
                "last_name": f"Doctor {suffix}",
                "email": f"{doctor_name}@example.test",
                "role": "doctor",
                "clinic_ids": ["BANER"],
                "patient_id": None,
                "locale": "en-IN",
                "traffic_class": "synthetic",
                "cohort": "loadtest",
            }
        )
    return users
