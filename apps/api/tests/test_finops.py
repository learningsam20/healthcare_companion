from __future__ import annotations

from pathlib import Path

import pytest
from app.modules.analytics.finops import calculate_what_if
from app.modules.analytics.schemas import WhatIfRequest
from sahyog_common.files import load_yaml

MODEL = load_yaml(Path("config/finops_model.yaml"))


def test_what_if_is_labelled_as_an_estimate() -> None:
    result = calculate_what_if(MODEL, WhatIfRequest())
    assert result.label == "estimate"
    assert result.currency == "INR"
    assert result.model_version == str(MODEL["model_version"])
    assert result.notes


def test_tco_is_capex_plus_opex_over_horizon() -> None:
    result = calculate_what_if(MODEL, WhatIfRequest(horizon_months=36))
    capex = result.capex_inr_lakh
    opex = result.opex_inr_month
    tco = result.tco_inr_lakh
    assert tco["min"] == pytest.approx(capex["min"] + opex["min"] * 36 / 100000, abs=0.02)
    assert tco["max"] == pytest.approx(capex["max"] + opex["max"] * 36 / 100000, abs=0.02)


def test_external_model_cost_scales_with_share_and_tokens() -> None:
    base = calculate_what_if(
        MODEL,
        WhatIfRequest(chat_turns_per_day=10_000, external_llm_share=0.0),
    )
    external = calculate_what_if(
        MODEL,
        WhatIfRequest(chat_turns_per_day=10_000, external_llm_share=1.0),
    )
    base_variable = base.assumptions["variable_model_usd_month"]
    external_variable = external.assumptions["variable_model_usd_month"]
    assert isinstance(base_variable, (int, float))
    assert isinstance(external_variable, (int, float))
    assert base_variable == 0
    assert external_variable > 0
    base_cost = base.unit_economics["external_model_cost_inr_month"]
    external_cost = external.unit_economics["external_model_cost_inr_month"]
    assert base_cost is not None
    assert external_cost is not None
    assert external_cost > base_cost


def test_revenue_and_margin_are_reported_only_with_inputs() -> None:
    no_revenue = calculate_what_if(MODEL, WhatIfRequest())
    assert no_revenue.revenue_inr_lakh is None
    assert no_revenue.gross_margin_pct is None

    priced = calculate_what_if(
        MODEL,
        WhatIfRequest(
            revenue_per_active_user_inr_month=199,
            monthly_active_users=2_000,
            chat_turns_per_day=4_000,
        ),
    )
    assert priced.revenue_inr_lakh is not None
    assert priced.revenue_inr_lakh > 0
    assert priced.gross_margin_pct is not None


def test_growth_curve_comes_from_the_versioned_model() -> None:
    result = calculate_what_if(MODEL, WhatIfRequest())
    assert result.growth_curve
    assert all("year" in row for row in result.growth_curve)
