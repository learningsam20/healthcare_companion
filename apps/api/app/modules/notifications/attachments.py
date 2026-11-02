"""Operational email attachments (no PHI / clinical detail).

Allowed artefacts:
  - ICS calendar invites for appointment templates
  - Plain-text staff ticket briefs for handoff / ops alerts
"""

from __future__ import annotations

import base64
import datetime as dt
import re
from typing import Any


def _ics_stamp(value: dt.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def build_ics(
    *,
    uid: str,
    summary: str,
    description: str,
    starts_at: dt.datetime,
    duration_minutes: int,
    location: str = "",
    method: str = "REQUEST",
) -> bytes:
    """Minimal RFC 5545 VEVENT. No attendee emails (privacy)."""
    duration = max(5, min(int(duration_minutes), 480))
    ends_at = starts_at + dt.timedelta(minutes=duration)
    stamp = _ics_stamp(dt.datetime.now(dt.UTC))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Sahyog//Notifications//EN",
        f"METHOD:{method}",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"DTSTART:{_ics_stamp(starts_at)}",
        f"DTEND:{_ics_stamp(ends_at)}",
        f"SUMMARY:{_ics_escape(summary)}",
        f"DESCRIPTION:{_ics_escape(description)}",
    ]
    if location:
        lines.append(f"LOCATION:{_ics_escape(location)}")
    if method == "CANCEL":
        lines.append("STATUS:CANCELLED")
    lines.extend(["END:VEVENT", "END:VCALENDAR", ""])
    return "\r\n".join(lines).encode("utf-8")


def _ics_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _b64_attachment(*, filename: str, content_type: str, content: bytes) -> dict[str, str]:
    return {
        "filename": filename,
        "content_type": content_type,
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


def decode_attachments(raw: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Hydrate payload attachments for the SMTP adapter."""
    out: list[dict[str, Any]] = []
    for item in raw or []:
        try:
            content = base64.b64decode(str(item.get("content_base64") or ""), validate=True)
        except Exception:  # noqa: BLE001
            continue
        filename = str(item.get("filename") or "attachment.bin")[:120]
        content_type = str(item.get("content_type") or "application/octet-stream")[:120]
        if not content or len(content) > 100_000:
            continue
        out.append({"filename": filename, "content_type": content_type, "content": content})
    return out


def build_template_attachments(
    template_id: str,
    data: dict[str, Any],
) -> list[dict[str, str]]:
    """Return base64 payload attachments for approved templates only."""
    if template_id in {
        "booking_confirmed",
        "appointment_reminder",
        "appointment_rescheduled",
    }:
        return _appointment_ics(template_id, data, method="REQUEST")
    if template_id == "appointment_cancelled":
        return _appointment_ics(template_id, data, method="CANCEL")
    if template_id == "staff_handoff":
        return [_staff_ticket_brief(data)]
    if template_id == "ops_alert":
        alert = str(data.get("alert") or "").strip()
        if not alert:
            return []
        body = (
            "Sahyog operations alert\n"
            "=======================\n"
            f"{alert}\n\n"
            "Open the Escalations / Analytics console for follow-up.\n"
            "This file contains no patient identifiers.\n"
        ).encode("utf-8")
        return [
            _b64_attachment(
                filename="sahyog-ops-alert.txt",
                content_type="text/plain; charset=utf-8",
                content=body,
            )
        ]
    return []


def _parse_starts_at_iso(raw: str) -> dt.datetime | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


def _appointment_ics(
    template_id: str, data: dict[str, Any], *, method: str
) -> list[dict[str, str]]:
    starts = _parse_starts_at_iso(str(data.get("starts_at_iso") or ""))
    if starts is None:
        return []
    appointment_id = str(data.get("appointment_id") or "unknown")
    doctor = str(data.get("doctor_name") or "Clinic")
    clinic = str(data.get("clinic_code") or "")
    try:
        duration = int(data.get("duration_minutes") or 20)
    except (TypeError, ValueError):
        duration = 20
    summary = f"Clinic appointment · {doctor}"
    description = (
        f"Template: {template_id}\n"
        f"Doctor: {doctor}\n"
        f"Clinic: {clinic}\n"
        f"When (local): {data.get('starts_at') or ''}\n"
        "Open Sahyog → Appointments for details. No clinical content in this invite."
    )
    safe_uid = re.sub(r"[^a-zA-Z0-9._-]", "", appointment_id) or "appointment"
    content = build_ics(
        uid=f"{safe_uid}@sahyog.local",
        summary=summary,
        description=description,
        starts_at=starts,
        duration_minutes=duration,
        location=clinic,
        method=method,
    )
    return [
        _b64_attachment(
            filename="sahyog-appointment.ics",
            content_type="text/calendar; charset=utf-8; method=" + method,
            content=content,
        )
    ]


def _staff_ticket_brief(data: dict[str, Any]) -> dict[str, str]:
    lines = [
        "Sahyog staff handoff ticket",
        "===========================",
        f"Ticket: {data.get('handoff_id') or '—'}",
        f"Clinic: {data.get('clinic_code') or '—'}",
        f"Priority: {data.get('priority') or '—'}",
        f"SLA due: {data.get('sla_due_at') or '—'}",
        f"Rules: {data.get('rule_ids') or '—'}",
        f"Resource: {data.get('resource_type') or '—'} / {data.get('resource_id_short') or '—'}",
        "",
        "Action: Open Escalations, assign within SLA, call the desk/patient path.",
        "This brief intentionally omits patient names and clinical free text.",
        "",
    ]
    return _b64_attachment(
        filename="sahyog-handoff-ticket.txt",
        content_type="text/plain; charset=utf-8",
        content="\n".join(lines).encode("utf-8"),
    )
