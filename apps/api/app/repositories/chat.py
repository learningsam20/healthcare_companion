from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence

from sahyog_common.provenance import SourceRef
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import ChatMessage, ChatSession

SORT_COLUMNS = {
    "updated_at": ChatSession.updated_at,
    "created_at": ChatSession.created_at,
    "title": ChatSession.title,
}


class ChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_sessions(
        self,
        *,
        owner_subject: str,
        query: str | None,
        sort: str,
        descending: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[ChatSession], int]:
        column = SORT_COLUMNS.get(sort, ChatSession.updated_at)
        order = column.desc() if descending else column.asc()
        conditions = [
            ChatSession.owner_subject == owner_subject,
            ChatSession.status != "deleted",
        ]
        if query:
            pattern = f"%{query.strip()}%"
            conditions.append(or_(ChatSession.title.ilike(pattern)))
        total = await self._session.scalar(
            select(func.count()).select_from(ChatSession).where(*conditions)
        )
        rows = await self._session.scalars(
            select(ChatSession)
            .where(*conditions)
            .order_by(order, ChatSession.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)

    async def count_for_owner(self, owner_subject: str) -> int:
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(ChatSession)
                .where(
                    ChatSession.owner_subject == owner_subject,
                    ChatSession.status != "deleted",
                )
            )
            or 0
        )

    async def create_session(
        self,
        *,
        owner_subject: str,
        owner_role: str,
        patient_id: uuid.UUID | None,
        title: str,
        locale: str,
        traffic_class: str,
        title_source: str = "system",
    ) -> ChatSession:
        from app.agents.session_title import is_placeholder_title

        source = title_source
        if source not in {"system", "user"}:
            source = "system"
        if not is_placeholder_title(title):
            source = "user"
        chat = ChatSession(
            owner_subject=owner_subject,
            owner_role=owner_role,
            patient_id=patient_id,
            title=title,
            title_source=source,
            locale=locale,
            traffic_class=traffic_class,
        )
        self._session.add(chat)
        await self._session.flush()
        return chat

    async def get_owned(self, session_id: uuid.UUID, owner_subject: str) -> ChatSession | None:
        return await self._session.scalar(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.owner_subject == owner_subject,
                ChatSession.status != "deleted",
            )
        )

    async def soft_delete(self, chat: ChatSession, when: dt.datetime | None = None) -> None:
        chat.status = "deleted"
        chat.deleted_at = when or dt.datetime.now(dt.UTC)
        await self._session.flush()

    async def list_messages(self, session_id: uuid.UUID, limit: int = 200) -> list[ChatMessage]:
        rows = await self._session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            .limit(limit)
        )
        return list(rows)

    async def add_message(
        self,
        *,
        session_id: uuid.UUID,
        role: str,
        content: str,
        language: str,
        sources: Sequence[SourceRef] | None = None,
        safety: dict | None = None,
        trace_id: str | None = None,
        model_alias: str | None = None,
    ) -> ChatMessage:
        message = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            language=language,
            sources=[ref.model_dump(mode="json") for ref in sources or ()],
            safety=dict(safety or {}),
            trace_id=trace_id,
            model_alias=model_alias,
        )
        self._session.add(message)
        await self._session.flush()
        return message

    async def touch(self, chat: ChatSession) -> None:
        chat.updated_at = dt.datetime.now(dt.UTC)
        await self._session.flush()

    async def get_message_owned(
        self, message_id: uuid.UUID, owner_subject: str
    ) -> ChatMessage | None:
        return await self._session.scalar(
            select(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(
                ChatMessage.id == message_id,
                ChatSession.owner_subject == owner_subject,
                ChatSession.status != "deleted",
            )
        )

    async def previous_user_message(
        self, *, session_id: uuid.UUID, before_message_id: uuid.UUID | None
    ) -> ChatMessage | None:
        conditions = [
            ChatMessage.session_id == session_id,
            ChatMessage.role == "user",
        ]
        if before_message_id is not None:
            anchor = await self._session.get(ChatMessage, before_message_id)
            if anchor is not None:
                conditions.append(ChatMessage.created_at <= anchor.created_at)
        return await self._session.scalar(
            select(ChatMessage)
            .where(*conditions)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(1)
        )
