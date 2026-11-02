from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ConsentScope = Literal["chat", "records", "scheduling", "notifications"]
DEFAULT_SCOPES: list[ConsentScope] = ["chat", "records"]


class ConsentCreate(BaseModel):
    caregiver_subject: str = Field(min_length=3, max_length=200)
    patient_id: uuid.UUID | None = None
    scopes: list[ConsentScope] = Field(default_factory=lambda: list(DEFAULT_SCOPES), min_length=1)
    purpose: str = Field(default="care", min_length=2, max_length=200)
    expires_at: dt.datetime | None = None

    @field_validator("scopes")
    @classmethod
    def _unique_scopes(cls, value: list[ConsentScope]) -> list[ConsentScope]:
        return list(dict.fromkeys(value))


class ConsentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str | None = None
    grantor_subject: str
    caregiver_subject: str
    scopes: list[str]
    purpose: str
    status: str
    granted_at: dt.datetime
    expires_at: dt.datetime | None
    revoked_at: dt.datetime | None


class ContextOut(BaseModel):
    consent_id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str | None
    scopes: list[str]
    expires_at: dt.datetime | None
