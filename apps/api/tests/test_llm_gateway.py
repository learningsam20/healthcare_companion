from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.agents.llm_gateway import ExternalEgressBlocked, LlmGateway
from app.agents.pii_gate import PiiGateResult
from app.core.config import Settings
from app.core.tracing import start_trace

MODELS = {
    "purposes": {
        "conversation": {"primary": "local_small", "fallback": "local_main", "egress": "local"},
        "rag_answer": {
            "primary": "external_reasoning",
            "fallback": "local_main",
            "egress": "external_deidentified",
        },
        "judge": {
            "primary": "external_reasoning",
            "fallback": None,
            "egress": "external_deidentified",
        },
    },
    "aliases": {
        "local_small": {"provider": "ollama", "kind": "chat", "max_output_tokens": 100},
        "local_main": {"provider": "ollama", "kind": "chat", "max_output_tokens": 100},
        "external_reasoning": {
            "provider": "openrouter",
            "kind": "chat",
            "max_output_tokens": 100,
        },
    },
    "language_routing": {
        "conversation": {"hi": {"primary": "local_main"}, "mr": {"primary": "local_main"}},
    },
}


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "litellm_base_url": "http://litellm:4000",
        "litellm_master_key": "test-key",
        "external_egress_enabled": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class _Gate:
    def __init__(self, result: PiiGateResult) -> None:
        self.result = result
        self.calls = 0

    async def redact(self, text: str, *, trace_id: str) -> PiiGateResult:
        self.calls += 1
        return self.result


def _unhealthy_gate() -> _Gate:
    return _Gate(
        PiiGateResult(
            healthy=False,
            engine="regex_fallback",
            not_clinical_grade=True,
            count=1,
            redacted_text="",
            reason="composite_engine_not_available",
        )
    )


def _healthy_gate(redacted: str) -> _Gate:
    return _Gate(
        PiiGateResult(
            healthy=True,
            engine="composite",
            not_clinical_grade=False,
            count=1,
            redacted_text=redacted,
        )
    )


def test_language_routing_prefers_local_main_for_hi() -> None:
    gateway = LlmGateway(_settings(), MODELS)
    alias, _, _ = gateway.resolve("conversation", language="hi-IN")
    assert alias == "local_main"
    alias_en, _, _ = gateway.resolve("conversation", language="en-IN")
    assert alias_en == "local_small"


async def test_external_route_without_egress_falls_back_locally() -> None:
    gate = _unhealthy_gate()
    gateway = LlmGateway(_settings(), MODELS, pii_gate=gate)  # type: ignore[arg-type]
    route = await gateway._route("rag_answer", "patient text")
    assert route.alias_name == "local_main"
    assert route.external is False
    assert gate.calls == 0


async def test_unhealthy_gate_blocks_external_route() -> None:
    gate = _unhealthy_gate()
    gateway = LlmGateway(
        _settings(external_egress_enabled=True),
        MODELS,
        pii_gate=gate,  # type: ignore[arg-type]
    )
    route = await gateway._route("rag_answer", "patient text")
    assert route.alias_name == "local_main"
    assert route.external is False
    assert route.gate is not None
    assert route.gate.healthy is False
    assert gate.calls == 1


async def test_unhealthy_gate_without_fallback_refuses_egress() -> None:
    gateway = LlmGateway(
        _settings(external_egress_enabled=True),
        MODELS,
        pii_gate=_unhealthy_gate(),  # type: ignore[arg-type]
    )
    with pytest.raises(ExternalEgressBlocked):
        await gateway._route("judge", "de-identified eval text")


async def test_healthy_gate_allows_external_route_with_redaction() -> None:
    gate = _healthy_gate("Patient [PERSON] has fever.")
    gateway = LlmGateway(
        _settings(external_egress_enabled=True),
        MODELS,
        pii_gate=gate,  # type: ignore[arg-type]
    )
    route = await gateway._route("rag_answer", "Patient Asha has fever.")
    assert route.alias_name == "external_reasoning"
    assert route.external is True
    assert route.gate is not None and route.gate.healthy is True
    outbound = gateway._redacted_messages(
        [{"role": "user", "content": "Patient Asha has fever."}], route.gate
    )
    assert outbound == [{"role": "user", "content": "Patient [PERSON] has fever."}]


def test_redacted_message_count_mismatch_is_rejected() -> None:
    gateway = LlmGateway(_settings(), MODELS)
    gate = PiiGateResult(
        healthy=True,
        engine="composite",
        not_clinical_grade=False,
        count=0,
        redacted_text="single piece",
    )
    assert (
        gateway._redacted_messages(
            [{"role": "system", "content": "a"}, {"role": "user", "content": "b"}], gate
        )
        is None
    )


class _Response:
    status_code = 200
    headers = {"x-litellm-call-id": "header-call-id"}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {
            "id": "chatcmpl-body-id",
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 2},
        }


