from __future__ import annotations

import datetime as dt
import logging
import math
import uuid
from typing import Annotated, Any, Literal

from app.agents.llm_gateway import LlmGateway, LlmGatewayError
from app.core.db import get_session
from app.core.pagination import GridMeta
from app.core.queue import enqueue
from app.core.security import AuthContext, Role, get_auth_context
from app.core.services import Services, get_services
from app.core.storage import StorageError
from app.modules.records.ingest import checksum, embed_query, ingest_document
from app.modules.records.schemas import (
    AskOut,
    AskRequest,
    ChunkOut,
    DocumentCreateOut,
    DocumentOut,
    MedicationOut,
    SearchHit,
    SearchOut,
    SearchRequest,
)
from app.modules.records.scope import resolve_patient
from app.repositories.audit import AuditRepository
from app.repositories.models import Document
from app.repositories.records import DocumentRepository
from app.repositories.usage import UsageRepository
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sahyog_common.errors import ProblemError
from sahyog_common.provenance import SourceRef, SourceType, resolve_sources
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/records", tags=["records"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ContextDep = Annotated[AuthContext, Depends(get_auth_context)]
ServicesDep = Annotated[Services, Depends(get_services)]

NO_EVIDENCE = {
    "en": (
        "I could not find this in the records available to me. "
        "Please ask your care team rather than relying on a guess."
    ),
    "hi": ("मुझे उपलब्ध रिकॉर्ड में यह जानकारी नहीं मिली। कृपया अनुमान लगाने के बजाय अपनी देखभाल टीम से पूछें।"),
    "mr": ("मला उपलब्ध नोंदींमध्ये ही माहिती सापडली नाही. कृपया अंदाज न लावता तुमच्या काळजी पथकाला विचारा."),
}
MODEL_UNAVAILABLE = {
    "en": "Records were found, but the answer model is unavailable. The excerpts are shown.",
    "hi": "रिकॉर्ड मिले, लेकिन उत्तर मॉडल उपलब्ध नहीं है। अंश नीचे दिखाए गए हैं।",
    "mr": "नोंदी सापडल्या, पण उत्तर मॉडेल उपलब्ध नाही. उतारे खाली दाखवले आहेत.",
}


