from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AppointmentCreate(BaseModel):
    patient_id: uuid.UUID | None = None
    clinic_code: str = Field(min_length=2, max_length=40)
    doctor_name: str = Field(min_length=2, max_length=120)
    specialty_code: str = Field(min_length=2, max_length=40)
    starts_at: dt.datetime
    duration_minutes: int = Field(default=20, ge=10, le=60)


class RescheduleRequest(BaseModel):
    starts_at: dt.datetime
    duration_minutes: int | None = Field(default=None, ge=10, le=60)


class OverrideRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=500)
    action: Literal["cancel", "reschedule"]
    starts_at: dt.datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=10, le=60)


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID | None
    patient_display_name: str | None = None
    clinic_code: str
    doctor_name: str
    specialty_code: str
    specialty_label: str | None = None
    starts_at: dt.datetime
    duration_minutes: int
    status: str
    traffic_class: str
    source: str = "front_desk"
    visit_kind: Literal["first", "repeat", "unknown"] | None = None
    no_show_risk: float | None = None
    no_show_band: str | None = None
    waitlist_suggested: bool = False
    confirm_by_reply: bool = False
    waitlist_status: str | None = None
    waitlist_owner_subject: str | None = None
    waitlist_claimed_at: dt.datetime | None = None
    waitlist_closed_at: dt.datetime | None = None
    waitlist_resolution: str | None = None
    waitlist_notes: str | None = None
    waitlist_offer_patient_id: uuid.UUID | None = None
    waitlist_offer_appointment_id: uuid.UUID | None = None
    created_at: dt.datetime


class DoctorOut(BaseModel):
    doctor_name: str
    specialty_code: str
    specialty_label: str
    clinic_code: str
    appointments: int
    last_seen_at: dt.datetime | None


class SlotsOut(BaseModel):
    doctor_name: str
    clinic_code: str
    timezone: str
    generated_for_days: int
    slots: list[dt.datetime]
