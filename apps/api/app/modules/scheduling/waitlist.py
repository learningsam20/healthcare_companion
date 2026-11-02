"""Front-desk waitlist claim queue for high no-show-risk slots."""

from __future__ import annotations

import datetime as dt
import logging
import math
import uuid
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sahyog_common.errors import ProblemError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import GridMeta
from app.core.security import AuthContext, Role
from app.core.services import Services
from app.modules.notifications.service import NotificationService
from app.modules.scheduling.schemas import AppointmentOut
from app.repositories.audit import AuditRepository
from app.repositories.models import Appointment
from app.repositories.patients import PatientRepository
from app.repositories.scheduling import AppointmentRepository

logger = logging.getLogger(__name__)
CLINIC_TZ = ZoneInfo("Asia/Kolkata")

WaitlistStatus = Literal["open", "claimed", "closed"]
WaitlistResolution = Literal["kept", "offered", "dismissed"]


class WaitlistCloseRequest(BaseModel):
    resolution: WaitlistResolution
    notes: str | None = Field(default=None, max_length=500)
    offer_patient_id: uuid.UUID | None = None


class WaitlistItemOut(AppointmentOut):
    model_config = ConfigDict(from_attributes=True)

    offer_patient_display_name: str | None = None


SORT_COLUMNS = {
    "starts_at": Appointment.starts_at,
    "created_at": Appointment.created_at,
    "no_show_risk": Appointment.no_show_risk,
    "waitlist_claimed_at": Appointment.waitlist_claimed_at,
}


def _clinic_scope(context: AuthContext) -> tuple[str, ...] | None:
    if context.primary_role is Role.ADMIN:
        return None
    return tuple(context.clinic_ids)


