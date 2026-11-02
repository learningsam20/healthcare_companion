from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import DataDeletionRequest


class DataDeletionRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest_open(self, patient_id: uuid.UUID) -> DataDeletionRequest | None:
        return await self._session.scalar(
            select(DataDeletionRequest)
            .where(
                DataDeletionRequest.patient_id == patient_id,
                DataDeletionRequest.status.in_(("pending", "processing")),
            )
            .order_by(DataDeletionRequest.requested_at.desc())
            .limit(1)
        )

    async def due(
        self, *, now: dt.datetime, limit: int = 20
    ) -> list[DataDeletionRequest]:
        rows = await self._session.scalars(
            select(DataDeletionRequest)
            .where(
                DataDeletionRequest.status == "pending",
                DataDeletionRequest.scheduled_for <= now,
            )
            .order_by(DataDeletionRequest.scheduled_for)
            .limit(limit)
        )
        return list(rows)

    async def create(self, request: DataDeletionRequest) -> DataDeletionRequest:
        self._session.add(request)
        await self._session.flush()
        return request
