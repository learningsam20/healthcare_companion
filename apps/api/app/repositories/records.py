from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, cast

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import (
    ChatMessage,
    Document,
    DocumentChunk,
    Medication,
    NoteSource,
    ScribeSource,
)

SORT_COLUMNS = {
    "created_at": Document.created_at,
    "title": Document.title,
    "status": Document.status,
    "updated_at": Document.updated_at,
}


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_grid(
        self,
        *,
        patient_id: uuid.UUID | None,
        query: str | None,
        status: str | None,
        kind: str | None,
        sort: str,
        descending: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Document], int]:
        conditions = []
        if patient_id is not None:
            conditions.append(Document.patient_id == patient_id)
        if query:
            pattern = f"%{query.strip()}%"
            conditions.append(or_(Document.title.ilike(pattern), Document.kind.ilike(pattern)))
        if status:
            conditions.append(Document.status == status)
        if kind:
            conditions.append(Document.kind == kind)
        column = SORT_COLUMNS.get(sort, Document.created_at)
        order = column.desc() if descending else column.asc()
        total = await self._session.scalar(
            select(func.count()).select_from(Document).where(*conditions)
        )
        rows = await self._session.scalars(
            select(Document)
            .where(*conditions)
            .order_by(order, Document.id)
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)

    async def get(self, document_id: uuid.UUID) -> Document | None:
        return await self._session.get(Document, document_id)

    async def create(self, document: Document) -> Document:
        self._session.add(document)
        await self._session.flush()
        return document

    async def delete(self, document: Document) -> None:
        await self._session.delete(document)
        await self._session.flush()

    async def scrub_citations(self, document_id: uuid.UUID) -> dict[str, int]:
        marker = [{"metadata": {"document_id": str(document_id)}}]
        counts = {"chat_messages": 0, "note_sources": 0, "scribe_sources": 0}

        messages = await self._session.scalars(
            select(ChatMessage).where(ChatMessage.sources.contains(marker))
        )
        for message in messages:
            sources = list(message.sources or [])
            kept = [
                source
                for source in sources
                if str((source.get("metadata") or {}).get("document_id")) != str(document_id)
            ]
            if len(kept) != len(sources):
                message.sources = kept
                counts["chat_messages"] += 1

        notes = await self._session.scalars(
            select(NoteSource).where(
                NoteSource.source_ref.op("->>")("document_id") == str(document_id)
            )
        )
        for source in notes:
            source.status = "missing"
            source.source_ref = {"redacted": True, "reason": "document_deleted"}
            counts["note_sources"] += 1

        scribe = await self._session.scalars(
            select(ScribeSource).where(
                ScribeSource.source_ref.op("->>")("document_id") == str(document_id)
            )
        )
        for source in scribe:
            source.status = "missing"
            source.source_ref = {"redacted": True, "reason": "document_deleted"}
            counts["scribe_sources"] += 1

        await self._session.flush()
        return counts

    async def set_status(
        self,
        document: Document,
        status: str,
        *,
        error_code: str | None = None,
        page_count: int | None = None,
    ) -> None:
        document.status = status
        document.error_code = error_code
        if page_count is not None:
            document.page_count = page_count
        document.updated_at = dt.datetime.now(dt.UTC)
        await self._session.flush()

    async def replace_chunks(self, document: Document, chunks: list[DocumentChunk]) -> None:
        existing = await self._session.scalars(
            select(DocumentChunk).where(DocumentChunk.document_id == document.id)
        )
        for row in existing:
            await self._session.delete(row)
        self._session.add_all(chunks)
        await self._session.flush()

    async def list_chunks(
        self, *, document_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[DocumentChunk], int]:
        total = await self._session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
        )
        rows = await self._session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)

    async def get_chunk(self, chunk_id: uuid.UUID) -> DocumentChunk | None:
        return await self._session.get(DocumentChunk, chunk_id)

    async def chunk_count(self, document_id: uuid.UUID) -> int:
        total = await self._session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
        )
        return int(total or 0)

    async def search(
        self,
        *,
        patient_id: uuid.UUID,
        embedding: list[float],
        limit: int,
        document_id: uuid.UUID | None = None,
        query_text: str | None = None,
        query_terms: list[str] | None = None,
    ) -> list[tuple[DocumentChunk, Document, float]]:
        """Hybrid retrieval: vector cosine + lexical/trigram candidates, fused with RRF."""
        distance = DocumentChunk.embedding.cosine_distance(embedding).label("distance")
        conditions = [
            DocumentChunk.patient_id == patient_id,
            Document.status == "indexed",
            DocumentChunk.retrieval_allowed.is_(True),
        ]
        if document_id is not None:
            conditions.append(DocumentChunk.document_id == document_id)
        vector_rows = await self._session.execute(
            select(DocumentChunk, Document, distance)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(*conditions)
            .order_by(distance)
            .limit(max(limit * 2, 12))
        )
        vector_hits = [
            (cast(DocumentChunk, chunk), cast(Document, document), cast(float, score))
            for chunk, document, score in vector_rows
        ]

        terms = [t.strip() for t in (query_terms or []) if t and t.strip()]
        if query_text and query_text.strip() and query_text.strip() not in terms:
            terms = [query_text.strip(), *terms]
        if not terms:
            return vector_hits[:limit]

        lexical_clauses = []
        for term in terms[:16]:
            pattern = f"%{term}%"
            lexical_clauses.append(DocumentChunk.content.ilike(pattern))
            lexical_clauses.append(Document.title.ilike(pattern))
            # pg_trgm similarity (extension enabled in 0001); soft-fail if unavailable.
            lexical_clauses.append(func.similarity(DocumentChunk.content, term) > 0.25)
            lexical_clauses.append(func.similarity(Document.title, term) > 0.3)

        primary = terms[0]
        trigram_score = func.greatest(
            func.similarity(DocumentChunk.content, primary),
            func.similarity(Document.title, primary),
        ).label("trigram_score")
        try:
            lexical_rows = await self._session.execute(
                select(DocumentChunk, Document, trigram_score)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(*conditions, or_(*lexical_clauses))
                .order_by(trigram_score.desc())
                .limit(max(limit * 2, 12))
            )
            lexical_hits = [
                (cast(DocumentChunk, chunk), cast(Document, document), cast(float, score))
                for chunk, document, score in lexical_rows
            ]
        except Exception:  # noqa: BLE001 — fall back to vector-only if trgm/SQL fails
            return vector_hits[:limit]

        return _rrf_fuse(vector_hits, lexical_hits, limit=limit)

    async def list_medications(
        self,
        *,
        patient_id: uuid.UUID,
        query: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Medication], int]:
        conditions = [Medication.patient_id == patient_id]
        if query:
            needle = f"%{query.strip()}%"
            conditions.append(
                or_(
                    Medication.name.ilike(needle),
                    Medication.dose.ilike(needle),
                    Medication.frequency.ilike(needle),
                    Medication.instructions.ilike(needle),
                )
            )
        if status:
            conditions.append(Medication.status == status)
        total = await self._session.scalar(
            select(func.count()).select_from(Medication).where(*conditions)
        )
        rows = await self._session.scalars(
            select(Medication)
            .where(*conditions)
            .order_by(Medication.name)
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)

    async def medications_for_patient(self, patient_id: uuid.UUID) -> list[Medication]:
        rows = await self._session.scalars(
            select(Medication)
            .where(Medication.patient_id == patient_id, Medication.status == "active")
            .order_by(Medication.name)
        )
        return list(rows)


