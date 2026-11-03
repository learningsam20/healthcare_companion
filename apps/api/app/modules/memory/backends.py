"""Pluggable durable non-clinical memory: Mem0 or first-party pgvector."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.mem0_client import Mem0Client, Mem0Unavailable
from app.modules.memory.policy import is_sensitive
from app.repositories.models import AgentMemory

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DurableHit:
    id: str
    text: str
    kind: str
    metadata: dict[str, Any] = field(default_factory=dict)


class DurableMemoryBackend(Protocol):
    async def add(
        self,
        *,
        subject: str,
        text: str,
        kind: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str | None: ...

    async def search(
        self,
        *,
        subject: str,
        query: str,
        limit: int = 5,
        session_id: str | None = None,
        kind: str | None = None,
    ) -> list[DurableHit]: ...

    async def delete_by_key(self, *, subject: str, key: str) -> None: ...

    async def purge_subject(self, *, subject: str) -> int: ...

    async def purge_session(self, *, subject: str, session_id: str) -> int: ...


class Mem0DurableBackend:
    def __init__(self, client: Mem0Client) -> None:
        self._client = client

    @property
    def configured(self) -> bool:
        return self._client.configured

    async def add(
        self,
        *,
        subject: str,
        text: str,
        kind: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        if not self._client.configured or is_sensitive(text):
            return None
        meta = {"kind": kind, "allowlisted": True, "source": "sahyog", **(metadata or {})}
        if session_id:
            meta["session_id"] = session_id
        try:
            result = await self._client.add(user_id=subject, text=text, metadata=meta)
        except Mem0Unavailable as exc:
            logger.warning(
                "mem0 add skipped",
                extra={"event": "memory.durable_add_failed", "extra_fields": {"reason": str(exc)}},
            )
            return None
        if isinstance(result, dict):
            return str(result.get("id") or result.get("memory_id") or "") or None
        return None

    async def search(
        self,
        *,
        subject: str,
        query: str,
        limit: int = 5,
        session_id: str | None = None,
        kind: str | None = None,
    ) -> list[DurableHit]:
        if not self._client.configured:
            return []
        try:
            rows = await self._client.search(user_id=subject, query=query, limit=max(limit * 3, 9))
        except Mem0Unavailable:
            return []
        hits: list[DurableHit] = []
        for row in rows:
            text = str(row.get("memory") or row.get("text") or "").strip()
            if not text or is_sensitive(text):
                continue
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            row_kind = str(meta.get("kind") or "preference")
            if kind and row_kind != kind:
                continue
            if session_id is not None and str(meta.get("session_id") or "") != session_id:
                continue
            mid = str(row.get("id") or row.get("memory_id") or text[:32])
            hits.append(DurableHit(id=mid, text=text, kind=row_kind, metadata=dict(meta)))
            if len(hits) >= limit:
                break
        return hits

    async def delete_by_key(self, *, subject: str, key: str) -> None:
        if not self._client.configured:
            return
        try:
            rows = await self._client.list_for_user(user_id=subject)
        except Mem0Unavailable:
            return
        for row in rows:
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            memory_id = str(row.get("id") or row.get("memory_id") or "")
            text = str(row.get("memory") or row.get("text") or "")
            matches = meta.get("key") == key or f"Preference {key}:" in text
            if memory_id and matches:
                try:
                    await self._client.delete(memory_id=memory_id)
                except Mem0Unavailable:
                    continue

    async def purge_subject(self, *, subject: str) -> int:
        if not self._client.configured:
            return 0
        deleted = 0
        try:
            rows = await self._client.list_for_user(user_id=subject)
        except Mem0Unavailable:
            return 0
        for row in rows:
            memory_id = str(row.get("id") or row.get("memory_id") or "")
            if not memory_id:
                continue
            try:
                await self._client.delete(memory_id=memory_id)
                deleted += 1
            except Mem0Unavailable:
                continue
        return deleted

    async def purge_session(self, *, subject: str, session_id: str) -> int:
        if not self._client.configured:
            return 0
        deleted = 0
        try:
            rows = await self._client.list_for_user(user_id=subject)
        except Mem0Unavailable:
            return 0
        for row in rows:
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            if str(meta.get("session_id") or "") != session_id:
                continue
            memory_id = str(row.get("id") or row.get("memory_id") or "")
            if not memory_id:
                continue
            try:
                await self._client.delete(memory_id=memory_id)
                deleted += 1
            except Mem0Unavailable:
                continue
        return deleted


class PgvectorDurableBackend:
    """First-party agent_memories table (non-clinical only)."""

    def __init__(self, session: AsyncSession, services: Any) -> None:
        self._session = session
        self._services = services

    async def _embed(self, text: str) -> list[float] | None:
        try:
            from app.modules.records.ingest import embed_query

            return await embed_query(self._services, text)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "agent memory embed failed",
                extra={"event": "memory.embed_failed", "extra_fields": {"reason": str(exc)}},
            )
            return None

    async def add(
        self,
        *,
        subject: str,
        text: str,
        kind: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        if is_sensitive(text):
            return None
        embedding = await self._embed(text)
        if embedding is None:
            return None
        sid = uuid.UUID(session_id) if session_id else None
        row = AgentMemory(
            subject=subject,
            session_id=sid,
            kind=kind,
            text=text[:2000],
            embedding=embedding,
            metadata_json=dict(metadata or {}),
        )
        self._session.add(row)
        await self._session.flush()
        return str(row.id)

    async def search(
        self,
        *,
        subject: str,
        query: str,
        limit: int = 5,
        session_id: str | None = None,
        kind: str | None = None,
    ) -> list[DurableHit]:
        embedding = await self._embed(query)
        if embedding is None:
            return []
        distance = AgentMemory.embedding.cosine_distance(embedding).label("distance")
        conditions = [AgentMemory.subject == subject]
        if kind:
            conditions.append(AgentMemory.kind == kind)
        if session_id:
            try:
                conditions.append(AgentMemory.session_id == uuid.UUID(session_id))
            except ValueError:
                return []
        rows = await self._session.execute(
            select(AgentMemory, distance)
            .where(*conditions)
            .order_by(distance)
            .limit(limit)
        )
        hits: list[DurableHit] = []
        for row, _score in rows:
            if is_sensitive(row.text):
                continue
            meta = dict(row.metadata_json or {})
            hits.append(
                DurableHit(id=str(row.id), text=row.text, kind=row.kind, metadata=meta)
            )
        return hits

    async def delete_by_key(self, *, subject: str, key: str) -> None:
        rows = await self._session.scalars(
            select(AgentMemory).where(
                AgentMemory.subject == subject,
                AgentMemory.kind == "preference",
            )
        )
        for row in rows:
            meta = row.metadata_json or {}
            if meta.get("key") == key or f"Preference {key}:" in row.text:
                await self._session.delete(row)

    async def purge_subject(self, *, subject: str) -> int:
        result = await self._session.execute(
            delete(AgentMemory).where(AgentMemory.subject == subject)
        )
        return int(result.rowcount or 0)

    async def purge_session(self, *, subject: str, session_id: str) -> int:
        try:
            sid = uuid.UUID(session_id)
        except ValueError:
            return 0
        result = await self._session.execute(
            delete(AgentMemory).where(
                AgentMemory.subject == subject,
                AgentMemory.session_id == sid,
            )
        )
        return int(result.rowcount or 0)
