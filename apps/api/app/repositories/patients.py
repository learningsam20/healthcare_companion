from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import Consent, Patient

SORT_COLUMNS = {
    "display_name": Patient.display_name,
    "created_at": Patient.created_at,
    "locale": Patient.locale,
}


class PatientRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists(self, patient_id: uuid.UUID, *, include_deleted: bool = False) -> bool:
        conditions = [Patient.id == patient_id]
        if not include_deleted:
            conditions.append(Patient.deleted_at.is_(None))
        return bool(await self._session.scalar(select(Patient.id).where(*conditions)))

    async def get(self, patient_id: uuid.UUID) -> Patient | None:
        return await self._session.get(Patient, patient_id)

    async def list_grid(
        self,
        *,
        query: str | None,
        sort: str,
        descending: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Patient], int]:
        conditions = []
        if query:
            pattern = f"%{query.strip()}%"
            conditions.append(
                or_(
                    Patient.display_name.ilike(pattern),
                    Patient.keycloak_subject.ilike(pattern),
                )
            )
        total = await self._session.scalar(
            select(func.count()).select_from(Patient).where(*conditions)
        )
        column = SORT_COLUMNS.get(sort, Patient.display_name)
        rows = await self._session.scalars(
            select(Patient)
            .where(*conditions)
            .order_by(column.desc() if descending else column.asc(), Patient.id)
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)

    async def active_consent(
        self,
        *,
        caregiver_subject: str,
        patient_id: uuid.UUID,
        scope: str,
        consent_id: uuid.UUID | None = None,
        now: dt.datetime | None = None,
    ) -> bool:
        current = now or dt.datetime.now(dt.UTC)
        conditions = [
            Consent.caregiver_subject == caregiver_subject,
            Consent.patient_id == patient_id,
            Consent.status == "active",
        ]
        if consent_id is not None:
            conditions.append(Consent.id == consent_id)
        rows = await self._session.scalars(select(Consent).where(*conditions))
        for row in rows:
            if row.expires_at is not None and row.expires_at <= current:
                continue
            if scope in (row.scopes or []):
                return True
        return False
