from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    kind: str
    title: str
    content_type: str
    size_bytes: int
    language: str
    status: str
    error_code: str | None
    page_count: int | None
    created_at: dt.datetime
    updated_at: dt.datetime


class DocumentCreateOut(BaseModel):
    document: DocumentOut
    queued: bool
    warning: str | None = None


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    page: int | None
    section: str | None
    content: str


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    patient_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    top_k: int = Field(default=5, ge=1, le=12)


class SearchHit(BaseModel):
    document_id: uuid.UUID
    document_title: str
    chunk_id: uuid.UUID
    chunk_index: int
    page: int | None
    snippet: str
    score: float
    source: dict[str, Any]


class SearchOut(BaseModel):
    query: str
    patient_id: uuid.UUID
    results: list[SearchHit]
    evidence_count: int
    engine: Literal["pgvector"] = "pgvector"


class AskRequest(SearchRequest):
    top_k: int = Field(default=6, ge=1, le=12)


class AskOut(BaseModel):
    question: str
    patient_id: uuid.UUID
    status: Literal["answered", "no_evidence", "model_unavailable"]
    answer: str
    sources: list[dict[str, Any]]
    evidence_count: int
    grounded: bool
    model_alias: str | None = None
    note: str | None = None


class MedicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    dose: str | None
    frequency: str | None
    status: str
    started_on: dt.datetime | None
    ended_on: dt.datetime | None
    source_document_id: uuid.UUID | None
