from __future__ import annotations

import datetime as dt
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from app.core.services import Services
from app.modules.notifications.attachments import build_template_attachments
from app.modules.notifications.format import (
    clean_subject_detail,
    plain_body,
    presentation_from_copy,
)
from app.repositories.audit import AuditRepository
from app.repositories.consents import ConsentRepository
from app.repositories.models import ContactChannel, Notification, NotificationDelivery, Patient
from app.repositories.notifications import ContactChannelRepository
from sahyog_common.errors import ProblemError
from sqlalchemy.ext.asyncio import AsyncSession

CHANNEL_FEATURE_FLAGS = {
    "email": "notifications_email",
    "sms": "notifications_sms",
    "slack_staff": "notifications_slack_staff",
    "slack_patient": "notifications_slack_patient",
}
# Placeholders permitted in approved copy. Never patient names / clinical free text.
ALLOWED_TEMPLATE_DATA = {
    "doctor_name",
    "clinic_code",
    "starts_at",
    "starts_at_iso",
    "duration_minutes",
    "appointment_id",
    "appointment_id_short",
    "queue",
    "channel",
    "alert",
    "alert_summary",
    "handoff_id",
    "handoff_id_short",
    "priority",
    "rule_ids",
    "sla_due_at",
    "resource_type",
    "resource_id_short",
    "document_kind",
    "action_url",
}


