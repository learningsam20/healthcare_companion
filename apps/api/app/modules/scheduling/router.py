from __future__ import annotations

import datetime as dt
import logging
import math
import uuid
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from app.core.db import get_session
from app.core.pagination import GridMeta
from app.core.security import (
    AuthContext,
    Role,
    doctor_schedule_name,
    get_auth_context,
    require_roles,
)
from app.core.services import Services, get_services
from app.modules.notifications.service import NotificationService
from app.modules.scheduling.schemas import (
    AppointmentCreate,
    AppointmentOut,
    DoctorOut,
    OverrideRequest,
    RescheduleRequest,
    SlotsOut,
)
from app.repositories.audit import AuditRepository
from app.repositories.models import Appointment
from app.repositories.patients import PatientRepository
from app.repositories.scheduling import AppointmentRepository
from fastapi import APIRouter, Depends, Query, Request, status
from sahyog_common.errors import ProblemError
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1", tags=["scheduling"])
logger = logging.getLogger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ContextDep = Annotated[AuthContext, Depends(get_auth_context)]
ServicesDep = Annotated[Services, Depends(get_services)]

GridAccess = Annotated[
    AuthContext,
    Depends(require_roles(Role.PATIENT, Role.CAREGIVER, Role.DOCTOR, Role.FRONT_DESK, Role.ADMIN)),
]
BookingAccess = Annotated[
    AuthContext, Depends(require_roles(Role.FRONT_DESK, Role.ADMIN, Role.DOCTOR))
]
OverrideAccess = Annotated[AuthContext, Depends(require_roles(Role.FRONT_DESK, Role.ADMIN))]
CancelAccess = Annotated[
    AuthContext,
    Depends(require_roles(Role.PATIENT, Role.CAREGIVER, Role.FRONT_DESK, Role.ADMIN)),
]

CLINIC_TZ = ZoneInfo("Asia/Kolkata")