class _Client:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.posted: dict[str, Any] | None = None

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> _Response:
        self.posted = json
        return _Response()


async def test_gateway_request_id_prefers_response_body_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()
    monkeypatch.setattr("app.agents.llm_gateway.httpx.AsyncClient", lambda *args, **kwargs: client)
    collector = start_trace("e" * 32, "test")
    gateway = LlmGateway(_settings(), MODELS)
    result = await gateway.complete(
        purpose="conversation",
        messages=[{"role": "user", "content": "hello"}],
        trace_id="e" * 32,
    )
    assert result.gateway_request_id == "chatcmpl-body-id"
    span = next(item for item in collector.spans if item.name == "llm.complete")
    assert span.attributes["prompt_tokens"] == 7
    assert span.attributes["completion_tokens"] == 2
    assert span.attributes["gateway_request_id"] == "chatcmpl-body-id"
    assert client.posted is not None
    assert client.posted["metadata"]["trace_id"] == "e" * 32
    assert client.posted["metadata"]["purpose"] == "conversation"


class _FailThenOllamaClient:
    """First post (LiteLLM) fails; second (Ollama) succeeds."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.urls: list[str] = []

    async def __aenter__(self) -> _FailThenOllamaClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def post(self, url: str, json: dict[str, Any], headers: dict[str, str] | None = None) -> _Response:
        self.urls.append(url)
        if "litellm" in url:
            raise httpx.ConnectError("litellm down", request=httpx.Request("POST", url))
        return _Response()


async def test_local_complete_falls_back_to_ollama_when_litellm_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients: list[_FailThenOllamaClient] = []

    def _factory(*args: Any, **kwargs: Any) -> _FailThenOllamaClient:
        client = _FailThenOllamaClient(*args, **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr("app.agents.llm_gateway.httpx.AsyncClient", _factory)
    models = {
        "purposes": {
            "conversation": {"primary": "local_main", "fallback": None, "egress": "local"},
        },
        "aliases": {
            "local_main": {
                "provider": "ollama",
                "kind": "chat",
                "model": "qwen2.5:3b-instruct-q4_K_M",
                "max_output_tokens": 100,
            },
        },
    }
    collector = start_trace("f" * 32, "test")
    gateway = LlmGateway(
        _settings(ollama_base_url="http://127.0.0.1:11434"),
        models,
    )
    result = await gateway.complete(
        purpose="conversation",
        messages=[{"role": "user", "content": "hello"}],
        trace_id="f" * 32,
    )
    assert result.content == "hello"
    assert any("litellm" in url for client in clients for url in client.urls)
    assert any("11434" in url for client in clients for url in client.urls)
    span = next(item for item in collector.spans if item.name == "llm.complete")
    assert span.attributes["provider"] == "ollama_direct"


EMBEDDING_MODELS = {
    "purposes": {
        "embedding": {
            "primary": "external_embedding",
            "fallback": None,
            "egress": "external_deidentified",
        }
    },
    "aliases": {
        "external_embedding": {
            "provider": "openrouter",
            "kind": "embedding",
            "dimensions": 2,
        }
    },
}


class _EmbedResponse:
    status_code = 200
    headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {
            "data": [
                {"index": 0, "embedding": [0.1, 0.2]},
                {"index": 1, "embedding": [0.3, 0.4]},
            ],
            "usage": {"prompt_tokens": 4},
        }


class _EmbedClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.posted: dict[str, Any] | None = None

    async def __aenter__(self) -> _EmbedClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> _EmbedResponse:
        self.posted = json
        return _EmbedResponse()


async def test_external_embedding_sends_redacted_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _EmbedClient()
    monkeypatch.setattr("app.agents.llm_gateway.httpx.AsyncClient", lambda *args, **kwargs: client)
    gate = _healthy_gate("Patient [PERSON] one\n\u241e\nPatient [PERSON] two")
    gateway = LlmGateway(
        _settings(external_egress_enabled=True),
        EMBEDDING_MODELS,
        pii_gate=gate,  # type: ignore[arg-type]
    )
    vectors = await gateway.embed(texts=["Asha one", "Asha two"])
    assert client.posted is not None
    assert client.posted["input"] == ["Patient [PERSON] one", "Patient [PERSON] two"]
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert gate.calls == 1


async def test_external_embedding_rejects_batch_shape_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _EmbedClient()
    monkeypatch.setattr("app.agents.llm_gateway.httpx.AsyncClient", lambda *args, **kwargs: client)
    gateway = LlmGateway(
        _settings(external_egress_enabled=True),
        EMBEDDING_MODELS,
        pii_gate=_healthy_gate("single piece"),  # type: ignore[arg-type]
    )
    with pytest.raises(ExternalEgressBlocked):
        await gateway.embed(texts=["Asha one", "Asha two"])
    assert client.posted is None
