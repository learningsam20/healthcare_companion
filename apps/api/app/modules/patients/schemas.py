from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str | None
    locale: str
    notify_email: str | None = None
    slack_user_id: str | None = None
    linked: bool
    created_at: dt.datetime
