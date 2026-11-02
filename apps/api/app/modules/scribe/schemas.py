from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EncounterCreate(BaseModel):
    appointment_id: uuid.UUID | None = None
    patient_id: uuid.UUID | None = None
    kind: Literal["scheduled", "walk_in"] = "scheduled"
    doctor_name: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _identity(self) -> EncounterCreate:
        if self.kind == "scheduled" and self.appointment_id is None:
            raise ValueError("a scheduled encounter requires an appointment")
        if self.kind == "walk_in" and self.patient_id is None:
            raise ValueError("a walk-in encounter requires a patient")
        return self


class EncounterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    patient_display_name: str | None = None
    doctor_subject: str
    doctor_name: str
    clinic_code: str
    appointment_id: uuid.UUID | None
    kind: str
    status: str
    started_at: dt.datetime
    ended_at: dt.datetime | None
    latest_run_id: uuid.UUID | None = None
    latest_run_status: str | None = None
    note_id: uuid.UUID | None = None


class TranscriptTurnIn(BaseModel):
    speaker: Literal["doctor", "patient", "other"] = "other"
    start_ms: int = Field(default=0, ge=0, le=86_400_000)
    end_ms: int = Field(default=0, ge=0, le=86_400_000)
    text: str = Field(min_length=1, max_length=4000)
    language: str | None = Field(default=None, max_length=10)


class TranscriptCreate(BaseModel):
    language: str = Field(default="mixed", max_length=10)
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    turns: list[TranscriptTurnIn] = Field(min_length=1, max_length=400)


class TranscriptTurnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    turn_index: int
    speaker: str
    start_ms: int
    end_ms: int
    text: str
    language: str


class TranscriptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    encounter_id: uuid.UUID
    status: str
    source: str
    language: str
    duration_ms: int | None
    error_code: str | None
    audio_deleted_at: dt.datetime | None
    created_at: dt.datetime
    turns: list[TranscriptTurnOut] = Field(default_factory=list)


class AudioUploadRequest(BaseModel):
    content_type: Literal[
        "audio/webm", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/ogg"
    ]
    size_bytes: int = Field(ge=1, le=200_000_000)


class AudioUploadOut(BaseModel):
    transcript_id: uuid.UUID
    upload_url: str
    expires_in_seconds: int
    method: Literal["PUT"] = "PUT"


class ScribeRunCreate(BaseModel):
    transcript_id: uuid.UUID | None = None


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    field: str
    line_index: int
    source_type: str
    source_ref: dict[str, Any]
    status: str
    as_of: dt.datetime | None


class DraftOut(BaseModel):
    id: uuid.UUID
    revision: int
    schema_version: str
    content: dict[str, Any]
    created_at: dt.datetime


class ScribeRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    encounter_id: uuid.UUID
    transcript_id: uuid.UUID
    status: str
    revision: int
    model_alias: str | None
    error_code: str | None
    error_detail: str | None = None
    rejection_reason: str | None
    rejection_category: str | None
    red_flag_ids: list[str]
    trace_id: str | None = None
    started_at: dt.datetime
    completed_at: dt.datetime | None
    draft: DraftOut | None = None
    sources: list[SourceOut] = Field(default_factory=list)
    red_flags: list[dict[str, str]] = Field(default_factory=list)
    elapsed_seconds: int | None = None


class DraftEditRequest(BaseModel):
    content: dict[str, Any]


class RejectRequest(BaseModel):
    category: Literal[
        "wrong_content", "missing_content", "unsafe", "template", "transcription", "other"
    ]
    comment: str = Field(min_length=3, max_length=500)


class SignRequest(BaseModel):
    attestation: bool
    comment: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _attested(self) -> SignRequest:
        if not self.attestation:
            raise ValueError("explicit attestation is required to sign")
        return self


class SignatureOut(BaseModel):
    note_id: uuid.UUID
    version: int
    content_hash: str
    signed_at: dt.datetime
    stock_flags: list[dict[str, Any]] = Field(default_factory=list)
    patient_notified: bool


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    encounter_id: uuid.UUID
    patient_id: uuid.UUID
    patient_display_name: str | None = None
    author_subject: str
    status: str
    title: str
    language: str
    current_version: int
    signed_by: str
    signed_at: dt.datetime
    signed_hash: str
    content: dict[str, Any] | None = None
    sources: list[SourceOut] = Field(default_factory=list)
    metadata_only: bool = False


class NoteVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    content_hash: str
    parent_version: int | None
    signed_by: str
    signed_at: dt.datetime
    signature_ref: dict[str, Any]


class CorrectionRequest(BaseModel):
    content: dict[str, Any]
    reason: str = Field(min_length=5, max_length=300)


class StockReservationRequest(BaseModel):
    medicine_name: str = Field(min_length=1, max_length=200)
    sku: str | None = Field(default=None, max_length=80)
    clinic_code: str = Field(min_length=2, max_length=40)
    quantity: int = Field(ge=1, le=10_000)


class StockReservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    note_id: uuid.UUID
    medicine_name: str
    sku: str | None
    clinic_code: str
    quantity: int
    status: str
    reserved_by_subject: str
    created_at: dt.datetime
