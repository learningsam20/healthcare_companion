from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FlagUpdate(BaseModel):
    value: bool
    reason: str = Field(min_length=5, max_length=300)


class FlagOut(BaseModel):
    key: str
    value: bool
    default: bool
    source: str
    flag_class: str
    owner: str
    expires: dt.date | None
    description: str
    runtime_changeable: bool


class FlagChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    flag_key: str
    old_value: bool
    new_value: bool
    actor_subject: str
    reason: str
    created_at: dt.datetime


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_subject: str
    actor_role: str
    action: str
    resource_type: str
    resource_id: str | None
    patient_id: uuid.UUID | None
    trace_id: str | None
    event_metadata: dict[str, Any] = Field(serialization_alias="metadata")
    created_at: dt.datetime


class AuditEventOutPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_subject: str
    actor_role: str
    action: str
    resource_type: str
    resource_id: str | None
    trace_id: str | None
    created_at: dt.datetime


class GovernancePatch(BaseModel):
    finops_history_days: int | None = Field(default=None, ge=7, le=3650)
    judge_require_attested_human: bool | None = None
    judge_min_kappa: float | None = Field(default=None, ge=0.0, le=1.0)
    chat_retention_days: int | None = Field(default=None, ge=1, le=3650)
    memory_retention_days: int | None = Field(default=None, ge=1, le=3650)
    external_egress_enabled: bool | None = None
    dpdp_enforce: bool | None = None
