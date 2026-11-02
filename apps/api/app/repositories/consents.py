from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.repositories.models import Consent, Patient

SORT_COLUMNS = {
    "granted_at": Consent.granted_at,
    "expires_at": Consent.expires_at,
    "status": Consent.status,
    "created_at": Consent.created_at,
}


def _active_filter(now: dt.datetime) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    return (
        Consent.status == "active",
        or_(Consent.expires_at.is_(None), Consent.expires_at > now),
    )


class ConsentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, consent_id: uuid.UUID) -> Consent | None:
        return await self._session.get(Consent, consent_id)

    async def active_for_subject(
        self,
        *,
        consent_id: uuid.UUID,
        caregiver_subject: str,
        now: dt.datetime | None = None,
    ) -> Consent | None:
        current = now or dt.datetime.now(dt.UTC)
        return await self._session.scalar(
            select(Consent).where(
                Consent.id == consent_id,
                Consent.caregiver_subject == caregiver_subject,
                *_active_filter(current),
            )
        )

    async def latest_active_for_patient(
        self,
        *,
        caregiver_subject: str,
        patient_id: uuid.UUID,
        scope: str | None = None,
        now: dt.datetime | None = None,
    ) -> Consent | None:
        current = now or dt.datetime.now(dt.UTC)
        rows = await self._session.scalars(
            select(Consent)
            .where(
                Consent.caregiver_subject == caregiver_subject,
                Consent.patient_id == patient_id,
                *_active_filter(current),
            )
            .order_by(Consent.granted_at.desc())
            .limit(5)
        )
        for row in rows:
            if scope is None or scope in (row.scopes or []):
                return row
        return None

    async def list_grid(
        self,
        *,
        patient_id: uuid.UUID | None,
        caregiver_subject: str | None,
        status: str | None,
        query: str | None,
        sort: str,
        descending: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[tuple[Consent, str | None]], int]:
        conditions = []
        if patient_id is not None:
            conditions.append(Consent.patient_id == patient_id)
        if caregiver_subject is not None:
            conditions.append(Consent.caregiver_subject == caregiver_subject)
        if status:
            conditions.append(Consent.status == status)
        if query:
            pattern = f"%{query.strip()}%"
            conditions.append(
                or_(
                    Consent.caregiver_subject.ilike(pattern),
                    Consent.purpose.ilike(pattern),
                    Patient.display_name.ilike(pattern),
                )
            )
        base = select(Consent, Patient.display_name).join(Patient, Patient.id == Consent.patient_id)
        total = await self._session.scalar(
            select(func.count())
            .select_from(Consent)
            .join(Patient, Patient.id == Consent.patient_id)
            .where(*conditions)
        )
        column = SORT_COLUMNS.get(sort, Consent.granted_at)
        order = column.desc() if descending else column.asc()
        rows = await self._session.execute(
            base.where(*conditions).order_by(order, Consent.id).limit(limit).offset(offset)
        )
        return [(row[0], row[1]) for row in rows], int(total or 0)

    async def active_contexts(
        self,
        *,
        caregiver_subject: str,
        now: dt.datetime | None = None,
    ) -> list[tuple[Consent, str | None]]:
        current = now or dt.datetime.now(dt.UTC)
        rows = await self._session.execute(
            select(Consent, Patient.display_name)
            .join(Patient, Patient.id == Consent.patient_id)
            .where(
                Consent.caregiver_subject == caregiver_subject,
                *_active_filter(current),
            )
            .order_by(Consent.granted_at.desc())
        )
        return [(row[0], row[1]) for row in rows]

    async def active_for_pair(
        self,
        *,
        patient_id: uuid.UUID,
        caregiver_subject: str,
        now: dt.datetime | None = None,
    ) -> Consent | None:
        current = now or dt.datetime.now(dt.UTC)
        return await self._session.scalar(
            select(Consent).where(
                Consent.patient_id == patient_id,
                Consent.caregiver_subject == caregiver_subject,
                *_active_filter(current),
            )
        )

    async def create(self, consent: Consent) -> Consent:
        self._session.add(consent)
        await self._session.flush()
        return consent

    async def revoke(self, consent: Consent, *, now: dt.datetime | None = None) -> None:
        consent.status = "revoked"
        consent.revoked_at = now or dt.datetime.now(dt.UTC)
        await self._session.flush()