def _rrf_fuse(
    vector_hits: list[tuple[DocumentChunk, Document, float]],
    lexical_hits: list[tuple[DocumentChunk, Document, float]],
    *,
    limit: int,
    k: int = 60,
) -> list[tuple[DocumentChunk, Document, float]]:
    scores: dict[uuid.UUID, float] = {}
    payloads: dict[uuid.UUID, tuple[DocumentChunk, Document]] = {}
    for rank, (chunk, document, _score) in enumerate(vector_hits, start=1):
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (k + rank)
        payloads[chunk.id] = (chunk, document)
    for rank, (chunk, document, _score) in enumerate(lexical_hits, start=1):
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (k + rank)
        payloads[chunk.id] = (chunk, document)
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    fused: list[tuple[DocumentChunk, Document, float]] = []
    for chunk_id, rrf in ordered[:limit]:
        chunk, document = payloads[chunk_id]
        # Lower is better for callers that treat the third value as distance-like;
        # invert RRF so ranking remains ascending when sorted later.
        fused.append((chunk, document, 1.0 / (rrf + 1e-9)))
    return fused


def chunk_source_ref(chunk: DocumentChunk, document: Document) -> dict[str, Any]:
    return {
        "id": str(chunk.id),
        "type": "document",
        "title": document.title,
        "locator": f"{document.id}#chunk={chunk.chunk_index}",
        "patient_id": str(document.patient_id),
        "snippet": chunk.content[:280],
        "metadata": {"document_id": str(document.id), "page": str(chunk.page or "")},
    }
