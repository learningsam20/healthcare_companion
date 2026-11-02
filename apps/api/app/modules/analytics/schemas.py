from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field


class FinopsBudgetUpsert(BaseModel):
    scope_type: str = Field(min_length=1, max_length=40)
    scope_id: str = Field(min_length=1, max_length=200)
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    limit_usd: float = Field(ge=0)
    alert_pct: float = Field(default=80, ge=0, le=100)
    hard_stop: bool = False
    owner: str = Field(min_length=1, max_length=200)


class FinopsSavingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    amount_usd: float = Field(ge=0)
    period_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    notes: str | None = None


class WhatIfRequest(BaseModel):
    profile: Literal["P", "S", "M", "L"] = "P"
    hosting: Literal["laptop", "colo", "on_prem", "india_cloud", "hybrid"] = "laptop"
    horizon_months: int = Field(default=36, ge=1, le=120)
    registered_users: int | None = Field(default=None, ge=1, le=10_000_000)
    monthly_active_users: int | None = Field(default=None, ge=1, le=10_000_000)
    peak_requests_per_hour: int | None = Field(default=None, ge=1, le=10_000_000)
    documents_per_month: int | None = Field(default=None, ge=0, le=10_000_000)
    audio_hours_per_month: int | None = Field(default=None, ge=0, le=1_000_000)
    chat_turns_per_day: int | None = Field(default=None, ge=0, le=10_000_000)
    external_llm_share: float | None = Field(default=None, ge=0, le=1)
    gpu: bool | None = None
    fx_usd_inr: float | None = Field(default=None, gt=0, le=500)
    input_tokens_per_turn: int = Field(default=900, ge=1, le=200_000)
    output_tokens_per_turn: int = Field(default=250, ge=1, le=200_000)
    revenue_per_active_user_inr_month: float = Field(default=0, ge=0)
    price_per_chat_turn_inr: float = Field(default=0, ge=0)
    sms_per_month: int = Field(default=0, ge=0)
    emails_per_month: int = Field(default=0, ge=0)


class ReconciliationOut(BaseModel):
    status: Literal["matched", "partial", "variance", "insufficient_data", "unavailable"]
    window_start: dt.datetime | None = None
    window_end: dt.datetime | None = None
    app_cost_usd: float = 0.0
    gateway_cost_usd: float = 0.0
    app_calls: int = 0
    gateway_calls: int = 0
    matched_calls: int = 0
    unmatched_app_calls: int = 0
    unmatched_gateway_calls: int = 0
    variance_usd: float = 0.0
    variance_pct: float = 0.0
    tolerance_pct: float = 2.0
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: dt.datetime | None = None
    note: str | None = None


class ReconcileRequest(BaseModel):
    window_hours: int = Field(default=24, ge=1, le=24 * 90)
    lag_minutes: int = Field(default=5, ge=0, le=120)


class InsightDecisionRequest(BaseModel):
    status: Literal["accepted", "rejected"]
    note: str | None = Field(default=None, max_length=500)


class WhatIfResponse(BaseModel):
    label: Literal["estimate"] = "estimate"
    model_version: str
    price_basis_date: str
    profile: str
    hosting: str
    horizon_months: int
    currency: str = "INR"
    fx_usd_inr: float
    assumptions: dict[str, float | int | str | bool]
    capex_inr_lakh: dict[str, float]
    opex_inr_month: dict[str, float]
    tco_inr_lakh: dict[str, float]
    revenue_inr_lakh: float | None
    gross_margin_pct: float | None
    unit_economics: dict[str, float | None]
    growth_curve: list[dict[str, object]]
    notes: list[str]