class NotificationError(ProblemError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(422, code, "Notification rejected", detail)


def in_quiet_hours(*, now: dt.datetime, start: str, end: str, timezone: str) -> bool:
    local = now.astimezone(ZoneInfo(timezone))
    start_time = dt.time.fromisoformat(start)
    end_time = dt.time.fromisoformat(end)
    current = local.time()
    if start_time <= end_time:
        return start_time <= current < end_time
    return current >= start_time or current < end_time


def quiet_hours_end(*, now: dt.datetime, start: str, end: str, timezone: str) -> dt.datetime:
    zone = ZoneInfo(timezone)
    local = now.astimezone(zone)
    start_time = dt.time.fromisoformat(start)
    end_time = dt.time.fromisoformat(end)
    candidate = dt.datetime.combine(local.date(), end_time, tzinfo=zone)
    if start_time <= end_time:
        if candidate <= local:
            candidate += dt.timedelta(days=1)
        return candidate
    if local.time() >= start_time:
        candidate += dt.timedelta(days=1)
    return candidate


def _default_action_path(template_id: str) -> str:
    if template_id == "staff_handoff":
        return "/escalations"
    if template_id == "ops_alert":
        return "/ops"
    if template_id == "document_ready":
        return "/records"
    if template_id == "delivery_failure":
        return "/notifications"
    return "/appointments"


class NotificationService:
    def __init__(self, services: Services, session: AsyncSession) -> None:
        self._services = services
        self._session = session
        self._config = services.notifications_config
        self._copy = services.notification_copy

    def _template(self, template_id: str) -> dict[str, Any]:
        for template in self._config.get("templates", []):
            if template.get("id") == template_id:
                return dict(template)
        raise NotificationError("unknown_template", "The notification template is not approved.")

    def _safe_data(self, data: dict[str, Any]) -> dict[str, str]:
        """Whitelist + empty defaults so subject_detail/body never KeyError on optional fields."""
        safe = {key: "" for key in ALLOWED_TEMPLATE_DATA}
        for key, value in data.items():
            if key not in ALLOWED_TEMPLATE_DATA or value is None:
                continue
            text = str(value).strip()
            # Defence in depth: strip CR/LF from subject-bound fields later; keep alert newlines.
            # Braces would be interpreted by format_map.
            text = " ".join(text.split()) if key != "alert" else text
            safe[key] = text.replace("{", "(").replace("}", ")")
        if not safe["appointment_id_short"] and safe["appointment_id"]:
            safe["appointment_id_short"] = safe["appointment_id"].split("-", 1)[0][:8]
        if not safe["handoff_id_short"] and safe["handoff_id"]:
            safe["handoff_id_short"] = safe["handoff_id"].split("-", 1)[0][:8]
        return safe

    def render(
        self, template_id: str, locale: str, data: dict[str, Any]
    ) -> tuple[str, str, dict[str, Any]]:
        self._template(template_id)
        language = locale.split("-")[0]
        entry = self._copy.get("templates", {}).get(template_id, {})
        copy = entry.get(language) or entry.get("en")
        if copy is None or not str(copy.get("intro") or "").strip():
            raise NotificationError("template_copy_missing", "Approved copy is missing.")
        safe_data = self._safe_data(data)
        try:
            subject = str(copy["subject"]).format_map(safe_data).strip()
            detail = clean_subject_detail(
                str(copy.get("subject_detail") or "").format_map(safe_data)
            )
            if detail:
                subject = f"{subject} — {detail}"
            # Email subjects are single-line and capped at the Notification.title column.
            subject = " ".join(subject.split())[:200]
            presentation = presentation_from_copy(copy, safe_data)
            return subject, plain_body(presentation), presentation
        except (KeyError, ValueError) as exc:
            raise NotificationError(
                "template_data_missing", "The notification is missing required data."
            ) from exc

    def _action_url(self, path: str = "/escalations") -> str:
        origins = self._services.settings.cors_origin_list
        base = (origins[0] if origins else "http://localhost:5705").rstrip("/")
        return f"{base}{path}"

    async def _contact_from_patient_metadata(
        self,
        *,
        channel: str,
        recipient_subject: str,
        patient_id: uuid.UUID,
    ) -> ContactChannel | None:
        """Fall back to Patient.notify_email / slack_user_id when no contact_channel row exists.

        Registration metadata is **not** a verified contact (G-06/G-07): the returned row is
        unverified and not opted in, so external delivery is suppressed
        (``recipient_unverified``) until the patient completes the verification code flow.
        """
        patient = await self._session.get(Patient, patient_id)
        if patient is None:
            return None
        address: str | None = None
        workspace: str | None = None
        opt_in = False
        if channel == "email":
            address = (patient.notify_email or "").strip() or None
        elif channel == "slack_patient":
            address = (patient.slack_user_id or "").strip() or None
            workspace = self._services.settings.slack_patient_workspace_id or None
        if not address:
            return None
        return ContactChannel(
            subject=recipient_subject,
            patient_id=patient_id,
            channel=channel,
            address=address,
            verified=False,
            opt_in=opt_in,
            workspace_id=workspace,
        )

    def _external_decision(
        self,
        *,
        channel: str,
        template: dict[str, Any],
        contact: ContactChannel | None,
        now: dt.datetime,
        emergency: bool,
        consent_ok: bool = True,
    ) -> tuple[str, str | None, dt.datetime]:
        if not self._services.settings.notify_send_external:
            return "suppressed", "external_disabled", now
        if not consent_ok:
            return "suppressed", "consent_required", now
        flag = CHANNEL_FEATURE_FLAGS.get(channel)
        if flag and not self._services.features.enabled(flag):
            return "suppressed", "feature_disabled", now
        channel_config = self._config.get("channels", {}).get(channel, {})
        if not channel_config.get("enabled"):
            return "suppressed", "channel_disabled", now
        if template.get("clinical_detail") or channel_config.get("allow_clinical_detail"):
            return "suppressed", "clinical_detail_not_allowed", now
        if contact is None:
            return "suppressed", "recipient_missing", now
        if not contact.verified:
            return "suppressed", "recipient_unverified", now
        if channel == "slack_patient":
            if channel_config.get("require_explicit_opt_in") and not contact.opt_in:
                return "suppressed", "opt_in_required", now
            expected = self._services.settings.slack_patient_workspace_id
            if not expected or contact.workspace_id != expected:
                return "suppressed", "workspace_mismatch", now
            patient_channels = {
                item.strip()
                for item in self._services.settings.slack_patient_allowed_channels.split(",")
                if item.strip()
            }
            if (
                patient_channels
                and contact.address.startswith("C")
                and contact.address not in patient_channels
            ):
                return "suppressed", "channel_not_allowed", now
        if channel == "slack_staff":
            expected = self._services.settings.slack_staff_workspace_id
            if not expected or contact.workspace_id != expected:
                return "suppressed", "workspace_mismatch", now
            allowed = {
                item.strip()
                for item in self._services.settings.slack_allowed_channels.split(",")
                if item.strip()
            }
            if contact.address.startswith("C") and contact.address not in allowed:
                return "suppressed", "channel_not_allowed", now
        quiet = self._config.get("quiet_hours", {})
        if (
            quiet.get("enabled")
            and not emergency
            and channel in set(quiet.get("applies_to", []))
            and in_quiet_hours(
                now=now,
                start=str(quiet.get("start", "21:00")),
                end=str(quiet.get("end", "08:00")),
                timezone=str(quiet.get("timezone", "Asia/Kolkata")),
            )
        ):
            return (
                "queued",
                None,
                quiet_hours_end(
                    now=now,
                    start=str(quiet.get("start", "21:00")),
                    end=str(quiet.get("end", "08:00")),
                    timezone=str(quiet.get("timezone", "Asia/Kolkata")),
                ),
            )
        return "queued", None, now

    async def send(
        self,
        *,
        template_id: str,
        recipient_subject: str,
        recipient_role: str,
        patient_id: uuid.UUID | None,
        locale: str,
        data: dict[str, Any],
        actor_subject: str,
        actor_role: str,
        trace_id: str | None = None,
        requested_channels: list[str] | None = None,
        emergency: bool = False,
        now: dt.datetime | None = None,
        action_path: str | None = None,
    ) -> tuple[Notification, list[NotificationDelivery]]:
        template = self._template(template_id)
        enriched = dict(data)
        if not enriched.get("action_url"):
            path = action_path or _default_action_path(template_id)
            enriched["action_url"] = self._action_url(path)
        if template_id == "ops_alert" and not enriched.get("alert_summary"):
            alert_text = str(enriched.get("alert") or "").strip()
            enriched["alert_summary"] = (alert_text[:80] + ("…" if len(alert_text) > 80 else "")) or "ops"
        subject, body, presentation = self.render(template_id, locale, enriched)
        email_cfg = self._config.get("channels", {}).get("email", {})
        attachments: list[dict[str, str]] = []
        if email_cfg.get("allow_attachments", False):
            attachments = build_template_attachments(template_id, enriched)
        current = now or dt.datetime.now(dt.UTC)
        notification = Notification(
            patient_id=patient_id,
            recipient_subject=recipient_subject,
            recipient_role=recipient_role,
            template_id=template_id,
            template_version=int(template.get("version", 1)),
            channel="in_app",
            status="sent",
            title=subject,
            body=body,
            payload={
                "template_id": template_id,
                "attachments": attachments,
                "attachment_count": len(attachments),
                "presentation": presentation,
            },
        )
        self._session.add(notification)
        await self._session.flush()
        contacts = ContactChannelRepository(self._session)
        deliveries: list[NotificationDelivery] = []
        allowed = set(requested_channels or template.get("channels", []))
        consent_ok = True
        if recipient_role == "caregiver" and patient_id is not None and not emergency:
            consent_ok = (
                await ConsentRepository(self._session).latest_active_for_patient(
                    caregiver_subject=recipient_subject,
                    patient_id=patient_id,
                    scope="notifications",
                )
                is not None
            )
        for channel in template.get("channels", []):
            if channel == "in_app" or channel not in allowed:
                continue
            contact = await contacts.find(
                subject=recipient_subject, channel=channel, patient_id=patient_id
            )
            if contact is None and patient_id is not None:
                contact = await self._contact_from_patient_metadata(
                    channel=channel,
                    recipient_subject=recipient_subject,
                    patient_id=patient_id,
                )
            status, error_code, scheduled_at = self._external_decision(
                channel=channel,
                template=template,
                contact=contact,
                now=current,
                emergency=emergency,
                consent_ok=consent_ok,
            )
            delivery = NotificationDelivery(
                notification_id=notification.id,
                channel=channel,
                status=status,
                attempts=0,
                last_error_code=error_code,
                scheduled_at=scheduled_at,
            )
            self._session.add(delivery)
            deliveries.append(delivery)
        await self._session.flush()
        AuditRepository(self._session).append(
            actor_subject=actor_subject,
            actor_role=actor_role,
            action="notifications.queued",
            resource_type="notification",
            resource_id=str(notification.id),
            patient_id=patient_id,
            trace_id=trace_id,
            metadata={
                "template_id": template_id,
                "channels": [delivery.channel for delivery in deliveries],
                "suppressed": sum(1 for delivery in deliveries if delivery.status == "suppressed"),
                "caregiver_consent": (
                    "not_applicable"
                    if recipient_role != "caregiver" or patient_id is None
                    else ("active" if consent_ok else "missing")
                ),
            },
        )
        return notification, deliveries
