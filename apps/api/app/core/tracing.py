"""Agent trace collection.

Spans carry identifiers, counts, hashes and durations only. Prompt text, completions,
tool arguments and results are never attached. A per-request collector can be
exported to Langfuse's ingestion API; OTLP export remains available independently.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import httpx
from opentelemetry import trace

from app.core.config import Settings

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer("sahyog.agent")
_collector: ContextVar[TraceCollector | None] = ContextVar("sahyog_trace_collector", default=None)


def content_digest(value: str | bytes | None) -> str | None:
    if value is None:
        return None
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()[:16]


@dataclass
class SpanRecord:
    span_id: str
    name: str
    kind: str
    start_time: dt.datetime
    end_time: dt.datetime
    attributes: dict[str, Any]
    parent_span_id: str | None = None
    error: bool = False


@dataclass
class TraceCollector:
    trace_id: str
    name: str
    started_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))
    spans: list[SpanRecord] = field(default_factory=list)
    _stack: list[str] = field(default_factory=list)

    @contextmanager
    def span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
        *,
        kind: str = "span",
    ) -> Iterator[None]:
        span_id = uuid.uuid4().hex[:16]
        parent = self._stack[-1] if self._stack else None
        started = dt.datetime.now(dt.UTC)
        self._stack.append(span_id)
        error = False
        try:
            with _tracer.start_as_current_span(name) as otel_span:
                for key, value in (attributes or {}).items():
                    if isinstance(value, (str, int, float, bool)):
                        otel_span.set_attribute(key, value)
                try:
                    yield
                except Exception:
                    error = True
                    otel_span.set_attribute("error", True)
                    raise
        finally:
            self._stack.pop()
            self.spans.append(
                SpanRecord(
                    span_id=span_id,
                    name=name,
                    kind=kind,
                    start_time=started,
                    end_time=dt.datetime.now(dt.UTC),
                    attributes=dict(attributes or {}),
                    parent_span_id=parent,
                    error=error,
                )
            )


def start_trace(trace_id: str, name: str) -> TraceCollector:
    collector = TraceCollector(trace_id=trace_id, name=name)
    _collector.set(collector)
    return collector


def current_trace() -> TraceCollector | None:
    return _collector.get()


@contextmanager
def trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
    *,
    kind: str = "span",
) -> Iterator[None]:
    collector = _collector.get()
    if collector is None:
        with _tracer.start_as_current_span(name) as otel_span:
            for key, value in (attributes or {}).items():
                if isinstance(value, (str, int, float, bool)):
                    otel_span.set_attribute(key, value)
            yield
        return
    with collector.span(name, attributes, kind=kind):
        yield


def _sampled(trace_id: str, ratio: float) -> bool:
    if ratio >= 1.0:
        return True
    if ratio <= 0.0:
        return False
    try:
        bucket = int(trace_id[-8:], 16) / 0xFFFFFFFF
    except ValueError:
        return False
    return bucket < ratio


def _event(collector: TraceCollector, record: SpanRecord) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": record.span_id,
        "traceId": collector.trace_id,
        "name": record.name,
        "startTime": record.start_time.isoformat(),
        "endTime": record.end_time.isoformat(),
        "metadata": {
            **record.attributes,
            "duration_ms": round((record.end_time - record.start_time).total_seconds() * 1000, 2),
        },
        "level": "ERROR" if record.error else "DEFAULT",
    }
    if record.parent_span_id:
        body["parentObservationId"] = record.parent_span_id
    event: dict[str, Any] = {"id": uuid.uuid4().hex, "timestamp": record.end_time.isoformat()}
    if record.kind == "generation":
        prompt_tokens = int(record.attributes.get("prompt_tokens", 0) or 0)
        completion_tokens = int(record.attributes.get("completion_tokens", 0) or 0)
        body["model"] = record.attributes.get("model_alias")
        body["usage"] = {
            "input": prompt_tokens,
            "output": completion_tokens,
            "total": prompt_tokens + completion_tokens,
            "unit": "TOKENS",
        }
        event.update({"type": "generation-create", "body": body})
        return event
    event.update({"type": "span-create", "body": body})
    return event


def langfuse_ingest_bases(settings: Settings) -> list[str]:
    """Candidate Langfuse base URLs for ingestion.

    Compose services use ``LANGFUSE_HOST=http://langfuse-web:3000``. Host-side
    ``--local`` API processes cannot resolve that DNS name, so
    ``LANGFUSE_PUBLIC_URL`` (published loopback) is appended as a fallback.
    """
    bases: list[str] = []
    for candidate in (settings.langfuse_host, settings.langfuse_public_url):
        base = (candidate or "").strip().rstrip("/")
        if base and base not in bases:
            bases.append(base)
    return bases


async def export_trace(settings: Settings, collector: TraceCollector) -> bool:
    bases = langfuse_ingest_bases(settings)
    if not (bases and settings.langfuse_public_key and settings.langfuse_secret_key):
        return False
    if settings.langfuse_capture_content:
        logger.error(
            "Langfuse content capture is enabled; refusing to export",
            extra={"event": "telemetry.langfuse.blocked"},
        )
        return False
    if not _sampled(collector.trace_id, settings.trace_export_sample_ratio):
        return False
    batch: list[dict[str, Any]] = [
        {
            "id": uuid.uuid4().hex,
            "type": "trace-create",
            "timestamp": collector.started_at.isoformat(),
            "body": {
                "id": collector.trace_id,
                "name": collector.name,
                "timestamp": collector.started_at.isoformat(),
                "metadata": {
                    "service": settings.otel_service_name,
                    "span_count": len(collector.spans),
                },
            },
        }
    ]
    batch.extend(_event(collector, record) for record in collector.spans)
    response: httpx.Response | None = None
    last_error: str | None = None
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            for base in bases:
                try:
                    response = await client.post(
                        f"{base}/api/public/ingestion",
                        json={"batch": batch},
                        auth=(settings.langfuse_public_key, settings.langfuse_secret_key),
                    )
                    break
                except httpx.HTTPError as exc:
                    last_error = f"{type(exc).__name__}:{base}"
                    response = None
                    continue
    except httpx.HTTPError:
        logger.warning(
            "Langfuse export unavailable",
            extra={"event": "telemetry.langfuse.unavailable"},
        )
        return False
    if response is None:
        logger.warning(
            "Langfuse export unavailable",
            extra={
                "event": "telemetry.langfuse.unavailable",
                "extra_fields": {"tried": bases, "last_error": last_error},
            },
        )
        return False
    if response.status_code >= 300:
        logger.warning(
            "Langfuse export rejected",
            extra={
                "event": "telemetry.langfuse.rejected",
                "extra_fields": {"status": response.status_code},
            },
        )
        return False
    try:
        result = response.json()
    except ValueError:
        return True
    errors = result.get("errors") if isinstance(result, dict) else None
    if errors:
        logger.warning(
            "Langfuse export partially rejected",
            extra={
                "event": "telemetry.langfuse.rejected",
                "extra_fields": {"status": response.status_code, "errors": len(errors)},
            },
        )
        return False
    return True
