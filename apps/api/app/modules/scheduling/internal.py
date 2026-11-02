"""Internal scheduling endpoints for MCP tools (key-auth, no JWT)."""

from __future__ import annotations

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.internal_auth import require_internal_api_key
from app.core.services import Services, get_services
from app.repositories.scheduling import AppointmentRepository

router = APIRouter(
    prefix="/api/v1/internal/scheduling",
    tags=["internal-scheduling"],
    dependencies=[Depends(require_internal_api_key)],
)

CLINIC_TZ = ZoneInfo("Asia/Kolkata")
SessionDep = Depends(get_session)
ServicesDep = Depends(get_services)


class DoctorOut(BaseModel):
    doctor_name: str
    specialty_code: str
    clinic_code: str
    appointments: int = 0
    next_slot: dt.datetime | None = None


class SlotOut(BaseModel):
    starts_at: dt.datetime
    doctor_name: str
    specialty_code: str
    clinic_code: str
    duration_minutes: int = 20


class HoldIn(BaseModel):
    patient_id: uuid.UUID | None = None
    clinic_code: str = Field(min_length=1, max_length=40)
    doctor_name: str = Field(min_length=1, max_length=120)
    specialty_code: str = Field(min_length=1, max_length=40)
    starts_at: dt.datetime
    duration_minutes: int = Field(default=20, ge=10, le=120)
    traffic_class: str = "real"
    source: str = Field(default="assistant", max_length=40)


class ConfirmIn(BaseModel):
    appointment_id: uuid.UUID


class CancelIn(BaseModel):
    appointment_id: uuid.UUID


class RescheduleIn(BaseModel):
    appointment_id: uuid.UUID
    starts_at: dt.datetime
    duration_minutes: int | None = Field(default=None, ge=10, le=120)


class AppointmentOut(BaseModel):
    id: uuid.UUID
    status: str
    doctor_name: str
    specialty_code: str
    clinic_code: str
    starts_at: dt.datetime
    duration_minutes: int
    patient_id: uuid.UUID | None = None


def _out(appointment) -> AppointmentOut:  # type: ignore[no-untyped-def]
    return AppointmentOut(
        id=appointment.id,
        status=appointment.status,
        doctor_name=appointment.doctor_name,
        specialty_code=appointment.specialty_code,
        clinic_code=appointment.clinic_code,
        starts_at=appointment.starts_at,
        duration_minutes=appointment.duration_minutes,
        patient_id=appointment.patient_id,
    )


@router.get("/doctors", response_model=list[DoctorOut])
async def search_doctors(
    specialty: str | None = Query(default=None),
    clinic_code: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=3, ge=1, le=20),
    session: AsyncSession = SessionDep,
) -> list[DoctorOut]:
    rows, _ = await AppointmentRepository(session).doctors(
        query=q,
        specialty=specialty,
        clinic=clinic_code,
        limit=limit,
        offset=0,
    )
    now = dt.datetime.now(CLINIC_TZ)
    items: list[DoctorOut] = []
    for row in rows:
        name = str(row["doctor_name"])
        clinic = str(row["clinic_code"])
        next_slot: dt.datetime | None = None
        booked = await AppointmentRepository(session).booked_starts(
            doctor_name=name,
            clinic_code=clinic,
            start=now,
            end=now + dt.timedelta(days=7),
        )
        cursor = now + dt.timedelta(minutes=30)
        cursor = cursor.replace(second=0, microsecond=0)
        minute = 0 if cursor.minute < 30 else 30
        cursor = cursor.replace(minute=minute)
        while cursor < now + dt.timedelta(days=7):
            if cursor.weekday() != 6 and 9 <= cursor.hour < 17 and cursor not in booked:
                next_slot = cursor
                break
            cursor += dt.timedelta(minutes=30)
        items.append(
            DoctorOut(
                doctor_name=name,
                specialty_code=str(row["specialty_code"]),
                clinic_code=clinic,
                appointments=int(row["appointments"]),
                next_slot=next_slot,
            )
        )
    return items