async def list_waitlist(
    session: AsyncSession,
    services: Services,
    context: AuthContext,
    *,
    status: str | None,
    clinic: str | None,
    query: str | None,
    page: int,
    page_size: int,
    sort: str,
    order: str,
    locale: str,
) -> dict[str, Any]:
    conditions = [
        Appointment.waitlist_suggested.is_(True),
        Appointment.waitlist_status.is_not(None),
    ]
    scope = _clinic_scope(context)
    if scope is not None:
        conditions.append(Appointment.clinic_code.in_(scope))
    if status in {"open", "claimed", "closed"}:
        conditions.append(Appointment.waitlist_status == status)
    elif status == "active":
        conditions.append(Appointment.waitlist_status.in_(("open", "claimed")))
    if clinic:
        conditions.append(Appointment.clinic_code == clinic)
    if query:
        pattern = f"%{query.strip()}%"
        conditions.append(
            or_(
                Appointment.doctor_name.ilike(pattern),
                Appointment.clinic_code.ilike(pattern),
                Appointment.specialty_code.ilike(pattern),
            )
        )

    column = SORT_COLUMNS.get(sort, Appointment.starts_at)
    direction = column.desc() if order == "desc" else column.asc()
    total = int(
        await session.scalar(select(func.count()).select_from(Appointment).where(*conditions)) or 0
    )
    rows = list(
        await session.scalars(
            select(Appointment)
            .where(*conditions)
            .order_by(direction, Appointment.id.asc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    )
    names = await AppointmentRepository(session).patient_names(
        {row.patient_id for row in rows if row.patient_id}
        | {row.waitlist_offer_patient_id for row in rows if row.waitlist_offer_patient_id}
    )
    kinds = await AppointmentRepository(session).visit_kinds(rows)
    items: list[WaitlistItemOut] = []
    for row in rows:
        base = AppointmentOut.model_validate(row).model_copy(
            update={
                "specialty_label": services.specialty_label(row.specialty_code, locale),
                "patient_display_name": names.get(row.patient_id) if row.patient_id else None,
                "visit_kind": kinds.get(row.id, "unknown"),
            }
        )
        items.append(
            WaitlistItemOut(
                **base.model_dump(),
                offer_patient_display_name=(
                    names.get(row.waitlist_offer_patient_id)
                    if row.waitlist_offer_patient_id
                    else None
                ),
            )
        )
    return {
        "items": items,
        "meta": GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort=sort,
            order=order,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    }


async def claim_waitlist_item(
    session: AsyncSession,
    context: AuthContext,
    appointment_id: uuid.UUID,
    *,
    trace_id: str | None,
) -> Appointment:
    appointment = await AppointmentRepository(session).get(appointment_id)
    if appointment is None or not appointment.waitlist_suggested:
        raise ProblemError(404, "waitlist_not_found", "Not found", "No waitlist item for this booking.")
    scope = _clinic_scope(context)
    if scope is not None and appointment.clinic_code not in scope:
        raise ProblemError(404, "waitlist_not_found", "Not found", "No waitlist item for this booking.")
    if appointment.waitlist_status == "closed":
        raise ProblemError(
            409, "waitlist_closed", "Already closed", "This waitlist item is already closed."
        )
    if (
        appointment.waitlist_status == "claimed"
        and appointment.waitlist_owner_subject
        and appointment.waitlist_owner_subject != context.subject
        and context.primary_role is not Role.ADMIN
    ):
        raise ProblemError(
            409,
            "waitlist_claimed",
            "Already claimed",
            "Another desk agent already claimed this slot.",
        )
    now = dt.datetime.now(dt.UTC)
    appointment.waitlist_status = "claimed"
    appointment.waitlist_owner_subject = context.subject
    if appointment.waitlist_claimed_at is None:
        appointment.waitlist_claimed_at = now
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="waitlist.claimed",
        resource_type="appointment",
        resource_id=str(appointment.id),
        patient_id=appointment.patient_id,
        consent_id=context.consent_id,
        trace_id=trace_id,
        metadata={"clinic_code": appointment.clinic_code, "no_show_band": appointment.no_show_band},
    )
    await session.flush()
    return appointment


async def close_waitlist_item(
    session: AsyncSession,
    services: Services,
    context: AuthContext,
    appointment_id: uuid.UUID,
    body: WaitlistCloseRequest,
    *,
    trace_id: str | None,
    locale: str,
) -> Appointment:
    appointment = await claim_waitlist_item(
        session, context, appointment_id, trace_id=trace_id
    )
    if body.resolution == "offered":
        if body.offer_patient_id is None:
            raise ProblemError(
                422,
                "offer_patient_required",
                "Patient required",
                "Choose a waitlist patient to offer this slot to.",
            )
        if not await PatientRepository(session).exists(body.offer_patient_id):
            raise ProblemError(404, "patient_not_found", "Not found", "No such patient.")
        if body.offer_patient_id == appointment.patient_id:
            raise ProblemError(
                422,
                "offer_patient_same",
                "Same patient",
                "Offer the slot to a different patient than the original booking.",
            )
        repo = AppointmentRepository(session)
        if appointment.status in {"held", "confirmed"}:
            await repo.update_status(appointment, "cancelled")
        if await repo.has_conflict(
            doctor_name=appointment.doctor_name,
            clinic_code=appointment.clinic_code,
            starts_at=appointment.starts_at,
            exclude_id=appointment.id,
        ):
            raise ProblemError(
                409,
                "slot_taken",
                "Slot unavailable",
                "That doctor already has another appointment at this time.",
            )
        offered = await repo.create(
            patient_id=body.offer_patient_id,
            clinic_code=appointment.clinic_code,
            doctor_name=appointment.doctor_name,
            specialty_code=appointment.specialty_code,
            starts_at=appointment.starts_at,
            duration_minutes=appointment.duration_minutes,
            traffic_class=context.traffic_class,
            status="confirmed",
            source="front_desk",
        )
        appointment.waitlist_offer_patient_id = body.offer_patient_id
        appointment.waitlist_offer_appointment_id = offered.id
        AuditRepository(session).append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="waitlist.offered",
            resource_type="appointment",
            resource_id=str(appointment.id),
            patient_id=body.offer_patient_id,
            consent_id=context.consent_id,
            trace_id=trace_id,
            metadata={
                "original_patient_id": str(appointment.patient_id) if appointment.patient_id else None,
                "offer_appointment_id": str(offered.id),
                "clinic_code": appointment.clinic_code,
            },
        )
        await _notify_offered(services, session, offered, locale=locale, actor_subject=context.subject, trace_id=trace_id)
    elif body.resolution == "kept":
        if appointment.status == "held":
            await AppointmentRepository(session).update_status(appointment, "confirmed")
    # dismissed: no appointment mutation

    now = dt.datetime.now(dt.UTC)
    appointment.waitlist_status = "closed"
    appointment.waitlist_closed_at = now
    appointment.waitlist_resolution = body.resolution
    if body.notes:
        appointment.waitlist_notes = body.notes.strip()[:500]
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="waitlist.closed",
        resource_type="appointment",
        resource_id=str(appointment.id),
        patient_id=appointment.patient_id,
        consent_id=context.consent_id,
        trace_id=trace_id,
        metadata={
            "resolution": body.resolution,
            "offer_appointment_id": (
                str(appointment.waitlist_offer_appointment_id)
                if appointment.waitlist_offer_appointment_id
                else None
            ),
        },
    )
    await session.flush()
    return appointment


async def _notify_offered(
    services: Services,
    session: AsyncSession,
    appointment: Appointment,
    *,
    locale: str,
    actor_subject: str,
    trace_id: str | None,
) -> None:
    if appointment.patient_id is None:
        return
    patient = await PatientRepository(session).get(appointment.patient_id)
    if patient is None or not patient.keycloak_subject:
        return
    starts_local = appointment.starts_at.astimezone(CLINIC_TZ)
    try:
        await NotificationService(services, session).send(
            template_id="booking_confirmed",
            recipient_subject=patient.keycloak_subject,
            recipient_role="patient",
            patient_id=appointment.patient_id,
            locale=locale,
            data={
                "doctor_name": appointment.doctor_name,
                "clinic_code": appointment.clinic_code,
                "starts_at": starts_local.strftime("%d %b %Y, %I:%M %p"),
                "starts_at_iso": appointment.starts_at.astimezone(dt.UTC).isoformat(),
                "duration_minutes": str(appointment.duration_minutes),
                "appointment_id": str(appointment.id),
            },
            actor_subject=actor_subject,
            actor_role="service",
            trace_id=trace_id,
        )
    except Exception:  # noqa: BLE001
        logger.warning("waitlist offer notification skipped", exc_info=True)
