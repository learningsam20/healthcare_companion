from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class StockItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sku: str
    drug_name: str
    form: str
    strength: str
    quantity: int
    clinic_code: str
    updated_at: dt.datetime
    source: str
    status: str | None = None
    stale: bool | None = None
    age_minutes: int | None = None


class StockItemWrite(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    drug_name: str = Field(min_length=1, max_length=200)
    form: str = Field(default="", max_length=80)
    strength: str = Field(default="", max_length=80)
    quantity: int = Field(ge=0)
    clinic_code: str = Field(min_length=1, max_length=40)
    source: str = Field(default="manual", max_length=80)


class StockImportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    file_hash: str
    as_of: dt.datetime
    row_count: int
    status: str
    errors: list[object]
