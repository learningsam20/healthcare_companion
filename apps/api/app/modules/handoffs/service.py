"""Emergency / staff handoff creation with SLA and paging (Wave F)."""

from __future__ import annotations

import datetime as dt
import logging
import statistics
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.services import Services
from app.modules.notifications.service import NotificationService
from app.repositories.audit import AuditRepository
from app.repositories.models import Handoff

logger = logging.getLogger(__name__)

EMERGENCY_SLA = dt.timedelta(minutes=2)
EMERGENCY_SLA_SECONDS = int(EMERGENCY_SLA.total_seconds())


def record_first_ack(handoff: Handoff, *, at: dt.datetime | None = None) -> None:
    """Stamp first human acknowledgement (assign). Idempotent after first ack."""
    if handoff.acknowledged_at is not None:
        return
    now = at or dt.datetime.now(dt.UTC)
    created = handoff.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=dt.UTC)
    handoff.acknowledged_at = now
    handoff.mtta_seconds = max(0, int((now - created).total_seconds()))


def mtta_within_sla(handoff: Handoff) -> bool | None:
    """True when emergency ack beat the 2-minute SLA; None when not yet measured."""
    if handoff.mtta_seconds is None:
        return None
    if handoff.priority != "emergency":
        # Non-emergency uses a softer 15-minute desk target.
        return handoff.mtta_seconds <= 15 * 60
    return handoff.mtta_seconds <= EMERGENCY_SLA_SECONDS


async def mtta_summary(
    session: AsyncSession,
    *,
    window_hours: int = 24 * 30,
) -> dict[str, Any]:
    """Rolling MTTA stats from acknowledged handoffs (G-25 measurable path)."""
    since = dt.datetime.now(dt.UTC) - dt.timedelta(hours=window_hours)
    rows = list(
        await session.scalars(
            select(Handoff).where(
                Handoff.acknowledged_at.is_not(None),
                Handoff.mtta_seconds.is_not(None),
                Handoff.acknowledged_at >= since,
            )
        )
    )
    values = [int(row.mtta_seconds) for row in rows if row.mtta_seconds is not None]
    if not values:
        return {
            "window_hours": window_hours,
            "acknowledged_count": 0,
            "mean_seconds": None,
            "p50_seconds": None,
            "p95_seconds": None,
            "max_seconds": None,
            "within_sla_count": 0,
            "within_sla_ratio": None,
            "sla_seconds_emergency": EMERGENCY_SLA_SECONDS,
            "target_met": None,
        }
    sorted_vals = sorted(values)
    within = sum(1 for row in rows if mtta_within_sla(row) is True)
    ratio = within / len(values)
    p50 = float(statistics.median(sorted_vals))
    # Nearest-rank p95 for small samples.
    idx95 = min(len(sorted_vals) - 1, max(0, int(round(0.95 * (len(sorted_vals) - 1)))))
    p95 = float(sorted_vals[idx95])
    mean = float(statistics.fmean(sorted_vals))
    return {
        "window_hours": window_hours,
        "acknowledged_count": len(values),
        "mean_seconds": round(mean, 1),
        "p50_seconds": round(p50, 1),
        "p95_seconds": round(p95, 1),
        "max_seconds": float(max(sorted_vals)),
        "within_sla_count": within,
        "within_sla_ratio": round(ratio, 4),
        "sla_seconds_emergency": EMERGENCY_SLA_SECONDS,
        # Pilot target: mean MTTA ≤ emergency SLA when we have acknowledgements.
        "target_met": mean <= EMERGENCY_SLA_SECONDS,
    }


async def create_staff_handoff(
    session: AsyncSession,
    services: Services,
    *,
    patient_id: uuid.UUID | None,
    created_by_subject: str,
    actor_role: str,
    clinic_code: str,
    reason: str,
    notes: str,
    resource_type: str | None,
    resource_id: str | None,
    rule_ids: list[str] | None,
    priority: str = "emergency",
    trace_id: str | None = None,
    consent_id: uuid.UUID | None = None,
    locale: str = "en-IN",
) -> Handoff:
    """Persist a handoff, set SLA, notify staff, and audit."""
    now = dt.datetime.now(dt.UTC)
    sla_due = now + EMERGENCY_SLA if priority == "emergency" else now + dt.timedelta(minutes=15)
    handoff = Handoff(
        patient_id=patient_id,
        created_by_subject=created_by_subject,
        clinic_code=clinic_code,
        reason=reason[:500],
        status="open",
        priority=priority if priority in {"normal", "urgent", "emergency"} else "normal",
        notes=notes[:4000] if notes else None,
        resource_type=resource_type,
        resource_id=resource_id,
        rule_ids=list(rule_ids or []),
        sla_due_at=sla_due,
        delivery_status="pending",
    )
    session.add(handoff)
    await session.flush()

    audit = AuditRepository(session)
    audit.append(
        actor_subject=created_by_subject,
        actor_role=actor_role,
        action="handoff.created",
        resource_type="handoff",
        resource_id=str(handoff.id),
        patient_id=patient_id,
        consent_id=consent_id,
        trace_id=trace_id,
        metadata={
            "reason": reason,
            "priority": handoff.priority,
            "sla_due_at": sla_due.isoformat(),
            "rule_ids": list(rule_ids or []),
            "clinic_code": clinic_code,
        },
    )

    delivery_status = await _notify_staff(
        session,
        services,
        handoff=handoff,
        actor_subject=created_by_subject,
        actor_role=actor_role,
        trace_id=trace_id,
        locale=locale,
        emergency=priority == "emergency",
    )
    handoff.delivery_status = delivery_status
    if delivery_status in {"queued", "sent", "partial"}:
        handoff.notified_at = dt.datetime.now(dt.UTC)
    await session.flush()
    return handoff


