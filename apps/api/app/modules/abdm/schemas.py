from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field


class LinkRequest(BaseModel):
    system: Literal["abha", "abdm_sandbox"]
    value: str = Field(min_length=1, max_length=200)


class LinkOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    system: str
    value_last4: str
    purpose: str
    status: Literal["linked", "unlinked", "pending"]
    created_by: str
    created_at: dt.datetime
    updated_at: dt.datetime
    certified: bool = False


class StatusOut(BaseModel):
    certified: bool = False
    sandbox_configured: bool
    status: str
