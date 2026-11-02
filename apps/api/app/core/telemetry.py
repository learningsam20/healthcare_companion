from __future__ import annotations

from sahyog_common.telemetry import init_telemetry

from app.core.config import Settings


def configure_telemetry(settings: Settings) -> bool:
    return init_telemetry(
        settings.otel_service_name,
        settings.otel_exporter_otlp_endpoint or None,
        sample_ratio=settings.otel_traces_sampler_arg,
    )
