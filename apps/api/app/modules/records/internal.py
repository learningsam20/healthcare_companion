"""Internal records endpoints for MCP tools (key-auth, no JWT)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.internal_auth import require_internal_api_key
from app.core.services import Services, get_services
from app.modules.records.ingest import embed_query
from app.repositories.records import DocumentRepository

router = APIRouter(
    prefix="/api/v1/internal/records",
    tags=["internal-records"],
    dependencies=[Depends(require_internal_api_key)],
)

SessionDep = Depends(get_session)
ServicesDep = Depends(get_services)


class DocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    document_type: str | None = None
    created_at: str | None = None


class SearchHit(BaseModel):
    document_id: uuid.UUID
    document_title: str
    chunk_id: uuid.UUID
    page: int | None = None
    snippet: str
    score: float


class SearchIn(BaseModel):
    patient_id: uuid.UUID
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=6, ge=1, le=20)
    document_id: uuid.UUID | None = None


class ChunkOut(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    page: int | None
    content: str


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    patient_id: uuid.UUID = Query(...),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = SessionDep,
) -> list[DocumentOut]:
    docs, _ = await DocumentRepository(session).list_grid(
        patient_id=patient_id,
        query=None,
        status=None,
        kind=None,
        sort="created_at",
        descending=True,
        limit=limit,
        offset=0,
    )
    return [
        DocumentOut(
            id=d.id,
            title=d.title,
            status=d.status,
            document_type=getattr(d, "kind", None),
            created_at=d.created_at.isoformat() if getattr(d, "created_at", None) else None,
        )
        for d in docs
    ]


@router.get("/documents/{document_id}/status")
async def get_document_status(
    document_id: uuid.UUID,
    session: AsyncSession = SessionDep,
) -> dict[str, object]:
    document = await DocumentRepository(session).get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": str(document.id),
        "title": document.title,
        "status": document.status,
        "patient_id": str(document.patient_id) if document.patient_id else None,
    }


@router.post("/search", response_model=list[SearchHit])
async def search_records(
    body: SearchIn,
    services: Services = ServicesDep,
    session: AsyncSession = SessionDep,
) -> list[SearchHit]:
    from app.core.rls import set_patient_rls

    try:
        embedding = await embed_query(services, body.query)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Embedding unavailable: {exc}") from exc
    await set_patient_rls(session, body.patient_id)
    rows = await DocumentRepository(session).search(
        patient_id=body.patient_id,
        embedding=embedding,
        limit=body.top_k,
        document_id=body.document_id,
    )
    hits: list[SearchHit] = []
    for chunk, document, distance in rows:
        hits.append(
            SearchHit(
                document_id=document.id,
                document_title=document.title,
                chunk_id=chunk.id,
                page=chunk.page,
                snippet=chunk.content[:400],
                score=round(1.0 - float(distance), 4),
            )
        )
    return hits


@router.get("/chunks/{chunk_id}", response_model=ChunkOut)
async def get_document_chunk(
    chunk_id: uuid.UUID,
    session: AsyncSession = SessionDep,
) -> ChunkOut:
    chunk = await DocumentRepository(session).get_chunk(chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="Chunk not found")
    document = await DocumentRepository(session).get(chunk.document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return ChunkOut(
        chunk_id=chunk.id,
        document_id=document.id,
        document_title=document.title,
        page=chunk.page,
        content=chunk.content[:4000],
    )


@router.get("/medications")
async def list_medications(
    patient_id: uuid.UUID = Query(...),
    session: AsyncSession = SessionDep,
) -> dict[str, object]:
    meds = await DocumentRepository(session).medications_for_patient(patient_id)
    return {
        "patient_id": str(patient_id),
        "source": "medications_table",
        "medications": [
            {
                "id": str(m.id),
                "name": m.name,
                "status": m.status,
                "dose": getattr(m, "dose", None),
                "frequency": getattr(m, "frequency", None),
            }
            for m in meds
        ],
    }
