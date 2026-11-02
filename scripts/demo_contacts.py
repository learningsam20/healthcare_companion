"""Shared demo email/Slack contact mapping for patients, staff, and other users.

Reads TEST_* env overrides (defaults match local smoke inboxes). Used by seed_demo
and keycloak seed so every demo identity has contact_channels + patient metadata.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from typing import Any

from demo_fixtures import DEMO_PATIENTS, DEMO_USERS, PATIENT_PRIYA

NOW = dt.datetime.now(dt.UTC)
STAFF_ROLES = frozenset({"doctor", "front_desk", "pharmacist", "compliance", "admin"})
PATIENT_ROLES = frozenset({"patient", "caregiver"})


def contact_targets() -> dict[str, str]:
    # Staff Slack: prefer an allowlisted channel (bot can post without a prior DM open).
    allowed = [
        part.strip()
        for part in (os.environ.get("SLACK_ALLOWED_CHANNELS") or "").split(",")
        if part.strip()
    ]
    staff_slack_default = allowed[0] if allowed else "C0CEKMA92EL"
    return {
        "patient_email": os.environ.get("TEST_PATIENT_EMAIL", "samdip2004@gmail.com").strip(),
        "staff_email": os.environ.get("TEST_STAFF_EMAIL", "learningsam20@gmail.com").strip(),
        "patient_slack": os.environ.get("TEST_PATIENT_SLACK_ID", "U0CDT655E1X").strip(),
        "staff_slack": os.environ.get("TEST_STAFF_SLACK_ID", staff_slack_default).strip(),
    }


def enrich_demo_users(users: list[dict[str, object]] | None = None) -> list[dict[str, object]]:
    """Attach notify_email / slack_id / slack_audience onto each demo (or loadtest) user."""
    targets = contact_targets()
    enriched: list[dict[str, object]] = []
    for user in users if users is not None else DEMO_USERS:
        role = str(user["role"])
        copy = dict(user)
        if role in PATIENT_ROLES:
            copy["notify_email"] = targets["patient_email"]
            copy["slack_id"] = targets["patient_slack"]
            copy["slack_audience"] = "patient"
        else:
            copy["notify_email"] = targets["staff_email"]
            copy["slack_id"] = targets["staff_slack"]
            copy["slack_audience"] = "staff"
        enriched.append(copy)
    return enriched


def enrich_demo_patients(
    patients: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Attach notify_email / slack_user_id onto every demo patient row."""
    targets = contact_targets()
    enriched: list[dict[str, object]] = []
    for item in patients if patients is not None else DEMO_PATIENTS:
        copy = dict(item)
        copy["notify_email"] = targets["patient_email"]
        copy["slack_user_id"] = targets["patient_slack"]
        enriched.append(copy)
    return enriched


def contact_uid(prefix: str, index: int) -> uuid.UUID:
    return uuid.UUID(f"{prefix}-0000-4000-8000-{index:012d}")


def planned_contacts(
    *,
    staff_workspace: str = "",
    patient_workspace: str = "",
    users: list[dict[str, object]] | None = None,
    patients: list[dict[str, object]] | None = None,
) -> list[dict[str, Any]]:
    """Build the full set of contact_channel rows for demo users + unlinked patients."""
    targets = contact_targets()
    rows: list[dict[str, Any]] = []
    index = 1

    for user in enrich_demo_users(users):
        role = str(user["role"])
        subject = str(user["id"])
        patient_id = (
            uuid.UUID(str(user["patient_id"]))
            if user.get("patient_id")
            else (PATIENT_PRIYA if role in PATIENT_ROLES else None)
        )
        if role in PATIENT_ROLES:
            email = str(user.get("notify_email") or targets["patient_email"])
            slack_channel = "slack_patient"
            slack_id = str(user.get("slack_id") or targets["patient_slack"])
            workspace = patient_workspace or None
            opt_in = True
            bind_patient = patient_id
        else:
            email = str(user.get("notify_email") or targets["staff_email"])
            slack_channel = "slack_staff"
            slack_id = str(user.get("slack_id") or targets["staff_slack"])
            workspace = staff_workspace or None
            opt_in = False
            bind_patient = None

        for channel, address, channel_opt_in, ws in (
            ("email", email, True, None),
            (slack_channel, slack_id, opt_in, workspace),
        ):
            if not address:
                continue
            rows.append(
                {
                    "id": contact_uid("43000000", index),
                    "subject": subject,
                    "patient_id": bind_patient,
                    "channel": channel,
                    "address": address,
                    "verified": True,
                    "opt_in": channel_opt_in,
                    "workspace_id": ws,
                    "username": user.get("username"),
                    "role": role,
                }
            )
            index += 1

    # Patients without their own Keycloak login still get Slack/email metadata contacts
    # keyed by a synthetic subject so patient_id lookups succeed.
    for item in enrich_demo_patients(patients):
        if item.get("keycloak_subject"):
            continue
        patient_id = item["id"]
        assert isinstance(patient_id, uuid.UUID)
        subject = f"patient:{patient_id}"
        email = str(item.get("notify_email") or targets["patient_email"])
        slack_id = str(item.get("slack_user_id") or targets["patient_slack"])
        for channel, address, ws in (
            ("email", email, None),
            ("slack_patient", slack_id, patient_workspace or None),
        ):
            if not address:
                continue
            rows.append(
                {
                    "id": contact_uid("43000000", index),
                    "subject": subject,
                    "patient_id": patient_id,
                    "channel": channel,
                    "address": address,
                    "verified": True,
                    "opt_in": True,
                    "workspace_id": ws,
                    "username": None,
                    "role": "patient",
                }
            )
            index += 1
    return rows
