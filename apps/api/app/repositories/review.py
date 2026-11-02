from __future__ import annotations

import uuid

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import Patient, ReviewTask

SORT_COLUMNS = {
    "created_at": ReviewTask.created_at,
    "due_at": ReviewTask.due_at,
    "status": ReviewTask.status,
    "assigned_role": ReviewTask.assigned_role,
}


class ReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, task: ReviewTask) -> ReviewTask:
        self._session.add(task)
        await self._session.flush()
        return task

    async def get(self, task_id: uuid.UUID, *, lock: bool = False) -> ReviewTask | None:
        if lock:
            return await self._session.scalar(
                select(ReviewTask).where(ReviewTask.id == task_id).with_for_update()
            )
        return await self._session.get(ReviewTask, task_id)

    async def list_grid(
        self,
        *,
        status: str | None,
        assigned_role: str | None,
        owner_subject: str | None,
        query: str | None,
        sort: str,
        descending: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[tuple[ReviewTask, str | None]], int]:
        conditions = []
        if status:
            conditions.append(ReviewTask.status == status)
        if assigned_role:
            conditions.append(ReviewTask.assigned_role == assigned_role)
        if owner_subject:
            conditions.append(ReviewTask.owner_subject == owner_subject)
        if query:
            pattern = f"%{query.strip()}%"
            conditions.append(
                or_(
                    ReviewTask.reason.ilike(pattern),
                    Patient.display_name.ilike(pattern),
                    cast(ReviewTask.id, String).ilike(pattern),
                    ReviewTask.resource_id.ilike(pattern),
                )
            )
        join = select(ReviewTask, Patient.display_name).outerjoin(
            Patient, Patient.id == ReviewTask.patient_id
        )
        total = await self._session.scalar(
            select(func.count())
            .select_from(ReviewTask)
            .outerjoin(Patient, Patient.id == ReviewTask.patient_id)
            .where(*conditions)
        )
        column = SORT_COLUMNS.get(sort, ReviewTask.created_at)
        rows = await self._session.execute(
            join.where(*conditions)
            .order_by(column.desc() if descending else column.asc(), ReviewTask.id)
            .limit(limit)
            .offset(offset)
        )
        return [(row[0], row[1]) for row in rows], int(total or 0)
