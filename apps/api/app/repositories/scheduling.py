from __future__ import annotations

import datetime as dt
import re
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import Appointment, BookingIdempotency, Patient

CLINIC_TZ = ZoneInfo("Asia/Kolkata")

SORT_COLUMNS = {
    "starts_at": Appointment.starts_at,
    "doctor_name": Appointment.doctor_name,
    "clinic_code": Appointment.clinic_code,
    "status": Appointment.status,
    "created_at": Appointment.created_at,
}

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y")


def parse_schedule_query_date(raw: str) -> dt.date | None:
    """Parse a full-date search token (ISO or common Indian day-first forms)."""
    text = (raw or "").strip()
    if not text or len(text) < 8:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # Allow "4 Nov 2026" / "04 November 2026" style without locale deps.
    match = re.fullmatch(
        r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})",
        text,
    )
    if match:
        day_s, month_s, year_s = match.groups()
        for fmt in ("%d %b %Y", "%d %B %Y"):
            try:
                return dt.datetime.strptime(
                    f"{int(day_s):02d} {month_s.title()} {year_s}", fmt
                ).date()
            except ValueError:
                continue
    return None


class AppointmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_grid(
        self,
        *,
        query: str | None,
        status: str | None,
        specialty: str | None,
        clinic: str | None,
        patient_id: uuid.UUID | None,
        clinic_scope: tuple[str, ...],
        starts_after: dt.datetime | None,
        starts_before: dt.datetime | None,
        sort: str,
        descending: bool,
        limit: int,
        offset: int,
        source: str | None = None,
        doctor_name: str | None = None,
    ) -> tuple[list[Appointment], int]:
        conditions = []
        if patient_id is not None:
            conditions.append(Appointment.patient_id == patient_id)
        if clinic_scope:
            conditions.append(Appointment.clinic_code.in_(clinic_scope))
        if doctor_name:
            conditions.append(Appointment.doctor_name == doctor_name)
        if status:
            conditions.append(Appointment.status == status)
        if specialty:
            conditions.append(Appointment.specialty_code == specialty)
        if clinic:
            conditions.append(Appointment.clinic_code == clinic)
        if source in {"assistant", "front_desk"}:
            conditions.append(Appointment.source == source)
        if starts_after:
            conditions.append(Appointment.starts_at >= starts_after)
        if starts_before:
            conditions.append(Appointment.starts_at <= starts_before)
        if query:
            needle = query.strip()
            pattern = f"%{needle}%"
            text_match = or_(
                Appointment.doctor_name.ilike(pattern),
                Appointment.clinic_code.ilike(pattern),
                Appointment.specialty_code.ilike(pattern),
                Patient.display_name.ilike(pattern),
            )
            day = parse_schedule_query_date(needle)
            if day is not None:
                day_start = dt.datetime.combine(day, dt.time.min, tzinfo=CLINIC_TZ)
                day_end = dt.datetime.combine(day, dt.time.max, tzinfo=CLINIC_TZ)
                conditions.append(
                    or_(
                        text_match,
                        and_(
                            Appointment.starts_at >= day_start,
                            Appointment.starts_at <= day_end,
                        ),
                    )
                )
            else:
                conditions.append(text_match)
        column = SORT_COLUMNS.get(sort, Appointment.starts_at)
        order = column.desc() if descending else column.asc()
        base = (
            select(Appointment)
            .outerjoin(Patient, Patient.id == Appointment.patient_id)
            .where(*conditions)
        )
        total = await self._session.scalar(
            select(func.count(func.distinct(Appointment.id)))
            .select_from(Appointment)
            .outerjoin(Patient, Patient.id == Appointment.patient_id)
            .where(*conditions)
        )
        rows = await self._session.scalars(
            base.order_by(order, Appointment.id.asc()).limit(limit).offset(offset)
        )
        return list(rows), int(total or 0)

    async def get(self, appointment_id: uuid.UUID) -> Appointment | None:
        return await self._session.get(Appointment, appointment_id)

    async def patient_names(
        self, patient_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, str | None]:
        if not patient_ids:
            return {}
        rows = await self._session.scalars(select(Patient).where(Patient.id.in_(patient_ids)))
        return {row.id: row.display_name for row in rows}

    async def visit_kinds(self, appointments: list[Appointment]) -> dict[uuid.UUID, str]:
        """first = no earlier held/confirmed/completed visit with same doctor; else repeat."""
        keyed = [row for row in appointments if row.patient_id is not None]
        if not keyed:
            return {row.id: "unknown" for row in appointments}
        patient_ids = {row.patient_id for row in keyed if row.patient_id is not None}
        doctor_names = {row.doctor_name for row in keyed}
        history = list(
            await self._session.scalars(
                select(Appointment).where(
                    Appointment.patient_id.in_(patient_ids),
                    Appointment.doctor_name.in_(doctor_names),
                    Appointment.status.in_(("held", "confirmed", "completed")),
                )
            )
        )
        result: dict[uuid.UUID, str] = {}
        for row in appointments:
            if row.patient_id is None:
                result[row.id] = "unknown"
                continue
            earlier = any(
                prior.patient_id == row.patient_id
                and prior.doctor_name == row.doctor_name
                and prior.id != row.id
                and prior.starts_at < row.starts_at
                for prior in history
            )
            result[row.id] = "repeat" if earlier else "first"
        return result

    async def has_conflict(
        self,
        *,
        doctor_name: str,
        clinic_code: str,
        starts_at: dt.datetime,
        exclude_id: uuid.UUID | None = None,
    ) -> bool:
        conditions = [
            Appointment.doctor_name == doctor_name,
            Appointment.clinic_code == clinic_code,
            Appointment.starts_at == starts_at,
            Appointment.status.in_(("held", "confirmed")),
        ]
        if exclude_id is not None:
            conditions.append(Appointment.id != exclude_id)
        found = await self._session.scalar(select(Appointment.id).where(*conditions).limit(1))
        return found is not None

    async def create(
        self,
        *,
        patient_id: uuid.UUID | None,
        clinic_code: str,
        doctor_name: str,
        specialty_code: str,
        starts_at: dt.datetime,
        duration_minutes: int,
        traffic_class: str,
        status: str = "confirmed",
        source: str = "front_desk",
    ) -> Appointment:
        appointment = Appointment(
            patient_id=patient_id,
            clinic_code=clinic_code,
            doctor_name=doctor_name,
            specialty_code=specialty_code,
            starts_at=starts_at,
            duration_minutes=duration_minutes,
            status=status,
            traffic_class=traffic_class,
            source=source if source in {"assistant", "front_desk"} else "front_desk",
        )
        self._session.add(appointment)
        await self._session.flush()
        return appointment

    async def update_status(self, appointment: Appointment, status: str) -> Appointment:
        appointment.status = status
        await self._session.flush()
        return appointment

    async def doctors(
        self,
        *,
        query: str | None,
        specialty: str | None,
        clinic: str | None,
        clinic_scope: tuple[str, ...] = (),
        doctor_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, object]], int]:
        conditions: list[ColumnElement[bool]] = [
            Appointment.status.in_(("held", "confirmed", "completed"))
        ]
        if clinic_scope:
            conditions.append(Appointment.clinic_code.in_(clinic_scope))
        if doctor_name:
            conditions.append(Appointment.doctor_name == doctor_name)
        if specialty:
            conditions.append(Appointment.specialty_code == specialty)
        if clinic:
            conditions.append(Appointment.clinic_code == clinic)
        if query:
            pattern = f"%{query.strip()}%"
            conditions.append(
                or_(
                    Appointment.doctor_name.ilike(pattern),
                    Appointment.specialty_code.ilike(pattern),
                    Appointment.clinic_code.ilike(pattern),
                )
            )
        base = (
            select(
                Appointment.doctor_name,
                Appointment.specialty_code,
                Appointment.clinic_code,
                func.count(Appointment.id),
                func.max(Appointment.starts_at),
            )
            .where(*conditions)
            .group_by(
                Appointment.doctor_name,
                Appointment.specialty_code,
                Appointment.clinic_code,
            )
        )
        total = int(
            await self._session.scalar(select(func.count()).select_from(base.subquery())) or 0
        )
        rows = await self._session.execute(
            base.order_by(Appointment.doctor_name.asc()).limit(limit).offset(offset)
        )
        return (
            [
                {
                    "doctor_name": row[0],
                    "specialty_code": row[1],
                    "clinic_code": row[2],
                    "appointments": int(row[3]),
                    "last_seen_at": row[4],
                }
                for row in rows
            ],
            total,
        )

    async def booked_starts(
        self,
        *,
        doctor_name: str,
        clinic_code: str,
        start: dt.datetime,
        end: dt.datetime,
    ) -> set[dt.datetime]:
        rows = await self._session.scalars(
            select(Appointment.starts_at).where(
                Appointment.doctor_name == doctor_name,
                Appointment.clinic_code == clinic_code,
                Appointment.starts_at >= start,
                Appointment.starts_at < end,
                Appointment.status.in_(("held", "confirmed")),
            )
        )
        return set(rows)

    async def get_idempotent(
        self, *, scope: str, key: str
    ) -> Appointment | None:
        row = await self._session.get(BookingIdempotency, (scope, key))
        if row is None:
            return None
        return await self._session.get(Appointment, row.appointment_id)

    async def remember_idempotent(
        self, *, scope: str, key: str, appointment_id: uuid.UUID
    ) -> None:
        existing = await self._session.get(BookingIdempotency, (scope, key))
        if existing is not None:
            return
        self._session.add(
            BookingIdempotency(scope=scope, key=key, appointment_id=appointment_id)
        )
        await self._session.flush()