def _trace(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _appointment_out(
    appointment: Appointment,
    services: Services,
    locale: str,
    *,
    patient_display_name: str | None = None,
    visit_kind: str | None = None,
) -> AppointmentOut:
    result = AppointmentOut.model_validate(appointment)
    return result.model_copy(
        update={
            "specialty_label": services.specialty_label(appointment.specialty_code, locale),
            "patient_display_name": patient_display_name,
            "visit_kind": visit_kind or "unknown",
        }
    )


async def _enrich_appointments(
    session: AsyncSession,
    rows: list[Appointment],
    services: Services,
    locale: str,
) -> list[AppointmentOut]:
    repo = AppointmentRepository(session)
    names = await repo.patient_names({row.patient_id for row in rows if row.patient_id})
    kinds = await repo.visit_kinds(rows)
    return [
        _appointment_out(
            row,
            services,
            locale,
            patient_display_name=names.get(row.patient_id) if row.patient_id else None,
            visit_kind=kinds.get(row.id, "unknown"),
        )
        for row in rows
    ]


async def _patient_id_for(context: AuthContext, session: AsyncSession) -> uuid.UUID:
    if context.patient_id is None:
        raise ProblemError(
            403,
            "patient_not_linked",
            "Patient not linked",
            "This account is not linked to a patient record.",
        )
    if context.primary_role is Role.CAREGIVER:
        consent = await PatientRepository(session).active_consent(
            caregiver_subject=context.subject,
            patient_id=context.patient_id,
            scope="scheduling",
            consent_id=context.consent_id,
        )
        if not consent:
            raise ProblemError(
                403,
                "consent_required",
                "Consent required",
                "The patient has not granted active scheduling consent to this caregiver.",
            )
    return context.patient_id


async def _notify_patient(
    services: Services,
    session: AsyncSession,
    *,
    appointment: Appointment,
    template_id: str,
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
    starts_at = starts_local.strftime("%d %b %Y, %I:%M %p")
    try:
        await NotificationService(services, session).send(
            template_id=template_id,
            recipient_subject=patient.keycloak_subject,
            recipient_role="patient",
            patient_id=appointment.patient_id,
            locale=locale,
            data={
                "doctor_name": appointment.doctor_name,
                "clinic_code": appointment.clinic_code,
                "starts_at": starts_at,
                "starts_at_iso": appointment.starts_at.astimezone(dt.UTC).isoformat(),
                "duration_minutes": str(appointment.duration_minutes),
                "appointment_id": str(appointment.id),
            },
            actor_subject=actor_subject,
            actor_role="service",
            trace_id=trace_id,
        )
    except Exception as exc:  # noqa: BLE001 - notification failure must not undo the booking
        logger.warning(
            "appointment notification skipped",
            extra={"event": "notification.skipped", "extra_fields": {"template": template_id}},
            exc_info=exc,
        )


def _staff_clinic_scope(context: AuthContext) -> tuple[str, ...]:
    if context.primary_role is Role.ADMIN:
        return ()
    if not context.clinic_ids:
        raise ProblemError(
            403,
            "clinic_scope_missing",
            "Clinic scope missing",
            "A staff account must be assigned to at least one clinic.",
        )
    return context.clinic_ids


async def _grid_scope(
    context: AuthContext, session: AsyncSession
) -> tuple[uuid.UUID | None, tuple[str, ...], str | None]:
    """Return patient_id, clinic_scope, and optional doctor_name lock for the caller."""
    if context.primary_role in {Role.PATIENT, Role.CAREGIVER}:
        return await _patient_id_for(context, session), (), None
    doctor_name = doctor_schedule_name(context)
    if context.primary_role is Role.DOCTOR:
        if not doctor_name:
            raise ProblemError(
                403,
                "doctor_identity_missing",
                "Doctor identity missing",
                "This doctor account has no display name to match the schedule.",
            )
        return None, _staff_clinic_scope(context), doctor_name
    return None, _staff_clinic_scope(context), None


def _assert_doctor_owns(context: AuthContext, appointment: Appointment) -> None:
    locked = doctor_schedule_name(context)
    if context.primary_role is Role.DOCTOR and locked and appointment.doctor_name != locked:
        raise ProblemError(404, "appointment_not_found", "Not found", "No such appointment.")


@router.get("/appointments")
async def list_appointments(
    context: GridAccess,
    services: ServicesDep,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=120)] = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=20)] = None,
    specialty: Annotated[str | None, Query(max_length=40)] = None,
    clinic: Annotated[str | None, Query(max_length=40)] = None,
    source: Annotated[Literal["assistant", "front_desk"] | None, Query()] = None,
    date_from: Annotated[dt.date | None, Query()] = None,
    date_to: Annotated[dt.date | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort: Annotated[
        Literal["starts_at", "doctor_name", "clinic_code", "status", "created_at"], Query()
    ] = "starts_at",
    order: Annotated[Literal["asc", "desc"], Query()] = "asc",
) -> dict[str, object]:
    if not services.features.enabled("all_role_assistants"):
        raise ProblemError(
            403,
            "feature_disabled",
            "Scheduling unavailable",
            "Scheduling is disabled by configuration.",
        )
    patient_id, clinic_scope, doctor_name = await _grid_scope(context, session)
    starts_after = (
        dt.datetime.combine(date_from, dt.time.min, tzinfo=CLINIC_TZ) if date_from else None
    )
    starts_before = dt.datetime.combine(date_to, dt.time.max, tzinfo=CLINIC_TZ) if date_to else None
    rows, total = await AppointmentRepository(session).list_grid(
        query=q,
        status=status_filter,
        specialty=specialty,
        clinic=clinic,
        patient_id=patient_id,
        clinic_scope=clinic_scope,
        starts_after=starts_after,
        starts_before=starts_before,
        sort=sort,
        descending=order == "desc",
        limit=page_size,
        offset=(page - 1) * page_size,
        source=source,
        doctor_name=doctor_name,
    )
    return {
        "items": await _enrich_appointments(session, rows, services, context.locale),
        "meta": GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort=sort,
            order=order,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    }


@router.get("/doctors")
async def list_doctors(
    context: GridAccess,
    services: ServicesDep,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=120)] = None,
    specialty: Annotated[str | None, Query(max_length=40)] = None,
    clinic: Annotated[str | None, Query(max_length=40)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, object]:
    _, clinic_scope, doctor_name = await _grid_scope(context, session)
    selected_clinic = clinic
    if selected_clinic and clinic_scope and selected_clinic not in clinic_scope:
        raise ProblemError(403, "forbidden", "Access denied", "Clinic is outside your scope.")
    rows, total = await AppointmentRepository(session).doctors(
        query=q,
        specialty=specialty,
        clinic=selected_clinic,
        clinic_scope=() if selected_clinic else clinic_scope,
        doctor_name=doctor_name,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    items = [
        DoctorOut.model_validate(
            {
                **row,
                "specialty_label": services.specialty_label(
                    str(row["specialty_code"]), context.locale
                ),
            }
        )
        for row in rows
    ]
    return {
        "items": items,
        "meta": GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort="doctor_name",
            order="asc",
            pages=math.ceil(total / page_size) if total else 0,
        ),
    }


