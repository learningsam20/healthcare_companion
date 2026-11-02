from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class ReviewTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID | None
    patient_display_name: str | None = None
    created_by_subject: str
    assigned_role: str
    reason: str
    status: str
    owner_subject: str | None
    resource_type: str | None
    resource_id: str | None
    due_at: dt.datetime | None
    resolution: str | None
    closed_at: dt.datetime | None
    created_at: dt.datetime


class CloseReviewRequest(BaseModel):
    resolution: str = Field(min_length=5, max_length=500)