@router.get("/slots", response_model=list[SlotOut])
async def get_availability(
    doctor_name: str = Query(min_length=1, max_length=120),
    clinic_code: str = Query(min_length=1, max_length=40),
    specialty_code: str | None = Query(default=None),
    days: int = Query(default=7, ge=1, le=21),
    session: AsyncSession = SessionDep,
) -> list[SlotOut]:
    now = dt.datetime.now(CLINIC_TZ)
    window_end = now + dt.timedelta(days=days)
    booked = await AppointmentRepository(session).booked_starts(
        doctor_name=doctor_name,
        clinic_code=clinic_code,
        start=now,
        end=window_end,
    )
    slots: list[SlotOut] = []
    day = now.date()
    for _ in range(days):
        if day.weekday() != 6:
            cursor = dt.datetime.combine(day, dt.time(9, 0), tzinfo=CLINIC_TZ)
            close = dt.datetime.combine(day, dt.time(17, 0), tzinfo=CLINIC_TZ)
            while cursor < close and len(slots) < 40:
                if cursor > now + dt.timedelta(minutes=30) and cursor not in booked:
                    slots.append(
                        SlotOut(
                            starts_at=cursor,
                            doctor_name=doctor_name,
                            specialty_code=specialty_code or "general_medicine",
                            clinic_code=clinic_code,
                        )
                    )
                cursor += dt.timedelta(minutes=30)
        day += dt.timedelta(days=1)
    return slots


@router.post("/hold", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
async def hold_slot(
    body: HoldIn,
    session: AsyncSession = SessionDep,
    services: Services = ServicesDep,
) -> AppointmentOut:
    starts = body.starts_at
    if starts.tzinfo is None:
        starts = starts.replace(tzinfo=CLINIC_TZ)
    repo = AppointmentRepository(session)
    if await repo.has_conflict(
        doctor_name=body.doctor_name,
        clinic_code=body.clinic_code,
        starts_at=starts,
    ):
        raise HTTPException(status_code=409, detail="Slot already held or booked")
    appointment = await repo.create(
        patient_id=body.patient_id,
        clinic_code=body.clinic_code,
        doctor_name=body.doctor_name,
        specialty_code=body.specialty_code,
        starts_at=starts,
        duration_minutes=body.duration_minutes,
        traffic_class=body.traffic_class,
        status="held",
        source=body.source if body.source in {"assistant", "front_desk"} else "assistant",
    )
    from app.modules.scheduling.no_show_actions import score_and_act

    await score_and_act(
        session,
        appointment,
        services=services,
        actor_subject="system:assistant_booking",
    )
    await session.commit()
    return _out(appointment)


@router.post("/confirm", response_model=AppointmentOut)
async def confirm_booking(
    body: ConfirmIn,
    session: AsyncSession = SessionDep,
    services: Services = ServicesDep,
) -> AppointmentOut:
    repo = AppointmentRepository(session)
    appointment = await repo.get(body.appointment_id)
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appointment.status not in {"held", "confirmed"}:
        raise HTTPException(status_code=409, detail=f"Cannot confirm status={appointment.status}")
    await repo.update_status(appointment, "confirmed")
    from app.modules.scheduling.no_show_actions import score_and_act

    # Ensure waitlist handoff exists for assistant bookings confirmed after hold.
    await score_and_act(
        session,
        appointment,
        services=services,
        actor_subject="system:assistant_booking",
    )
    await session.commit()
    return _out(appointment)


@router.post("/cancel", response_model=AppointmentOut)
async def cancel_appointment(
    body: CancelIn,
    session: AsyncSession = SessionDep,
) -> AppointmentOut:
    repo = AppointmentRepository(session)
    appointment = await repo.get(body.appointment_id)
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appointment.status == "cancelled":
        return _out(appointment)
    if appointment.status not in {"held", "confirmed"}:
        raise HTTPException(status_code=409, detail=f"Cannot cancel status={appointment.status}")
    await repo.update_status(appointment, "cancelled")
    await session.commit()
    return _out(appointment)


@router.post("/reschedule", response_model=AppointmentOut)
async def reschedule_appointment(
    body: RescheduleIn,
    session: AsyncSession = SessionDep,
) -> AppointmentOut:
    repo = AppointmentRepository(session)
    appointment = await repo.get(body.appointment_id)
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appointment.status not in {"held", "confirmed"}:
        raise HTTPException(status_code=409, detail=f"Cannot reschedule status={appointment.status}")
    starts = body.starts_at
    if starts.tzinfo is None:
        starts = starts.replace(tzinfo=CLINIC_TZ)
    if await repo.has_conflict(
        doctor_name=appointment.doctor_name,
        clinic_code=appointment.clinic_code,
        starts_at=starts,
        exclude_id=appointment.id,
    ):
        raise HTTPException(status_code=409, detail="Target slot already held or booked")
    appointment.starts_at = starts
    if body.duration_minutes is not None:
        appointment.duration_minutes = body.duration_minutes
    await session.flush()
    await session.commit()
    return _out(appointment)


@router.get("/appointments/{appointment_id}", response_model=AppointmentOut)
async def get_appointment(
    appointment_id: uuid.UUID,
    session: AsyncSession = SessionDep,
) -> AppointmentOut:
    appointment = await AppointmentRepository(session).get(appointment_id)
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return _out(appointment)