@router.get("/doctors/{doctor_name}/slots")
async def doctor_slots(
    doctor_name: str,
    context: GridAccess,
    session: SessionDep,
    clinic: Annotated[str, Query(min_length=2, max_length=40)],
    days: Annotated[int, Query(ge=1, le=21)] = 7,
) -> SlotsOut:
    _, clinic_scope, locked_doctor = await _grid_scope(context, session)
    if clinic_scope and clinic not in clinic_scope:
        raise ProblemError(403, "forbidden", "Access denied", "Clinic is outside your scope.")
    if locked_doctor and doctor_name != locked_doctor:
        raise ProblemError(
            403,
            "forbidden",
            "Access denied",
            "Doctors can only view their own free slots.",
        )
    now = dt.datetime.now(CLINIC_TZ)
    window_end = now + dt.timedelta(days=days)
    booked = await AppointmentRepository(session).booked_starts(
        doctor_name=doctor_name, clinic_code=clinic, start=now, end=window_end
    )
    slots: list[dt.datetime] = []
    day = now.date()
    for _ in range(days):
        if day.weekday() != 6:
            cursor = dt.datetime.combine(day, dt.time(9, 0), tzinfo=CLINIC_TZ)
            close = dt.datetime.combine(day, dt.time(17, 0), tzinfo=CLINIC_TZ)
            while cursor < close and len(slots) < 60:
                if cursor > now + dt.timedelta(minutes=30) and cursor not in booked:
                    slots.append(cursor)
                cursor += dt.timedelta(minutes=30)
        day += dt.timedelta(days=1)
    return SlotsOut(
        doctor_name=doctor_name,
        clinic_code=clinic,
        timezone="Asia/Kolkata",
        generated_for_days=days,
        slots=slots,
    )


@router.get("/appointments/{appointment_id}")
async def appointment_detail(
    appointment_id: uuid.UUID,
    request: Request,
    context: GridAccess,
    services: ServicesDep,
    session: SessionDep,
) -> AppointmentOut:
    appointment = await AppointmentRepository(session).get(appointment_id)
    if appointment is None:
        raise ProblemError(404, "appointment_not_found", "Not found", "No such appointment.")
    if context.primary_role in {Role.PATIENT, Role.CAREGIVER}:
        patient_id, _, _ = await _grid_scope(context, session)
        if appointment.patient_id != patient_id:
            raise ProblemError(404, "appointment_not_found", "Not found", "No such appointment.")
    elif context.primary_role is not Role.ADMIN:
        if appointment.clinic_code not in context.clinic_ids:
            raise ProblemError(404, "appointment_not_found", "Not found", "No such appointment.")
        _assert_doctor_owns(context, appointment)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="appointment.viewed",
        resource_type="appointment",
        resource_id=str(appointment.id),
        patient_id=appointment.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
    )
    await session.commit()
    enriched = await _enrich_appointments(session, [appointment], services, context.locale)
    return enriched[0]


