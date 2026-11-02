from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import ChatRun


class ChatRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        session_id: uuid.UUID,
        owner_subject: str,
        graph: str,
        graph_version: str,
        status: str = "running",
        interrupt_type: str | None = None,
        interrupt_id: str | None = None,
        interrupt_payload: dict[str, Any] | None = None,
        checkpoint: dict[str, Any] | None = None,
        trace_id: str | None = None,
        result_message_id: uuid.UUID | None = None,
        error_code: str | None = None,
    ) -> ChatRun:
        run = ChatRun(
            session_id=session_id,
            owner_subject=owner_subject,
            graph=graph,
            graph_version=graph_version,
            status=status,
            interrupt_type=interrupt_type,
            interrupt_id=interrupt_id,
            interrupt_payload=interrupt_payload or {},
            checkpoint=checkpoint or {},
            trace_id=trace_id,
            result_message_id=result_message_id,
            error_code=error_code,
            ended_at=(
                dt.datetime.now(dt.UTC)
                if status in {"completed", "failed", "cancelled"}
                else None
            ),
        )
        self._session.add(run)
        await self._session.flush()
        return run

    async def get_owned(self, run_id: uuid.UUID, owner_subject: str) -> ChatRun | None:
        return await self._session.scalar(
            select(ChatRun).where(ChatRun.id == run_id, ChatRun.owner_subject == owner_subject)
        )

    async def get(self, run_id: uuid.UUID) -> ChatRun | None:
        return await self._session.get(ChatRun, run_id)

    async def cancel_active_runs(self, session_id: uuid.UUID) -> int:
        result = await self._session.execute(
            update(ChatRun)
            .where(
                ChatRun.session_id == session_id,
                ChatRun.status.in_(("running", "interrupted")),
            )
            .values(
                status="cancelled",
                ended_at=dt.datetime.now(dt.UTC),
                error_code="session_deleted",
            )
        )
        return int(result.rowcount or 0)

    async def active_interrupt(
        self, *, session_id: uuid.UUID, owner_subject: str
    ) -> ChatRun | None:
        return await self._session.scalar(
            select(ChatRun)
            .where(
                ChatRun.session_id == session_id,
                ChatRun.owner_subject == owner_subject,
                ChatRun.status == "interrupted",
            )
            .order_by(ChatRun.started_at.desc())
            .limit(1)
        )

    async def complete(
        self,
        run: ChatRun,
        *,
        status: str = "completed",
        result_message_id: uuid.UUID | None = None,
        error_code: str | None = None,
        checkpoint: dict[str, Any] | None = None,
    ) -> ChatRun:
        run.status = status
        run.ended_at = dt.datetime.now(dt.UTC)
        if result_message_id is not None:
            run.result_message_id = result_message_id
        if error_code is not None:
            run.error_code = error_code
        if checkpoint is not None:
            run.checkpoint = checkpoint
        await self._session.flush()
        return run

    async def mark_interrupted(
        self,
        run: ChatRun,
        *,
        graph: str,
        interrupt_type: str,
        interrupt_id: str,
        interrupt_payload: dict[str, Any],
        result_message_id: uuid.UUID | None = None,
        checkpoint: dict[str, Any] | None = None,
    ) -> ChatRun:
        run.graph = graph
        run.graph_version = graph
        run.status = "interrupted"
        run.ended_at = None
        run.interrupt_type = interrupt_type
        run.interrupt_id = interrupt_id
        run.interrupt_payload = interrupt_payload
        run.error_code = None
        if result_message_id is not None:
            run.result_message_id = result_message_id
        if checkpoint is not None:
            run.checkpoint = {**(run.checkpoint or {}), **checkpoint}
        await self._session.flush()
        return run

    async def reinterrupt(
        self,
        run: ChatRun,
        *,
        interrupt_type: str,
        interrupt_id: str,
        interrupt_payload: dict[str, Any],
        result_message_id: uuid.UUID | None = None,
        checkpoint: dict[str, Any] | None = None,
    ) -> ChatRun:
        run.status = "interrupted"
        run.ended_at = None
        run.interrupt_type = interrupt_type
        run.interrupt_id = interrupt_id
        run.interrupt_payload = interrupt_payload
        if result_message_id is not None:
            run.result_message_id = result_message_id
        if checkpoint is not None:
            run.checkpoint = {**(run.checkpoint or {}), **checkpoint}
        await self._session.flush()
        return run
