from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

IncidentSeverity = Literal["low", "medium", "high", "critical"]
IncidentStatus = Literal["open", "investigating", "closed"]


class IncidentCreate(BaseModel):
    patient_id: uuid.UUID | None = None
    severity: IncidentSeverity
    category: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(min_length=1, max_length=10000)
    linked_resource_type: str | None = Field(default=None, max_length=40)
    linked_resource_id: str | None = Field(default=None, max_length=200)


class IncidentUpdate(BaseModel):
    status: IncidentStatus | None = None
    resolution: str | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def require_change(self) -> IncidentUpdate:
        if self.status is None and self.resolution is None:
            raise ValueError("Provide status or resolution.")
        if self.status == "closed" and not self.resolution:
            raise ValueError("A resolution is required when closing an incident.")
        return self


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID | None
    reported_by_subject: str
    severity: IncidentSeverity
    category: str
    title: str
    detail: str
    status: IncidentStatus
    linked_resource_type: str | None
    linked_resource_id: str | None
    resolution: str | None
    created_at: dt.datetime
    closed_at: dt.datetime | None
