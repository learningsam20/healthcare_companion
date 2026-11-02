"""OpenDecider-on-Ollama returns JSON in message.reasoning with empty content."""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
from sahyog_common.context import ExecutionContext, Role
from sahyog_mcp_decider.main import _parse_intent_payload, classify_intent

CONTEXT = ExecutionContext(
    actor_subject="patient-1",
    actor_role=Role.PATIENT,
    trace_id="trace-od",
    issued_at=int(time.time()),
    expires_at=int(time.time()) + 60,
)


def test_parse_intent_from_reasoning_blob() -> None:
    parsed = _parse_intent_payload(
        '{"intent":"book_appointment","confidence":0.9}\n',
        model="hf.co/manjunathshiva/opendecider-small-GGUF:Q8_0",
    )
    assert parsed is not None
    assert parsed["engine"] == "opendecider_openai_compatible"
    assert parsed["intent"] == "book_appointment"
    assert parsed["confidence"] == 0.9


@pytest.mark.asyncio
async def test_classify_reads_message_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECIDER_BACKEND", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv(
        "DECIDER_MODEL", "hf.co/manjunathshiva/opendecider-small-GGUF:Q8_0"
    )
    monkeypatch.delenv("DECIDER_LLAMA_URL", raising=False)
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("STRANDS_DECIDER_URL", raising=False)
    monkeypatch.setenv("OPENDECIDER_REQUIRED", "false")

    class _Resp:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "reasoning": '{"intent":"book_appointment","confidence":0.91}\n',
                        }
                    }
                ]
            }

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, **kwargs: Any) -> _Resp:
            assert "/chat/completions" in url
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    result = await classify_intent(
        {"text": "I want to book an appointment with a doctor tomorrow"}, CONTEXT
    )
    assert result["engine"] == "opendecider_openai_compatible"
    assert result["intent"] == "book_appointment"
    assert result["model"] == "hf.co/manjunathshiva/opendecider-small-GGUF:Q8_0"