async def _notify_staff(
    session: AsyncSession,
    services: Services,
    *,
    handoff: Handoff,
    actor_subject: str,
    actor_role: str,
    trace_id: str | None,
    locale: str,
    emergency: bool,
) -> str:
    recipient = (services.settings.notify_ops_subject or "").strip()
    if not recipient:
        logger.info(
            "handoff notify skipped — NOTIFY_OPS_SUBJECT unset",
            extra={"event": "handoff.notify_skipped", "handoff_id": str(handoff.id)},
        )
        return "skipped"
    handoff_id = str(handoff.id)
    sla_due = (
        handoff.sla_due_at.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
        if handoff.sla_due_at
        else "—"
    )
    queue_label = (
        f"{handoff.clinic_code} · {handoff.priority} · "
        f"call within 2 min · ticket {handoff_id[:8]}"
    )
    try:
        _notification, deliveries = await NotificationService(services, session).send(
            template_id="staff_handoff",
            recipient_subject=recipient,
            recipient_role="front_desk",
            patient_id=handoff.patient_id,
            locale=locale if locale in {"en-IN", "hi-IN", "mr-IN"} else "en-IN",
            data={
                "queue": queue_label,
                "handoff_id": handoff_id,
                "handoff_id_short": handoff_id[:8],
                "clinic_code": handoff.clinic_code,
                "priority": handoff.priority,
                "rule_ids": ",".join(str(r) for r in (handoff.rule_ids or [])) or "—",
                "sla_due_at": sla_due,
                "resource_type": handoff.resource_type or "—",
                "resource_id_short": (handoff.resource_id or "—")[:12],
            },
            actor_subject=actor_subject,
            actor_role=actor_role,
            trace_id=trace_id,
            requested_channels=["in_app", "slack_staff", "email"],
            emergency=emergency,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "handoff staff notify failed",
            extra={"event": "handoff.notify_failed", "handoff_id": str(handoff.id)},
            exc_info=exc,
        )
        return "failed"

    if not deliveries:
        return "sent"  # in-app row always created
    statuses = {d.status for d in deliveries}
    if statuses <= {"sent", "queued"}:
        return "queued" if "queued" in statuses else "sent"
    if "failed" in statuses and statuses & {"sent", "queued"}:
        return "partial"
    if statuses <= {"suppressed", "skipped"}:
        return "sent"  # in-app still delivered
    if "failed" in statuses:
        return "failed"
    return "partial"


async def mark_overdue_handoffs(session: AsyncSession, services: Services) -> dict[str, Any]:
    """Escalate open/assigned handoffs past sla_due_at (ARQ / metrics companion)."""
    now = dt.datetime.now(dt.UTC)
    rows = list(
        await session.scalars(
            select(Handoff).where(
                Handoff.status.in_(("open", "assigned")),
                Handoff.sla_due_at.is_not(None),
                Handoff.sla_due_at < now,
                Handoff.overdue_alerted_at.is_(None),
            ).limit(50)
        )
    )
    alerted = 0
    for handoff in rows:
        handoff.overdue_alerted_at = now
        alerted += 1
        if services.settings.notify_ops_subject:
            try:
                await NotificationService(services, session).send(
                    template_id="ops_alert",
                    recipient_subject=services.settings.notify_ops_subject,
                    recipient_role="admin",
                    patient_id=handoff.patient_id,
                    locale="en-IN",
                    data={
                        "alert": (
                            f"Handoff {handoff.id} overdue "
                            f"(clinic={handoff.clinic_code}, priority={handoff.priority}). "
                            "Open Escalations and call the desk path now."
                        ),
                        "alert_summary": (
                            f"OVERDUE {handoff.priority} · {handoff.clinic_code} · "
                            f"{str(handoff.id)[:8]}"
                        ),
                        "handoff_id": str(handoff.id),
                        "handoff_id_short": str(handoff.id)[:8],
                        "clinic_code": handoff.clinic_code,
                        "priority": handoff.priority,
                    },
                    actor_subject="system:handoff_sla",
                    actor_role="service",
                    requested_channels=["in_app", "email", "slack_staff"],
                    emergency=True,
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "overdue handoff alert failed",
                    extra={"event": "handoff.overdue_alert_failed", "handoff_id": str(handoff.id)},
                )
        AuditRepository(session).append(
            actor_subject="system:handoff_sla",
            actor_role="service",
            action="handoff.sla_breached",
            resource_type="handoff",
            resource_id=str(handoff.id),
            patient_id=handoff.patient_id,
            metadata={"sla_due_at": handoff.sla_due_at.isoformat() if handoff.sla_due_at else None},
        )
    await session.flush()
    return {"alerted": alerted, "checked_at": now.isoformat()}