def _trace(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _document_out(document: Document) -> DocumentOut:
    return DocumentOut.model_validate(document)


def _source(chunk: Any, document: Document) -> SourceRef:
    return SourceRef(
        id=str(chunk.id),
        type=SourceType.DOCUMENT,
        title=document.title,
        locator=f"{document.id}#chunk={chunk.chunk_index}",
        patient_id=document.patient_id,
        snippet=chunk.content[:280],
        metadata={
            "document_id": str(document.id),
            "page": str(chunk.page or ""),
            "chunk_index": str(chunk.chunk_index),
        },
    )


def _localized(copy: dict[str, str], locale: str) -> str:
    return copy.get(locale.split("-")[0], copy["en"])


async def _check_document_scope(
    *,
    document_id: uuid.UUID,
    context: AuthContext,
    session: AsyncSession,
    services: Services,
) -> Document:
    document = await DocumentRepository(session).get(document_id)
    if document is None:
        raise ProblemError(404, "document_not_found", "Not found", "No such document.")
    scoped = await resolve_patient(
        context,
        session,
        document.patient_id,
        allow_all_for_admin=True,
    )
    if scoped is not None and scoped != document.patient_id:
        raise ProblemError(404, "document_not_found", "Not found", "No such document.")
    return document


@router.get("/documents")
async def list_documents(
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
    patient_id: Annotated[uuid.UUID | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    doc_status: Annotated[str | None, Query(alias="status", max_length=20)] = None,
    kind: Annotated[str | None, Query(max_length=40)] = None,
    sort: Annotated[str, Query(max_length=20)] = "created_at",
    order: Annotated[Literal["asc", "desc"], Query()] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    scoped = await resolve_patient(context, session, patient_id, allow_all_for_admin=True)
    items, total = await DocumentRepository(session).list_grid(
        patient_id=scoped,
        query=q,
        status=doc_status,
        kind=kind,
        sort=sort,
        descending=order == "desc",
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="records.documents_listed",
        resource_type="document",
        patient_id=scoped,
        consent_id=context.consent_id,
        trace_id=_trace(request),
        metadata={"count": total, "page": page},
    )
    await session.commit()
    return {
        "items": [_document_out(item).model_dump(mode="json") for item in items],
        "meta": GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort=sort,
            order=order,
            pages=math.ceil(total / page_size) if total else 0,
        ).model_dump(),
    }


@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    background: BackgroundTasks,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=2, max_length=200)],
    kind: Annotated[str, Form(max_length=40)] = "other",
    patient_id: Annotated[uuid.UUID | None, Form()] = None,
    language: Annotated[str, Form(max_length=10)] = "en-IN",
) -> DocumentCreateOut:
    scoped = await resolve_patient(context, session, patient_id)
    if scoped is None:
        raise ProblemError(
            400, "patient_required", "Patient required", "Select a patient for this document."
        )
    uploads = services.app_config.get("uploads", {})
    allowed = set(uploads.get("allowed_document_types", []))
    content_type = file.content_type or "application/octet-stream"
    if content_type not in allowed:
        raise ProblemError(
            415,
            "unsupported_document_type",
            "Unsupported file",
            "Upload a PDF or image document.",
        )
    limit = int(uploads.get("max_document_mb", 25)) * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise ProblemError(
            413, "document_too_large", "File too large", "The document exceeds the size limit."
        )
    if not data:
        raise ProblemError(400, "empty_document", "Empty file", "The document is empty.")
    if language not in {"en-IN", "hi-IN", "mr-IN"}:
        language = "en-IN"
    document_id = uuid.uuid4()
    object_key = f"documents/{scoped}/{document_id}"
    verdict = await services.malware.scan(data)
    if verdict.infected:
        quarantine_key = f"quarantine/{scoped}/{document_id}"
        await services.storage.put(key=quarantine_key, data=data, content_type=content_type)
        document = Document(
            id=document_id,
            patient_id=scoped,
            uploaded_by_subject=context.subject,
            kind=kind,
            title=title,
            object_key=quarantine_key,
            content_type=content_type,
            size_bytes=len(data),
            checksum_sha256=checksum(data),
            language=language,
            status="quarantined",
            error_code="malware_detected",
            scan_status="infected",
            scan_engine=verdict.engine,
            scan_engine_version=verdict.engine_version,
            scanned_at=dt.datetime.now(dt.UTC),
            quarantine_key=quarantine_key,
            traffic_class=context.traffic_class,
        )
        await DocumentRepository(session).create(document)
        AuditRepository(session).append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="records.document_quarantined",
            resource_type="document",
            resource_id=str(document.id),
            patient_id=scoped,
            consent_id=context.consent_id,
            trace_id=_trace(request),
            metadata={
                "scan_status": "infected",
                "scan_engine": verdict.engine,
                "signature": verdict.signature or "unknown",
                "size_bytes": len(data),
            },
        )
        await session.commit()
        raise ProblemError(
            422,
            "malware_detected",
            "File quarantined",
            "The file failed the malware scan and was quarantined. "
            "Contact the clinic if this is unexpected.",
        )
    if verdict.status == "unavailable" and services.malware.required:
        AuditRepository(session).append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="records.upload_blocked",
            resource_type="document",
            resource_id=str(document_id),
            patient_id=scoped,
            consent_id=context.consent_id,
            trace_id=_trace(request),
            metadata={"reason": "malware_scan_unavailable", "scan_engine": verdict.engine},
        )
        await session.commit()
        raise ProblemError(
            503,
            "malware_scan_unavailable",
            "Scan unavailable",
            "The malware scanner is unavailable, so the file was not accepted. Try again shortly.",
        )
    try:
        await services.storage.put(key=object_key, data=data, content_type=content_type)
    except Exception as exc:
        logger.warning(
            "document storage unavailable", extra={"event": "records.storage.unavailable"}
        )
        raise ProblemError(
            503,
            "storage_unavailable",
            "Storage unavailable",
            "The document store is unavailable. Try again shortly.",
        ) from exc
    document = Document(
        id=document_id,
        patient_id=scoped,
        uploaded_by_subject=context.subject,
        kind=kind,
        title=title,
        object_key=object_key,
        content_type=content_type,
        size_bytes=len(data),
        checksum_sha256=checksum(data),
        language=language,
        status="queued",
        scan_status=verdict.status,
        scan_engine=verdict.engine,
        scan_engine_version=verdict.engine_version,
        scanned_at=dt.datetime.now(dt.UTC) if verdict.status != "unavailable" else None,
        traffic_class=context.traffic_class,
    )
    await DocumentRepository(session).create(document)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="records.document_uploaded",
        resource_type="document",
        resource_id=str(document.id),
        patient_id=scoped,
        consent_id=context.consent_id,
        trace_id=_trace(request),
        metadata={
            "kind": kind,
            "content_type": content_type,
            "size_bytes": len(data),
            "scan_status": verdict.status,
            "scan_engine": verdict.engine,
        },
    )
    await session.commit()

    queued = True
    warning: str | None = None
    if verdict.status == "unavailable":
        warning = (
            "Malware scanning is unavailable; the file was accepted under advisory policy. "
            "Escalate this to the security owner."
        )
    elif verdict.status == "disabled":
        warning = "Malware scanning is disabled in this environment."
    try:
        await enqueue(
            services.settings.redis_url,
            "ingest_document_job",
            str(document.id),
            queue_name=services.settings.arq_worker_queue,
        )
    except Exception:
        logger.warning(
            "ingestion queue unavailable; using in-process task",
            extra={"event": "records.queue.unavailable"},
        )
        background.add_task(ingest_document, services, document.id)
        warning = "The job queue is unavailable; ingestion is running in-process."
    return DocumentCreateOut(document=_document_out(document), queued=queued, warning=warning)


