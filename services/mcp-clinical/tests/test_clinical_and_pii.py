from __future__ import annotations

import time

import pytest
from sahyog_common.context import ExecutionContext, Role
from sahyog_mcp_clinical.main import check_red_flags, get_specialty_catalogue
from sahyog_mcp_pii.main import detect, redact

CONTEXT = ExecutionContext(
    actor_subject="patient-1",
    actor_role=Role.PATIENT,
    trace_id="trace-1",
    locale="hi-IN",
    issued_at=int(time.time()),
    expires_at=int(time.time()) + 60,
)


def test_check_red_flags_runs_deterministic_rules() -> None:
    result = check_red_flags({"text": "severe breathlessness and gasping"}, CONTEXT)
    assert result["engine"] == "deterministic_rules"
    assert result["requires_emergency_action"] is True
    assert result["count"] == 1
    assert result["matches"][0]["rule_id"] == "RF-BREATHLESS"
    assert result["matches"][0]["guidance"]


def test_check_red_flags_uses_context_locale() -> None:
    result = check_red_flags({"text": "मुझे सांस नहीं आ रही"}, CONTEXT)
    assert result["locale"] == "hi-IN"
    assert result["count"] == 1


def test_check_red_flags_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="text is required"):
        check_red_flags({"text": "  "}, CONTEXT)


def test_specialty_catalogue_is_closed() -> None:
    catalogue = get_specialty_catalogue({}, CONTEXT)
    codes = {item["code"] for item in catalogue["specialties"]}
    assert "cardiology" in codes
    assert "general_medicine" in codes


def test_pii_detects_contact_identifiers() -> None:
    result = detect({"text": "Reach me at asha@example.com or 9876543210"}, CONTEXT)
    types = {entity["type"] for entity in result["entities"]}
    assert types == {"email", "phone_in"}
    assert result["not_clinical_grade"] is True


def test_pii_redact_removes_values_but_keeps_shape() -> None:
    result = redact({"text": "MRN: 123456 email asha@example.com"}, CONTEXT)
    assert "asha@example.com" not in result["redacted_text"]
    assert "123456" not in result["redacted_text"]
    assert "[EMAIL]" in result["redacted_text"]
    assert "[MRN]" in result["redacted_text"]


def test_pii_aadhaar_is_detected() -> None:
    result = detect({"text": "Aadhaar 1234 5678 9012"}, CONTEXT)
    assert any(entity["type"] == "aadhaar" for entity in result["entities"])
