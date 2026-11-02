from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HandoffCreate(BaseModel):
    patient_id: uuid.UUID | None = None
    clinic_code: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=4000)
    resource_type: str | None = Field(default=None, max_length=40)
    resource_id: str | None = Field(default=None, max_length=200)


class HandoffAssign(BaseModel):
    assigned_to_subject: str = Field(min_length=1, max_length=200)


class HandoffResolve(BaseModel):
    notes: str = Field(min_length=1, max_length=4000)


class HandoffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID | None
    created_by_subject: str
    assigned_to_subject: str | None
    clinic_code: str
    reason: str
    status: Literal["open", "assigned", "resolved"]
    priority: Literal["normal", "urgent", "emergency"] = "normal"
    notes: str | None
    resource_type: str | None
    resource_id: str | None
    rule_ids: list[str] = Field(default_factory=list)
    sla_due_at: dt.datetime | None = None
    notified_at: dt.datetime | None = None
    delivery_status: Literal[
        "pending", "queued", "sent", "partial", "failed", "skipped"
    ] = "pending"
    overdue_alerted_at: dt.datetime | None = None
    acknowledged_at: dt.datetime | None = None
    mtta_seconds: int | None = None
    created_at: dt.datetime
    resolved_at: dt.datetime | None
    overdue: bool = False
    mtta_within_sla: bool | None = None


class HandoffMttaSummary(BaseModel):
    """Rolling MTTA stats for staff ops (G-25)."""

    window_hours: int
    acknowledged_count: int
    mean_seconds: float | None = None
    p50_seconds: float | None = None
    p95_seconds: float | None = None
    max_seconds: float | None = None
    within_sla_count: int = 0
    within_sla_ratio: float | None = None
    sla_seconds_emergency: int = 120
    target_met: bool | None = None