@router.get("/documents/{document_id}")
async def get_document(
    document_id: uuid.UUID,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> DocumentOut:
    document = await _check_document_scope(
        document_id=document_id, context=context, session=session, services=services
    )
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="records.document_viewed",
        resource_type="document",
        resource_id=str(document.id),
        patient_id=document.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
    )
    await session.commit()
    return _document_out(document)


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: uuid.UUID,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> dict[str, Any]:
    document = await _check_document_scope(
        document_id=document_id, context=context, session=session, services=services
    )
    if not services.settings.s3_configured:
        raise ProblemError(
            503,
            "storage_unavailable",
            "Storage unavailable",
            "Document storage is not configured, so the original file cannot be downloaded.",
        )
    try:
        url = await services.storage.presign_get(key=document.object_key, expires_seconds=300)
    except StorageError as exc:
        logger.warning(
            "document download presign failed",
            extra={"event": "records.document_download.storage_failed"},
        )
        raise ProblemError(
            503,
            "storage_unavailable",
            "Storage unavailable",
            "The document store is unavailable. Try again shortly.",
        ) from exc
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="records.document_downloaded",
        resource_type="document",
        resource_id=str(document.id),
        patient_id=document.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
    )
    await session.commit()
    return {"url": url, "expires_in": 300}


