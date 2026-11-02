"""OTLP telemetry setup. Any MELT backend can receive the same spans and metrics."""

from __future__ import annotations

import logging

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

logger = logging.getLogger(__name__)

_METER = metrics.get_meter("sahyog.http")
_REQUEST_DURATION = _METER.create_histogram(
    "http.server.duration",
    unit="ms",
    description="HTTP request duration in milliseconds.",
)
_REQUEST_ERRORS = _METER.create_counter(
    "http.server.errors",
    unit="1",
    description="HTTP responses with status >= 500.",
)


def init_telemetry(
    service_name: str,
    endpoint: str | None,
    *,
    sample_ratio: float = 0.1,
) -> bool:
    """Configure global tracer and meter providers once. Returns True when exporting."""

    resource = Resource.create({SERVICE_NAME: service_name, "service.namespace": "sahyog"})
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        sampler = ParentBased(TraceIdRatioBased(max(0.0, min(1.0, sample_ratio))))
        tracer_provider = TracerProvider(resource=resource, sampler=sampler)
        if endpoint:
            exporter = OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
            tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
        else:
            logger.warning(
                "OTLP endpoint not configured; spans are not exported",
                extra={"event": "telemetry.disabled"},
            )
        trace.set_tracer_provider(tracer_provider)
    if not isinstance(metrics.get_meter_provider(), MeterProvider):
        readers = []
        if endpoint:
            readers.append(
                PeriodicExportingMetricReader(
                    OTLPMetricExporter(endpoint=f"{endpoint.rstrip('/')}/v1/metrics"),
                    export_interval_millis=15_000,
                )
            )
        metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=readers))
    return bool(endpoint)


def record_http_request(
    *,
    method: str,
    route: str,
    status_code: int,
    duration_ms: float,
    traffic_class: str,
) -> None:
    """Record low-cardinality request metrics. Never pass paths with identifiers."""

    attributes: dict[str, str | int] = {
        "http.request.method": method,
        "http.route": route,
        "http.response.status_code": status_code,
        "sahyog.traffic_class": traffic_class,
    }
    try:
        _REQUEST_DURATION.record(duration_ms, attributes)
        if status_code >= 500:
            _REQUEST_ERRORS.add(1, attributes)
    except Exception:  # pragma: no cover - telemetry must never break a request
        logger.debug("metric recording failed", exc_info=True)


def current_trace_id() -> str | None:
    span = trace.get_current_span().get_span_context()
    if not span.is_valid:
        return None
    return format(span.trace_id, "032x")
