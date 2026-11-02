from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sahyog_common.provenance import SourceRef


class SessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    locale: Literal["en-IN", "hi-IN", "mr-IN"] | None = None


class SessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    title_source: str = "system"
    locale: str
    status: str
    created_at: dt.datetime
    updated_at: dt.datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    language: str
    sources: list[SourceRef]
    safety: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None
    model_alias: str | None
    created_at: dt.datetime


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    language: Literal["en-IN", "hi-IN", "mr-IN"] | None = None


class RedFlagOut(BaseModel):
    rule_ids: list[str]
    severity: str
    guidance: str


class InterruptOut(BaseModel):
    run_id: uuid.UUID
    interrupt_id: str
    interrupt_type: str
    payload: dict[str, Any]


class HeldAppointmentOut(BaseModel):
    """Soft-held slot returned when resume uses confirm=false (hold countdown UX)."""

    id: uuid.UUID
    doctor_name: str
    clinic_code: str
    specialty_code: str
    starts_at: dt.datetime
    duration_minutes: int
    status: str
    source: str = "assistant"
    hold_expires_at: dt.datetime


class SendResult(BaseModel):
    user_message: MessageOut
    assistant_message: MessageOut
    red_flag: RedFlagOut | None = None
    run_id: uuid.UUID | None = None
    interrupt: InterruptOut | None = None
    appointment: HeldAppointmentOut | None = None


class ResumeRequest(BaseModel):
    interrupt_id: str = Field(min_length=8, max_length=64)
    command: Literal[
        "slot_choice", "doctor_choice", "specialty_choice", "language_choice", "cancel"
    ] = "slot_choice"
    choice_index: int | None = Field(default=None, ge=1, le=10)
    doctor_name: str | None = Field(default=None, max_length=120)
    clinic_code: str | None = Field(default=None, max_length=40)
    specialty_code: str | None = Field(default=None, max_length=40)
    locale: str | None = Field(default=None, max_length=10)
    starts_at: dt.datetime | None = None
    confirm: bool = True
    idempotency_key: str | None = Field(default=None, max_length=80)


class ChatRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    graph: str
    graph_version: str
    status: str
    interrupt_type: str | None
    interrupt_id: str | None
    interrupt_payload: dict[str, Any]
    trace_id: str | None
    error_code: str | None
    started_at: dt.datetime
    ended_at: dt.datetime | None


class FeedbackCreate(BaseModel):
    rating: Literal["up", "down", "helpful", "not_helpful"]
    comment: str | None = Field(default=None, max_length=2000)
    idempotency_key: str | None = Field(default=None, max_length=80)


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    message_id: uuid.UUID
    rating: str
    comment: str | None
    review_task_id: uuid.UUID | None
    created_at: dt.datetime


class StopResult(BaseModel):
    run_id: uuid.UUID
    status: str