def _content_filename(title: str, content_type: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    stem = "".join(char if char in allowed else "_" for char in title).strip("._") or "document"
    stem = stem[:80]
    lowered = stem.lower()
    if content_type == "application/pdf" and not lowered.endswith(".pdf"):
        return f"{stem}.pdf"
    if content_type == "image/png" and not lowered.endswith(".png"):
        return f"{stem}.png"
    if content_type in {"image/jpeg", "image/jpg"} and not lowered.endswith((".jpg", ".jpeg")):
        return f"{stem}.jpg"
    return stem


@router.get("/documents/{document_id}/content")
async def document_content(
    document_id: uuid.UUID,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> Response:
    """Stream the original file through the API so the browser can show it inline.

    A presigned object-store URL often points at a host the browser cannot reach.
    """
    document = await _check_document_scope(
        document_id=document_id, context=context, session=session, services=services
    )
    if not services.settings.s3_configured:
        raise ProblemError(
            503,
            "storage_unavailable",
            "Storage unavailable",
            "Document storage is not configured, so the original file cannot be opened.",
        )
    try:
        data = await services.storage.get(key=document.object_key)
    except StorageError as exc:
        logger.warning(
            "document content read failed",
            extra={"event": "records.document_content.storage_failed"},
        )
        raise ProblemError(
            503,
            "storage_unavailable",
            "Storage unavailable",
            "The document store is unavailable. Try again shortly.",
        ) from exc
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="records.document_downloaded",
        resource_type="document",
        resource_id=str(document.id),
        patient_id=document.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
    )
    await session.commit()
    filename = _content_filename(document.title, document.content_type)
    return Response(
        content=data,
        media_type=document.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> Response:
    if context.primary_role not in {Role.PATIENT, Role.ADMIN, Role.COMPLIANCE}:
        raise ProblemError(
            403,
            "forbidden",
            "Access denied",
            "Only the patient, an administrator or compliance can delete a document.",
        )
    document = await _check_document_scope(
        document_id=document_id, context=context, session=session, services=services
    )
    keys = {key for key in (document.object_key, document.quarantine_key) if key}
    deleted_objects = 0
    if services.settings.s3_configured:
        for key in keys:
            try:
                await services.storage.delete(key=key)
            except StorageError as exc:
                logger.warning(
                    "document object delete failed",
                    extra={"event": "records.document_delete.storage_failed"},
                )
                raise ProblemError(
                    503,
                    "storage_unavailable",
                    "Storage unavailable",
                    "The document store is unavailable, so the document was not deleted. "
                    "Try again shortly.",
                ) from exc
            deleted_objects += 1
    repo = DocumentRepository(session)
    chunk_count = await repo.chunk_count(document.id)
    citations = await repo.scrub_citations(document.id)
    title = document.title
    patient_id = document.patient_id
    await repo.delete(document)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="records.document_deleted",
        resource_type="document",
        resource_id=str(document_id),
        patient_id=patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
        metadata={
            "title": title,
            "objects_deleted": deleted_objects,
            "chunks_deleted": chunk_count,
            "citations_scrubbed": citations,
        },
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/documents/{document_id}/ingest", status_code=status.HTTP_202_ACCEPTED)
async def retry_ingest(
    document_id: uuid.UUID,
    background: BackgroundTasks,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> DocumentCreateOut:
    document = await _check_document_scope(
        document_id=document_id, context=context, session=session, services=services
    )
    if document.status == "quarantined" or document.scan_status == "infected":
        raise ProblemError(
            409,
            "document_quarantined",
            "Quarantined",
            "A quarantined file cannot be processed or retried.",
        )
    if document.status == "processing":
        raise ProblemError(
            409, "already_processing", "Already processing", "Ingestion is already running."
        )
    document.status = "queued"
    document.error_code = None
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="records.document_reingest_requested",
        resource_type="document",
        resource_id=str(document.id),
        patient_id=document.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
    )
    await session.commit()
    warning = None
    try:
        await enqueue(
            services.settings.redis_url,
            "ingest_document_job",
            str(document.id),
            queue_name=services.settings.arq_worker_queue,
        )
    except Exception:
        background.add_task(ingest_document, services, document.id)
        warning = "The job queue is unavailable; ingestion is running in-process."
    return DocumentCreateOut(document=_document_out(document), queued=True, warning=warning)


@router.get("/documents/{document_id}/chunks")
async def list_chunks(
    document_id: uuid.UUID,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    document = await _check_document_scope(
        document_id=document_id, context=context, session=session, services=services
    )
    chunks, total = await DocumentRepository(session).list_chunks(
        document_id=document.id, limit=page_size, offset=(page - 1) * page_size
    )
    return {
        "items": [ChunkOut.model_validate(chunk).model_dump(mode="json") for chunk in chunks],
        "meta": GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort="chunk_index",
            order="asc",
            pages=math.ceil(total / page_size) if total else 0,
        ).model_dump(),
    }


@router.post("/search")
async def search_records(
    body: SearchRequest,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> SearchOut:
    scoped = await resolve_patient(context, session, body.patient_id)
    assert scoped is not None
    from app.core.rls import set_patient_rls

    await set_patient_rls(session, scoped)
    embedding = await embed_query(services, body.query)
    rows = await DocumentRepository(session).search(
        patient_id=scoped,
        embedding=embedding,
        limit=body.top_k,
        document_id=body.document_id,
    )
    hits = []
    for chunk, document, distance in rows:
        source = _source(chunk, document)
        hits.append(
            SearchHit(
                document_id=document.id,
                document_title=document.title,
                chunk_id=chunk.id,
                chunk_index=chunk.chunk_index,
                page=chunk.page,
                snippet=chunk.content[:400],
                score=round(1.0 - distance, 4),
                source=source.model_dump(mode="json"),
            )
        )
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="records.search",
        resource_type="patient_records",
        resource_id=str(scoped),
        patient_id=scoped,
        consent_id=context.consent_id,
        trace_id=_trace(request),
        metadata={"results": len(hits), "top_k": body.top_k},
    )
    await session.commit()
    return SearchOut(
        query=body.query,
        patient_id=scoped,
        results=hits,
        evidence_count=len(hits),
    )


@router.post("/ask")
async def ask_records(
    body: AskRequest,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> AskOut:
    scoped = await resolve_patient(context, session, body.patient_id)
    assert scoped is not None
    from app.core.rls import set_patient_rls

    await set_patient_rls(session, scoped)
    embedding = await embed_query(services, body.query)
    rows = await DocumentRepository(session).search(
        patient_id=scoped,
        embedding=embedding,
        limit=body.top_k,
        document_id=body.document_id,
    )
    audit = AuditRepository(session)
    if not rows:
        audit.append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="records.answer_no_evidence",
            resource_type="patient_records",
            resource_id=str(scoped),
            patient_id=scoped,
            consent_id=context.consent_id,
            trace_id=_trace(request),
        )
        await session.commit()
        return AskOut(
            question=body.query,
            patient_id=scoped,
            status="no_evidence",
            answer=_localized(NO_EVIDENCE, context.locale),
            sources=[],
            evidence_count=0,
            grounded=True,
        )

    sources = resolve_sources(
        [_source(chunk, document) for chunk, document, _ in rows],
        current_patient_id=scoped,
    )
    excerpts = "\n\n".join(
        f"[{chunk.id}] {document.title} (page {chunk.page or 'n/a'}):\n{chunk.content}"
        for chunk, document, _ in rows
    )
    prompt = services.prompts["records_answer"]
    messages = [
        {"role": "system", "content": str(prompt.get("system", ""))},
        {
            "role": "user",
            "content": (
                f"Language: {context.locale}\n"
                f"Question: {body.query}\n\n"
                f"Patient-scoped record excerpts:\n{excerpts}"
            ),
        },
    ]
    gateway = LlmGateway(services.settings, services.models_config)
    try:
        result = await gateway.complete(
            purpose="rag_answer",
            messages=messages,
            max_tokens=800,
            temperature=0.1,
            trace_id=_trace(request),
        )
    except LlmGatewayError:
        logger.warning(
            "records answer model unavailable",
            extra={"event": "records.answer.model_unavailable"},
        )
        audit.append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="records.answer_model_unavailable",
            resource_type="patient_records",
            resource_id=str(scoped),
            patient_id=scoped,
            consent_id=context.consent_id,
            trace_id=_trace(request),
        )
        await session.commit()
        return AskOut(
            question=body.query,
            patient_id=scoped,
            status="model_unavailable",
            answer=_localized(MODEL_UNAVAILABLE, context.locale),
            sources=[ref.model_dump(mode="json") for ref in sources],
            evidence_count=len(sources),
            grounded=True,
        )

    await UsageRepository(session).record(
        purpose="rag_answer",
        model_alias=result.model_alias,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        cost_usd=services.model_cost(
            result.model_alias, result.prompt_tokens, result.completion_tokens
        ),
        trace_id=_trace(request),
        session_id=None,
        traffic_class=context.traffic_class,
        gateway_request_id=result.gateway_request_id,
    )
    audit.append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="records.answered",
        resource_type="patient_records",
        resource_id=str(scoped),
        patient_id=scoped,
        consent_id=context.consent_id,
        trace_id=_trace(request),
        metadata={
            "evidence": len(sources),
            "model_alias": result.model_alias,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
        },
    )
    await session.commit()
    return AskOut(
        question=body.query,
        patient_id=scoped,
        status="answered",
        answer=result.content,
        sources=[ref.model_dump(mode="json") for ref in sources],
        evidence_count=len(sources),
        grounded=True,
        model_alias=result.model_alias,
        note="Answered only from patient-scoped records, using a local model route.",
    )


@router.get("/medications")
async def list_medications(
    context: ContextDep,
    session: SessionDep,
    patient_id: Annotated[uuid.UUID | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    med_status: Annotated[str | None, Query(alias="status", max_length=20)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    scoped = await resolve_patient(context, session, patient_id)
    assert scoped is not None
    rows, total = await DocumentRepository(session).list_medications(
        patient_id=scoped,
        query=q,
        status=med_status,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return {
        "items": [MedicationOut.model_validate(row).model_dump(mode="json") for row in rows],
        "meta": GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort="name",
            order="asc",
            pages=math.ceil(total / page_size) if total else 0,
        ).model_dump(),
    }
