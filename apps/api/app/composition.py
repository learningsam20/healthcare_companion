from __future__ import annotations

from app.core.config import Settings
from app.core.services import Services, build_services
from app.integrations.fhir import build_fhir_gateway
from app.integrations.notifications import NotificationDispatcher


def build_app_services(settings: Settings) -> Services:
    services = build_services(settings)
    services.notifications = NotificationDispatcher(settings)
    services.fhir = build_fhir_gateway(settings)
    return services
