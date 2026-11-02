"""G-29: OpenDecider required mode fails honestly when backend/weights absent."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_required_without_backend_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENDECIDER_REQUIRED", "true")
    monkeypatch.setenv("DECIDER_BACKEND", "auto")
    monkeypatch.delenv("DECIDER_LLAMA_URL", raising=False)
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("STRANDS_DECIDER_URL", raising=False)
    monkeypatch.setenv("OPENDECIDER_GGUF", "/tmp/definitely-missing-opendecider.gguf")
    from sahyog_mcp_decider import main as mod

    class Ctx:
        locale = "en-IN"

    with pytest.raises(ValueError, match="opendecider_weights_missing"):
        await mod.classify_intent({"text": "book a doctor tomorrow"}, Ctx())


def test_explain_reports_weights_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENDECIDER_REQUIRED", "false")
    monkeypatch.setenv("OPENDECIDER_GGUF", "/tmp/definitely-missing-opendecider.gguf")
    from sahyog_mcp_decider import main as mod

    class Ctx:
        locale = "en-IN"

    info = mod.explain_decision({}, Ctx())
    assert info["weights_present"] is False
    assert "Keyword fallback" in " ".join(info["limits"])