@router.post("/appointments", status_code=status.HTTP_201_CREATED)
async def create_appointment(
    body: AppointmentCreate,
    request: Request,
    context: BookingAccess,
    services: ServicesDep,
    session: SessionDep,
) -> AppointmentOut:
    if context.primary_role is not Role.ADMIN and body.clinic_code not in context.clinic_ids:
        raise ProblemError(403, "forbidden", "Access denied", "Clinic is outside your scope.")
    doctor_name = body.doctor_name
    locked = doctor_schedule_name(context)
    if context.primary_role is Role.DOCTOR:
        if not locked:
            raise ProblemError(
                403,
                "doctor_identity_missing",
                "Doctor identity missing",
                "This doctor account has no display name to book against.",
            )
        doctor_name = locked
    if body.patient_id is None:
        raise ProblemError(
            422, "patient_required", "Patient required", "A patient must be selected for a booking."
        )
    if not await PatientRepository(session).exists(body.patient_id):
        raise ProblemError(404, "patient_not_found", "Not found", "No such patient.")
    if body.specialty_code not in services.specialty_codes():
        raise ProblemError(
            422, "specialty_invalid", "Specialty invalid", "Choose a specialty from the catalogue."
        )
    if body.starts_at.tzinfo is None:
        raise ProblemError(
            422,
            "timezone_required",
            "Timezone required",
            "Appointment times must include a timezone.",
        )
    if body.starts_at <= dt.datetime.now(dt.UTC):
        raise ProblemError(
            422, "time_in_past", "Time in the past", "Appointment times must be in the future."
        )
    repo = AppointmentRepository(session)
    if await repo.has_conflict(
        doctor_name=doctor_name,
        clinic_code=body.clinic_code,
        starts_at=body.starts_at,
    ):
        raise ProblemError(
            409,
            "slot_taken",
            "Slot unavailable",
            "That doctor already has an appointment at this time.",
        )
    appointment = await repo.create(
        patient_id=body.patient_id,
        clinic_code=body.clinic_code,
        doctor_name=doctor_name,
        specialty_code=body.specialty_code,
        starts_at=body.starts_at,
        duration_minutes=body.duration_minutes,
        traffic_class=context.traffic_class,
        source="front_desk",
    )
    from app.modules.scheduling.no_show_actions import score_and_act, score_metadata

    scored = await score_and_act(
        session,
        appointment,
        services=services,
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        locale=context.locale,
        trace_id=_trace(request),
        consent_id=context.consent_id,
    )
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="appointment.created",
        resource_type="appointment",
        resource_id=str(appointment.id),
        patient_id=appointment.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
        metadata={
            "clinic_code": appointment.clinic_code,
            "source": "front_desk",
            **score_metadata(scored),
        },
    )
    await _notify_patient(
        services,
        session,
        appointment=appointment,
        template_id="booking_confirm_reply" if scored.confirm_by_reply else "booking_confirmed",
        locale=context.locale,
        actor_subject=context.subject,
        trace_id=_trace(request),
    )
    await session.commit()
    await session.refresh(appointment)
    enriched = await _enrich_appointments(session, [appointment], services, context.locale)
    return enriched[0]


async def _cancellable(
    appointment_id: uuid.UUID,
    context: AuthContext,
    session: AsyncSession,
) -> Appointment:
    appointment = await AppointmentRepository(session).get(appointment_id)
    if appointment is None:
        raise ProblemError(404, "appointment_not_found", "Not found", "No such appointment.")
    if context.primary_role in {Role.PATIENT, Role.CAREGIVER}:
        patient_id, _, _ = await _grid_scope(context, session)
        if appointment.patient_id != patient_id:
            raise ProblemError(404, "appointment_not_found", "Not found", "No such appointment.")
    elif context.primary_role is not Role.ADMIN:
        if appointment.clinic_code not in context.clinic_ids:
            raise ProblemError(404, "appointment_not_found", "Not found", "No such appointment.")
        _assert_doctor_owns(context, appointment)
    if appointment.status not in {"held", "confirmed"}:
        raise ProblemError(
            409, "appointment_not_cancellable", "Cannot cancel", "This appointment is not active."
        )
    return appointment


@router.post("/appointments/{appointment_id}/confirm")
async def confirm_appointment(
    appointment_id: uuid.UUID,
    request: Request,
    context: CancelAccess,
    services: ServicesDep,
    session: SessionDep,
) -> AppointmentOut:
    """Confirm a soft-held slot (chat booking card countdown path)."""
    appointment = await _cancellable(appointment_id, context, session)
    if appointment.status == "confirmed":
        enriched = await _enrich_appointments(session, [appointment], services, context.locale)
        return enriched[0]
    if appointment.status != "held":
        raise ProblemError(
            409,
            "appointment_not_confirmable",
            "Cannot confirm",
            "Only held appointments can be confirmed.",
        )
    await AppointmentRepository(session).update_status(appointment, "confirmed")
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="appointment.confirmed",
        resource_type="appointment",
        resource_id=str(appointment.id),
        patient_id=appointment.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
        metadata={"clinic_code": appointment.clinic_code, "source": appointment.source},
    )
    await _notify_patient(
        services,
        session,
        appointment=appointment,
        template_id="booking_confirmed",
        locale=context.locale,
        actor_subject=context.subject,
        trace_id=_trace(request),
    )
    await session.commit()
    await session.refresh(appointment)
    enriched = await _enrich_appointments(session, [appointment], services, context.locale)
    return enriched[0]


@router.post("/appointments/{appointment_id}/cancel")
async def cancel_appointment(
    appointment_id: uuid.UUID,
    request: Request,
    context: CancelAccess,
    services: ServicesDep,
    session: SessionDep,
) -> AppointmentOut:
    appointment = await _cancellable(appointment_id, context, session)
    await AppointmentRepository(session).update_status(appointment, "cancelled")
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="appointment.cancelled",
        resource_type="appointment",
        resource_id=str(appointment.id),
        patient_id=appointment.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
        metadata={"clinic_code": appointment.clinic_code},
    )
    await _notify_patient(
        services,
        session,
        appointment=appointment,
        template_id="appointment_cancelled",
        locale=context.locale,
        actor_subject=context.subject,
        trace_id=_trace(request),
    )
    await session.commit()
    await session.refresh(appointment)
    enriched = await _enrich_appointments(session, [appointment], services, context.locale)
    return enriched[0]


