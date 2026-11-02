from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import FhirPatientLink


class FhirLinkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, patient_id: uuid.UUID) -> FhirPatientLink | None:
        return await self._session.get(FhirPatientLink, patient_id)

    async def upsert(
        self,
        *,
        patient_id: uuid.UUID,
        fhir_patient_id: str,
        system: str = "fhir",
    ) -> FhirPatientLink:
        row = await self.get(patient_id)
        if row is None:
            row = FhirPatientLink(
                patient_id=patient_id,
                fhir_patient_id=fhir_patient_id,
                system=system,
            )
            self._session.add(row)
        else:
            row.fhir_patient_id = fhir_patient_id
            row.system = system
        await self._session.flush()
        return row

    async def list_links(self, *, limit: int = 100) -> list[FhirPatientLink]:
        result = await self._session.execute(
            select(FhirPatientLink).order_by(FhirPatientLink.updated_at.desc()).limit(limit)
        )
        return list(result.scalars())
