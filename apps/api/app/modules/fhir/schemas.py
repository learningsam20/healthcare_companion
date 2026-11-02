from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel, Field


class FhirLinkIn(BaseModel):
    fhir_patient_id: str = Field(min_length=1, max_length=120)
    system: str = Field(default="fhir", max_length=200)


class FhirLinkOut(BaseModel):
    patient_id: uuid.UUID
    fhir_patient_id: str
    system: str
    updated_at: dt.datetime


class FhirPatientOut(BaseModel):
    patient_id: uuid.UUID
    link: FhirLinkOut
    demographics: dict[str, Any]
    source: str = "fhir"


class FhirEncountersOut(BaseModel):
    patient_id: uuid.UUID
    fhir_patient_id: str
    encounters: list[dict[str, Any]]
    source: str = "fhir"


class FhirDocumentReferencesOut(BaseModel):
    patient_id: uuid.UUID
    fhir_patient_id: str | None = None
    local_records: list[dict[str, Any]] = Field(default_factory=list)
    fhir_records: list[dict[str, Any]] = Field(default_factory=list)
    source: str = "local+fhir"