@router.post("/appointments/{appointment_id}/reschedule")
async def reschedule_appointment(
    appointment_id: uuid.UUID,
    body: RescheduleRequest,
    request: Request,
    context: CancelAccess,
    services: ServicesDep,
    session: SessionDep,
) -> AppointmentOut:
    if body.starts_at.tzinfo is None:
        raise ProblemError(
            422,
            "timezone_required",
            "Timezone required",
            "Appointment times must include a timezone.",
        )
    if body.starts_at <= dt.datetime.now(dt.UTC):
        raise ProblemError(
            422, "time_in_past", "Time in the past", "Appointment times must be in the future."
        )
    appointment = await _cancellable(appointment_id, context, session)
    repo = AppointmentRepository(session)
    if await repo.has_conflict(
        doctor_name=appointment.doctor_name,
        clinic_code=appointment.clinic_code,
        starts_at=body.starts_at,
        exclude_id=appointment.id,
    ):
        raise ProblemError(
            409,
            "slot_taken",
            "Slot unavailable",
            "That doctor already has an appointment at this time.",
        )
    appointment.starts_at = body.starts_at
    if body.duration_minutes:
        appointment.duration_minutes = body.duration_minutes
    await session.flush()
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="appointment.rescheduled",
        resource_type="appointment",
        resource_id=str(appointment.id),
        patient_id=appointment.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
    )
    await _notify_patient(
        services,
        session,
        appointment=appointment,
        template_id="appointment_rescheduled",
        locale=context.locale,
        actor_subject=context.subject,
        trace_id=_trace(request),
    )
    await session.commit()
    await session.refresh(appointment)
    enriched = await _enrich_appointments(session, [appointment], services, context.locale)
    return enriched[0]


@router.post("/appointments/{appointment_id}/override")
async def override_appointment(
    appointment_id: uuid.UUID,
    body: OverrideRequest,
    request: Request,
    context: OverrideAccess,
    services: ServicesDep,
    session: SessionDep,
) -> AppointmentOut:
    appointment = await _cancellable(appointment_id, context, session)
    repo = AppointmentRepository(session)
    previous_start = appointment.starts_at
    if body.action == "reschedule":
        if body.starts_at is None:
            raise ProblemError(
                422,
                "starts_at_required",
                "Time required",
                "A new start time is required to reschedule.",
            )
        if body.starts_at.tzinfo is None:
            raise ProblemError(
                422,
                "timezone_required",
                "Timezone required",
                "Appointment times must include a timezone.",
            )
        if body.starts_at <= dt.datetime.now(dt.UTC):
            raise ProblemError(
                422,
                "time_in_past",
                "Time in the past",
                "Appointment times must be in the future.",
            )
        if await repo.has_conflict(
            doctor_name=appointment.doctor_name,
            clinic_code=appointment.clinic_code,
            starts_at=body.starts_at,
            exclude_id=appointment.id,
        ):
            raise ProblemError(
                409,
                "slot_taken",
                "Slot unavailable",
                "That doctor already has an appointment at this time.",
            )
        appointment.starts_at = body.starts_at
        if body.duration_minutes is not None:
            appointment.duration_minutes = body.duration_minutes
        template_id = "appointment_rescheduled"
    else:
        await repo.update_status(appointment, "cancelled")
        template_id = "appointment_cancelled"
    await session.flush()
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="appointment.overridden",
        resource_type="appointment",
        resource_id=str(appointment.id),
        patient_id=appointment.patient_id,
        trace_id=_trace(request),
        metadata={
            "action": body.action,
            "reason": body.reason,
            "previous_starts_at": previous_start.isoformat(),
            "starts_at": appointment.starts_at.isoformat(),
            "duration_minutes": appointment.duration_minutes,
        },
    )
    await _notify_patient(
        services,
        session,
        appointment=appointment,
        template_id=template_id,
        locale=context.locale,
        actor_subject=context.subject,
        trace_id=_trace(request),
    )
    await session.commit()
    await session.refresh(appointment)
    enriched = await _enrich_appointments(session, [appointment], services, context.locale)
    return enriched[0]
