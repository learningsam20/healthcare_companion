"""Egress must not proceed without composite PII (G-28 / user requirement)."""

from __future__ import annotations

import pytest

from app.agents.llm_gateway import ExternalEgressBlocked, LlmGateway
from app.agents.pii_gate import PiiGateResult
from app.core.config import Settings


class _Gate:
    async def redact(self, text: str, *, trace_id: str) -> PiiGateResult:
        return PiiGateResult(
            healthy=False,
            engine="regex_fallback",
            not_clinical_grade=True,
            count=1,
            redacted_text="",
            reason="composite_engine_not_available",
        )


@pytest.mark.asyncio
async def test_external_blocked_when_regex_fallback() -> None:
    settings = Settings(
        _env_file=None,
        litellm_base_url="http://litellm.test",
        litellm_master_key="test-key",
        external_egress_enabled=True,
        pii_service_url="http://pii.test",
        mcp_context_secret="x" * 32,
    )
    models = {
        "purposes": {"chat": {"primary": "ext", "fallback": None, "timeout_seconds": 5}},
        "aliases": {
            "ext": {
                "kind": "chat",
                "provider": "openai",
                "max_output_tokens": 100,
            }
        },
    }
    gateway = LlmGateway(settings, models, pii_gate=_Gate())  # type: ignore[arg-type]
    with pytest.raises(ExternalEgressBlocked):
        await gateway._route("chat", "patient email test@example.com")
