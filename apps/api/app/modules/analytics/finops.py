"""Deterministic FinOps what-if calculation over the versioned model in config.

Every figure is a planning range derived from config/finops_model.yaml and the price
catalogue. Nothing here observes live spend; the caller labels results as estimates.
"""

from __future__ import annotations

from typing import Any

from app.modules.analytics.schemas import WhatIfRequest, WhatIfResponse


def _range(payload: dict[str, Any], key: str) -> tuple[float, float] | None:
    value = payload.get(key)
    if not isinstance(value, dict):
        return None
    return float(value.get("min", 0)), float(value.get("max", 0))


def _capex_lakh(profile: dict[str, Any], hosting: str, gpu: bool) -> tuple[float, float]:
    lakh = _range(profile, "capex_inr_lakh")
    if lakh is not None and gpu and "with_gpu_min" in profile.get("capex_inr_lakh", {}):
        block = profile["capex_inr_lakh"]
        return float(block["with_gpu_min"]), float(block["with_gpu_max"])
    if lakh is not None:
        return lakh
    inr = _range(profile, "capex_inr")
    if inr is not None:
        if hosting == "laptop":
            return float(profile["capex_inr"].get("replacement_min", 0)) / 100000, float(
                profile["capex_inr"].get("replacement_max", 0)
            ) / 100000
        return inr[0] / 100000, inr[1] / 100000
    return 0.0, 0.0


def _opex_inr(profile: dict[str, Any], hosting: str) -> tuple[float, float]:
    key = "cloud_opex_inr_month" if hosting in {"india_cloud", "hybrid"} else "opex_inr_month"
    value = _range(profile, key)
    if value is None:
        value = _range(profile, "opex_inr_month")
    return value or (0.0, 0.0)


def calculate_what_if(model: dict[str, Any], request: WhatIfRequest) -> WhatIfResponse:
    profiles = model["profiles"]
    profile = profiles[request.profile]
    base_inputs: dict[str, Any] = dict(profile.get("inputs", {}))
    overrides = request.model_dump(
        include={
            "registered_users",
            "monthly_active_users",
            "peak_requests_per_hour",
            "documents_per_month",
            "audio_hours_per_month",
            "chat_turns_per_day",
            "external_llm_share",
        },
        exclude_none=True,
    )
    inputs = {**base_inputs, **overrides}
    fx = float(request.fx_usd_inr or model.get("fx_usd_inr", 88))
    unit_costs = model.get("unit_costs", {})
    external_input = float(unit_costs.get("external_input_per_million_usd", 0.15))
    external_output = float(unit_costs.get("external_output_per_million_usd", 0.6))
    turns = float(inputs.get("chat_turns_per_day", 0))
    share = float(inputs.get("external_llm_share", 0))

    external_model_usd_month = (
        turns
        * 30
        * (
            request.input_tokens_per_turn * external_input
            + request.output_tokens_per_turn * external_output
        )
        / 1_000_000
        * share
    )
    notifications_usd_month = request.sms_per_month * float(
        unit_costs.get("sms_per_segment_usd", 0)
    ) + request.emails_per_month * float(unit_costs.get("email_per_message_usd", 0))
    variable_inr_month = (external_model_usd_month + notifications_usd_month) * fx

    capex_min, capex_max = _capex_lakh(profile, request.hosting, bool(request.gpu))
    opex_min, opex_max = _opex_inr(profile, request.hosting)
    opex_min += variable_inr_month
    opex_max += variable_inr_month

    horizon = request.horizon_months
    tco_min = capex_min + opex_min * horizon / 100000
    tco_max = capex_max + opex_max * horizon / 100000

    revenue_lakh: float | None = None
    if request.revenue_per_active_user_inr_month > 0:
        mau = float(inputs.get("monthly_active_users", 0))
        revenue_lakh = request.revenue_per_active_user_inr_month * mau * horizon / 100000
    elif request.price_per_chat_turn_inr > 0:
        revenue_lakh = request.price_per_chat_turn_inr * turns * 30 * horizon / 100000

    gross_margin: float | None = None
    if revenue_lakh and revenue_lakh > 0:
        midpoint_opex_lakh = ((opex_min + opex_max) / 2) * horizon / 100000
        gross_margin = round((revenue_lakh - midpoint_opex_lakh) / revenue_lakh * 100, 2)

    monthly_turns = turns * 30
    cost_per_turn = (
        (opex_min / monthly_turns, opex_max / monthly_turns) if monthly_turns else (0.0, 0.0)
    )

    growth = []
    for year in model.get("growth", []):
        onprem = year.get("onprem_opex_inr_month", {})
        cloud = year.get("cloud_opex_inr_month", {})
        incremental = year.get("incremental_capex_inr_lakh", {})
        growth.append(
            {
                "year": year.get("year"),
                "profile": year.get("profile"),
                "registered_users": year.get("registered_users"),
                "monthly_active_users": year.get("monthly_active_users"),
                "chunks_searchable": year.get("chunks_searchable"),
                "onprem_opex_inr_month": onprem,
                "cloud_opex_inr_month": cloud,
                "incremental_capex_inr_lakh": incremental,
            }
        )

    return WhatIfResponse(
        model_version=str(model.get("model_version")),
        price_basis_date=str(model.get("price_basis_date")),
        profile=request.profile,
        hosting=request.hosting,
        horizon_months=horizon,
        fx_usd_inr=fx,
        assumptions={
            **inputs,
            "input_tokens_per_turn": request.input_tokens_per_turn,
            "output_tokens_per_turn": request.output_tokens_per_turn,
            "gpu": bool(request.gpu),
            "variable_model_usd_month": round(external_model_usd_month, 2),
            "notifications_usd_month": round(notifications_usd_month, 2),
        },
        capex_inr_lakh={"min": round(capex_min, 2), "max": round(capex_max, 2)},
        opex_inr_month={"min": round(opex_min, 2), "max": round(opex_max, 2)},
        tco_inr_lakh={"min": round(tco_min, 2), "max": round(tco_max, 2)},
        revenue_inr_lakh=round(revenue_lakh, 2) if revenue_lakh is not None else None,
        gross_margin_pct=gross_margin,
        unit_economics={
            "cost_per_chat_turn_inr_min": round(cost_per_turn[0], 2),
            "cost_per_chat_turn_inr_max": round(cost_per_turn[1], 2),
            "external_model_cost_inr_month": round(external_model_usd_month * fx, 2),
        },
        growth_curve=growth,
        notes=[
            "Planning ranges from the versioned FinOps model, not vendor quotes.",
            "Excludes tax. Local model electricity is included only where the profile states it.",
            "Cloud and colo prices vary by contract and region; validate before procurement.",
        ],
    )
