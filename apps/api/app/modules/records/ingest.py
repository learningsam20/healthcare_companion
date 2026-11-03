"""Document ingestion: object storage to extracted text, chunks and embeddings.

No extracted text is logged. Failures record a stable error code only, so logs, traces
and analytics never carry clinical content or identifiers.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from app.agents.llm_gateway import LlmGateway
from app.core.services import Services
from app.core.storage import StorageError
from app.modules.records.injection_scan import quarantine_decision, scan_text
from app.repositories.audit import AuditRepository
from app.repositories.models import Document, DocumentChunk
from app.repositories.records import DocumentRepository
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CHUNK_CHARS = 1100
CHUNK_OVERLAP = 150
MAX_CHUNKS = 4000
EMBED_BATCH = 16


class IngestError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class TextChunk:
    index: int
    page: int | None
    content: str


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract_pages(data: bytes, content_type: str) -> list[tuple[int | None, str]]:
    if content_type == "application/pdf":
        try:
            reader = PdfReader(io.BytesIO(data))
            pages: list[tuple[int | None, str]] = [
                (index + 1, page.extract_text() or "") for index, page in enumerate(reader.pages)
            ]
        except Exception as exc:
            raise IngestError("pdf_unreadable") from exc
        if not any(text.strip() for _, text in pages):
            raise IngestError("no_extractable_text")
        return pages
    if content_type in {"image/png", "image/jpeg"}:
        raise IngestError("ocr_not_configured")
    raise IngestError("unsupported_content_type")


def _normalize(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def chunk_pages(pages: list[tuple[int | None, str]]) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    index = 0
    for page_number, raw in pages:
        text = _normalize(raw)
        if not text:
            continue
        start = 0
        while start < len(text):
            piece = text[start : start + CHUNK_CHARS].strip()
            if len(piece) >= 20:
                chunks.append(TextChunk(index=index, page=page_number, content=piece))
                index += 1
                if index >= MAX_CHUNKS:
                    raise IngestError("document_too_large")
            if start + CHUNK_CHARS >= len(text):
                break
            start += CHUNK_CHARS - CHUNK_OVERLAP
    if not chunks:
        raise IngestError("no_extractable_text")
    return chunks


async def ingest_document(services: Services, document_id: uuid.UUID) -> str:
    async with services.db.sessionmaker() as session:
        repo = DocumentRepository(session)
        document = await repo.get(document_id)
        if document is None:
            return "not_found"
        if document.status == "quarantined" or document.scan_status == "infected":
            return "quarantined"
        if document.status == "indexed":
            return "indexed"
        await repo.set_status(document, "processing", error_code=None)
        await session.commit()
        try:
            data = await services.storage.get(key=document.object_key)
            pages = extract_pages(data, document.content_type)
            specs = chunk_pages(pages)
            gateway = LlmGateway(services.settings, services.models_config)
            embeddings: list[list[float]] = []
            for offset in range(0, len(specs), EMBED_BATCH):
                batch = specs[offset : offset + EMBED_BATCH]
                vectors = await gateway.embed(texts=[item.content for item in batch])
                embeddings.extend(vectors)
            quarantined_chunks = 0
            injection_patterns: list[str] = []
            rows: list[DocumentChunk] = []
            for spec, vector in zip(specs, embeddings, strict=True):
                hits = scan_text(spec.content)
                allowed, tag = quarantine_decision(hits)
                if not allowed:
                    quarantined_chunks += 1
                    injection_patterns.extend(hit.pattern_id for hit in hits)
                rows.append(
                    DocumentChunk(
                        document_id=document.id,
                        patient_id=document.patient_id,
                        chunk_index=spec.index,
                        page=spec.page,
                        content=spec.content,
                        embedding=vector,
                        quarantine_tag=tag,
                        retrieval_allowed=allowed,
                    )
                )
            await repo.replace_chunks(document, rows)
            # Document stays askable for clean chunks; fully-injected docs get quarantined.
            if quarantined_chunks and quarantined_chunks == len(rows):
                await repo.set_status(
                    document, "quarantined", error_code="prompt_injection", page_count=len(pages)
                )
                status_action = "records.document_quarantined"
            else:
                await repo.set_status(document, "indexed", error_code=None, page_count=len(pages))
                status_action = "records.document_indexed"
            AuditRepository(session).append(
                actor_subject="system:ingestion",
                actor_role="service",
                action=status_action,
                resource_type="document",
                resource_id=str(document.id),
                patient_id=document.patient_id,
                metadata={
                    "chunks": len(rows),
                    "pages": len(pages),
                    "content_type": document.content_type,
                    "quarantined_chunks": quarantined_chunks,
                    "injection_patterns": sorted(set(injection_patterns))[:12],
                },
            )
            if document.status == "indexed":
                await _notify_document_ready(services, session, document)
                await _post_chat_indexed_notice(session, document)
            await session.commit()
            logger.info(
                "document ingestion finished",
                extra={
                    "event": f"records.document.{document.status}",
                    "extra_fields": {
                        "chunks": len(rows),
                        "pages": len(pages),
                        "quarantined_chunks": quarantined_chunks,
                    },
                },
            )
            return document.status
        except IngestError as exc:
            await _fail(session, repo, document, exc.code)
            return exc.code
        except StorageError:
            await _fail(session, repo, document, "storage_unavailable")
            return "storage_unavailable"
        except Exception:
            logger.exception(
                "document ingestion failed",
                extra={"event": "records.document.failed"},
            )
            await _fail(session, repo, document, "ingestion_failed")
            return "ingestion_failed"


def _document_kind(content_type: str | None) -> str:
    """Readable file kind. Never the filename or title (those can identify a person)."""
    subtype = (content_type or "document").split("/")[-1].split(";")[0].strip().lower()[:40]
    labels = {
        "pdf": "PDF",
        "png": "Image",
        "jpeg": "Image",
        "jpg": "Image",
        "webp": "Image",
        "gif": "Image",
        "tiff": "Image",
        "plain": "Text file",
        "csv": "Spreadsheet",
        "json": "Data file",
    }
    if subtype in labels:
        return labels[subtype]
    if subtype.isascii() and subtype.isalnum() and len(subtype) <= 8:
        return subtype.upper()
    return "Document"


async def _notify_document_ready(services: Services, session: AsyncSession, document: Document) -> None:
    """Best-effort in-app notice when a report becomes askable (G-50)."""
    try:
        from app.modules.notifications.service import NotificationService

        await NotificationService(services, session).send(
            template_id="document_ready",
            recipient_subject=document.uploaded_by_subject,
            recipient_role="patient",
            patient_id=document.patient_id,
            locale=document.language or "en-IN",
            data={
                # Never put document.title in outbound copy (may contain identifiers).
                "document_kind": _document_kind(document.content_type),
            },
            actor_subject="system:ingestion",
            actor_role="service",
            requested_channels=["in_app", "email"],
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "document_ready notify skipped",
            extra={"event": "records.document_ready_notify_failed"},
        )


async def _post_chat_indexed_notice(session: AsyncSession, document: Document) -> None:
    """Append a system line to the uploader's most recent chat for this patient."""
    try:
        from sqlalchemy import select

        from app.repositories.models import ChatMessage, ChatSession

        chat = await session.scalar(
            select(ChatSession)
            .where(
                ChatSession.owner_subject == document.uploaded_by_subject,
                ChatSession.patient_id == document.patient_id,
                ChatSession.status == "active",
            )
            .order_by(ChatSession.updated_at.desc())
            .limit(1)
        )
        if chat is None:
            return
        session.add(
            ChatMessage(
                session_id=chat.id,
                role="system",
                content=(
                    f"Report indexed: **{document.title}** "
                    f"(`{document.id}`). You can ask questions about it in chat or Records."
                ),
                language=document.language or "en-IN",
                sources=[],
                safety={"document_indexed": True, "document_id": str(document.id)},
            )
        )
        chat.updated_at = dt.datetime.now(dt.UTC)
        await session.flush()
    except Exception:  # noqa: BLE001
        logger.warning(
            "chat indexed notice skipped",
            extra={"event": "records.chat_indexed_notice_failed"},
        )


async def _fail(
    session: AsyncSession, repo: DocumentRepository, document: Document, code: str
) -> None:
    await repo.set_status(document, "failed", error_code=code)
    AuditRepository(session).append(
        actor_subject="system:ingestion",
        actor_role="service",
        action="records.document_failed",
        resource_type="document",
        resource_id=str(document.id),
        patient_id=document.patient_id,
        metadata={"error_code": code},
    )
    await session.commit()
    logger.warning(
        "document ingestion failed",
        extra={"event": "records.document.failed", "extra_fields": {"error_code": code}},
    )


async def ingest_document_job(ctx: dict[str, Any], document_id: str) -> str:
    return await ingest_document(ctx["services"], uuid.UUID(document_id))


async def embed_query(services: Services, text: str) -> list[float]:
    gateway = LlmGateway(services.settings, services.models_config)
    vectors = await gateway.embed(texts=[text])
    return vectors[0]
