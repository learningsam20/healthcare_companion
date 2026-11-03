from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from app.core import tracing
from app.core.config import Settings
from app.core.tracing import (
    TraceCollector,
    _event,
    _sampled,
    content_digest,
    export_trace,
    langfuse_ingest_bases,
)


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "langfuse_host": "http://langfuse-web:3000",
        "langfuse_public_url": "http://localhost:5721",
        "langfuse_public_key": "pk-lf-test",
        "langfuse_secret_key": "sk-lf-test",
        "langfuse_capture_content": False,
        "trace_export_sample_ratio": 1.0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_langfuse_ingest_bases_include_public_fallback() -> None:
    assert langfuse_ingest_bases(_settings()) == [
        "http://langfuse-web:3000",
        "http://localhost:5721",
    ]
    assert langfuse_ingest_bases(
        _settings(langfuse_host="http://localhost:5721", langfuse_public_url="http://localhost:5721")
    ) == ["http://localhost:5721"]


def test_collector_records_parent_and_generation_metadata() -> None:
    collector = TraceCollector(trace_id="a" * 32, name="POST /chat")
    with (
        collector.span("agent.run", {"graph": "chat"}),
        collector.span(
            "llm.complete",
            {"model_alias": "local_small", "prompt_tokens": 10, "completion_tokens": 4},
            kind="generation",
        ),
    ):
        pass
    assert len(collector.spans) == 2
    by_name = {span.name: span for span in collector.spans}
    root = by_name["agent.run"]
    child = by_name["llm.complete"]
    assert child.parent_span_id == root.span_id
    assert child.kind == "generation"
    event = _event(collector, child)
    assert event["type"] == "generation-create"
    assert isinstance(event["timestamp"], str)
    assert event["body"]["usage"] == {
        "input": 10,
        "output": 4,
        "total": 14,
        "unit": "TOKENS",
    }
    serialized = json.dumps(event)
    assert "messages" not in serialized
    assert "content" not in serialized


def test_content_digest_is_stable_and_short() -> None:
    assert content_digest("hello") == content_digest(b"hello")
    assert len(content_digest("hello") or "") == 16
    assert content_digest("hello") != content_digest("hello!")


def test_sampling_ratio_is_deterministic() -> None:
    assert _sampled("0" * 32, 0.5) is True
    assert _sampled("f" * 32, 0.5) is False
    assert _sampled("not-hex-trace", 0.5) is False
    assert _sampled("f" * 32, 1.0) is True
    assert _sampled("0" * 32, 0.0) is False


async def test_export_refuses_content_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            calls.append((args, kwargs))

    monkeypatch.setattr(tracing.httpx, "AsyncClient", _Client)
    collector = TraceCollector(trace_id="b" * 32, name="test")
    assert await export_trace(_settings(langfuse_capture_content=True), collector) is False
    assert calls == []


async def test_export_sends_events_with_top_level_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return httpx.Response(207, json={"successes": [{"id": "x", "status": 201}], "errors": []})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def fake_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return real_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(tracing.httpx, "AsyncClient", fake_client)
    collector = TraceCollector(
        trace_id="c" * 32,
        name="POST /chat",
        session_id="session-uuid",
        user_id="subject-1",
    )
    with collector.span(
        "llm.complete",
        {
            "model_alias": "local_small",
            "prompt_tokens": 3,
            "completion_tokens": 2,
            "redacted_input": "user: hello",
            "redacted_output": "assistant: hi",
        },
        kind="generation",
    ):
        pass
    assert await export_trace(_settings(), collector) is True
    batch = seen["payload"]["batch"]
    assert batch[0]["type"] == "trace-create"
    assert batch[0]["timestamp"]
    assert batch[0]["body"]["sessionId"] == "session-uuid"
    assert batch[0]["body"]["userId"] == "subject-1"
    assert batch[1]["type"] == "generation-create"
    assert batch[1]["timestamp"]
    assert batch[1]["body"]["traceId"] == "c" * 32
    assert batch[1]["body"]["input"] == "user: hello"
    assert batch[1]["body"]["output"] == "assistant: hi"
    assert "redacted_input" not in batch[1]["body"]["metadata"]


async def test_export_reports_partial_ingestion_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            207,
            json={"successes": [], "errors": [{"id": "x", "status": 400, "message": "bad"}]},
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def fake_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return real_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(tracing.httpx, "AsyncClient", fake_client)
    collector = TraceCollector(trace_id="d" * 32, name="test")
    assert await export_trace(_settings(), collector) is False


async def test_export_falls_back_to_public_url_when_compose_host_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        if "langfuse-web" in str(request.url):
            raise httpx.ConnectError("nodename nor servname provided", request=request)
        return httpx.Response(
            207, json={"successes": [{"id": "t1", "status": 201}], "errors": []}
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def fake_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return real_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(tracing.httpx, "AsyncClient", fake_client)
    collector = TraceCollector(trace_id="e" * 32, name="POST /chat")
    assert await export_trace(_settings(), collector) is True
    assert any("localhost:5721" in url for url in seen_urls)
