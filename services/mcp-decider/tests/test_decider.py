from __future__ import annotations

import time

import pytest
from sahyog_common.context import ExecutionContext, Role
from sahyog_mcp_decider.main import classify_intent, classify_red_flag, explain_decision

CONTEXT = ExecutionContext(
    actor_subject="patient-1",
    actor_role=Role.PATIENT,
    trace_id="trace-1",
    issued_at=int(time.time()),
    expires_at=int(time.time()) + 60,
)


@pytest.mark.asyncio
async def test_booking_intent_is_recognized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("DECIDER_LLAMA_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENDECIDER_REQUIRED", "false")
    result = await classify_intent({"text": "I want to book an appointment with a doctor"}, CONTEXT)
    assert result["intent"] == "book_appointment"
    assert result["category"] == "workflow"
    assert 0.5 <= result["confidence"] <= 0.95
    assert result["model"] is None
    assert result["engine"] == "deterministic_v1"


@pytest.mark.asyncio
async def test_hindi_booking_intent_is_recognized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("DECIDER_LLAMA_URL", raising=False)
    monkeypatch.setenv("OPENDECIDER_REQUIRED", "false")
    result = await classify_intent({"text": "मुझे डॉक्टर के साथ अपॉइंटमेंट बुक करना है"}, CONTEXT)
    assert result["intent"] == "book_appointment"


@pytest.mark.asyncio
async def test_unknown_intent_falls_back_to_other(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("DECIDER_LLAMA_URL", raising=False)
    monkeypatch.setenv("OPENDECIDER_REQUIRED", "false")
    result = await classify_intent({"text": "hello there"}, CONTEXT)
    assert result["intent"] == "other"
    assert result["category"] == "conversation"


@pytest.mark.asyncio
async def test_empty_text_is_rejected() -> None:
    with pytest.raises(ValueError, match="text is required"):
        await classify_intent({"text": " "}, CONTEXT)


def test_red_flag_second_pass_escalates_emergency() -> None:
    result = classify_red_flag({"text": "heavy bleeding that will not stop"}, CONTEXT)
    assert result["count"] == 1
    assert result["escalate"] is True
    assert result["model"] is None


def test_explanation_states_limits_and_engine() -> None:
    result = explain_decision({}, CONTEXT)
    assert result["version"] == "opendecider_or_strands_or_deterministic_v1"
    assert any("not clinically validated" in item.lower() for item in result["limits"])
    assert "weights_present" in result
