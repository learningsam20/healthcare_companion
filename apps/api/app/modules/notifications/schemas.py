from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID | None
    recipient_subject: str
    recipient_role: str
    template_id: str
    template_version: int
    channel: str
    status: str
    title: str
    body: str
    read_at: dt.datetime | None
    created_at: dt.datetime


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel: str
    status: str
    attempts: int
    last_error_code: str | None
    provider_message_id: str | None
    scheduled_at: dt.datetime
    sent_at: dt.datetime | None


class NotificationDetailOut(NotificationOut):
    deliveries: list[DeliveryOut] = Field(default_factory=list)


class ContactCreate(BaseModel):
    subject: str = Field(min_length=2, max_length=200)
    patient_id: uuid.UUID | None = None
    channel: Literal["email", "sms", "slack_staff", "slack_patient"]
    address: str = Field(min_length=3, max_length=300)
    verified: bool = False
    opt_in: bool = False
    workspace_id: str | None = Field(default=None, max_length=100)


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject: str
    patient_id: uuid.UUID | None
    channel: str
    address: str
    verified: bool
    opt_in: bool
    workspace_id: str | None
    created_at: dt.datetime


class VerificationCodeRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class SelfContactCreate(BaseModel):
    """Patient/caregiver self-registration of a contact (always unverified until coded)."""

    channel: Literal["email", "sms", "slack_patient"]
    address: str = Field(min_length=3, max_length=300)
    opt_in: bool = False


class VerificationRequestedOut(BaseModel):
    expires_at: dt.datetime
    code: str | None = None
    # sent | unconfigured | external_disabled | failed — never claims "sent" without an adapter ack.
    delivery: str = "unconfigured"
    delivery_error: str | None = None


class SendRequest(BaseModel):
    template_id: str = Field(min_length=2, max_length=60)
    recipient_subject: str = Field(min_length=2, max_length=200)
    recipient_role: Literal[
        "patient", "caregiver", "doctor", "front_desk", "pharmacist", "compliance", "admin"
    ] = "patient"
    patient_id: uuid.UUID | None = None
    locale: Literal["en-IN", "hi-IN", "mr-IN"] = "en-IN"
    data: dict[str, Any] = Field(default_factory=dict)
    channels: list[str] | None = None


class SendOut(BaseModel):
    notification: NotificationDetailOut
    queued_channels: int
    suppressed_channels: int
